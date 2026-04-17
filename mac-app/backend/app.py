"""
app.py — Whispr main pipeline orchestrator.

Responsibilities:
  - Transcribe audio → raw text
  - Detect intent and dispatch to the right subagent
  - Append to history
  - Expose CLI commands
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

# ── Silence connectonion's stdout chatter before it imports ──────────────────
# connectonion prints [env] and [agent] lines to stdout which breaks our JSON
# output parsing in the Swift client. Redirect stdout temporarily during import,
# then restore it so our own _exit_json() still works.
import io as _io
_real_stdout = sys.stdout
sys.stdout = _io.StringIO()   # swallow any noise during connectonion import

try:
    from connectonion.address import load
    from connectonion import Agent, host
except Exception as _co_err:
    sys.stdout = _real_stdout
    print(f"[whispr] connectonion import failed: {_co_err}", file=sys.stderr)
    raise
finally:
    sys.stdout = _real_stdout  # always restore, even on success
# ─────────────────────────────────────────────────────────────────────────────

from storage import (
    app_support_dir, now_ms, save_store,
    load_profile, save_profile, load_history, append_history,
    get_target_language, set_target_language, SUPPORTED_LANGUAGES,
    get_model, set_model, MODEL_OPTIONS, SUPPORTED_MODELS,
    get_api_key, set_api_key, remove_api_key, has_api_key,
    requires_api_key, load_env_into_os,
)
from agents.profile  import get_user_context, startup_init, invalidate_context_cache
from agents.profile  import is_first_launch, complete_onboarding
from agents.intent   import detect_intent
from agents.plugins.session import session_remember
from agents.refiner  import run as run_refiner
from agents.knowledge import run as run_knowledge
from agents.cal_agent import run as run_calendar

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"


# =========================================================
# Audio transcription
# =========================================================

def _transcribe_audio(audio_path: str) -> str:
    from connectonion import transcribe
    # connectonion.transcribe only supports Gemini (co/) models.
    # If user has selected an OpenAI model, fall back to the default Gemini transcriber.
    model = get_model()
    if not model.startswith("co/"):
        model = "co/gemini-3-flash-preview"
    return transcribe(
        audio_path,
        prompt="Transcribe exactly as spoken. Output ONLY the transcribed words — no preamble, no labels, no phrases like 'Here is the transcription'.",
        model=model,
    ).strip()


# =========================================================
# Main pipeline
# =========================================================

def transcribe_and_enhance_impl(
    audio_path         : str,
    app_name           : str = "",
    target_language    : str = "",
    _raw_text_override : str = "",
) -> Dict[str, Any]:

    t0 = time.perf_counter()

    if _raw_text_override:
        raw_text = _raw_text_override
    else:
        audio_path = str(Path(audio_path).expanduser())
        if not Path(audio_path).exists():
            return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}
        raw_text = _transcribe_audio(audio_path)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app = app_name.strip() or "unknown"

    from agents.refiner import _quick_clean
    intent = detect_intent(_quick_clean(raw_text))

    if intent == "calendar":
        final_text = run_calendar(raw_text, raw_text)
    elif intent == "knowledge":
        final_text = run_knowledge(raw_text)
    else:
        final_text = run_refiner(raw_text, effective_app)

    session_remember(raw_text, final_text)

    append_history({
        "ts":              now_ms(),
        "audio_path":      audio_path if not _raw_text_override else "",
        "raw_text":        raw_text,
        "final_text":      final_text,
        "app_name":        effective_app,
        "target_language": target_language or get_target_language(),
    })

    return {"ok": True, "raw_text": raw_text, "final_text": final_text, "ts": now_ms()}


# =========================================================
# Orchestrator agent
# =========================================================

def create_agent():
    def transcribe_and_enhance(audio_path: str, app_name: str = "", target_language: str = ""):
        return transcribe_and_enhance_impl(audio_path=audio_path, app_name=app_name, target_language=target_language)

    def create_or_update_profile(name: str = "", email: str = "", organization: str = "", role: str = "", target_language: str = ""):
        profile = load_profile()
        for key, val in {"name": name, "email": email, "organization": organization, "role": role}.items():
            if str(val).strip():
                profile[key] = str(val).strip()
        if target_language.strip() in SUPPORTED_LANGUAGES:
            profile.setdefault("preferences", {})["target_language"] = target_language.strip()
        save_profile(profile)
        return {"ok": True, "profile": profile}

    def get_profile():
        return {"ok": True, "profile": load_profile()}

    agent = Agent(
        model=get_model(),
        name="whispr_orchestrator",
        system_prompt="You are Whispr. You orchestrate audio transcription and refinement.",
    )
    for fn in (transcribe_and_enhance, create_or_update_profile, get_profile):
        agent.add_tool(fn)
    return agent


load_env_into_os()   # inject .env → os.environ before any agent runs
startup_init()


# =========================================================
# CLI
# =========================================================

def _exit_json(data, code=0):
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


if __name__ == "__main__":
    if not (len(sys.argv) > 1 and sys.argv[1] == "cli"):
        addr = load(CO_DIR)
        host(create_agent, relay_url=None, whitelist=[addr["address"]], blacklist=[])
        sys.exit(0)

    if len(sys.argv) < 3:
        _exit_json({"output": ""}, 1)

    command = sys.argv[2]

    if command == "transcribe":
        audio_path      = sys.argv[3] if len(sys.argv) > 3 else ""
        app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
        target_language = sys.argv[5] if len(sys.argv) > 5 else ""
        result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
        _exit_json({"output": result.get("final_text", "")})

    elif command == "refine":
        raw_text        = sys.argv[3] if len(sys.argv) > 3 else ""
        app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
        target_language = sys.argv[5] if len(sys.argv) > 5 else ""
        if not raw_text:
            _exit_json({"error": "no text provided"}, 1)
        result = transcribe_and_enhance_impl("", app_name, target_language, _raw_text_override=raw_text)
        _exit_json({"input": raw_text, "output": result.get("final_text", "")})

    elif command == "set-language":
        language = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_target_language(language)
        _exit_json({"ok": ok, "language": language, "supported": SUPPORTED_LANGUAGES}, 0 if ok else 1)

    elif command == "get-language":
        _exit_json({"ok": True, "language": get_target_language(), "supported": SUPPORTED_LANGUAGES})

    elif command == "set-profile":
        name         = sys.argv[3] if len(sys.argv) > 3 else ""
        email        = sys.argv[4] if len(sys.argv) > 4 else ""
        organization = sys.argv[5] if len(sys.argv) > 5 else ""
        role         = sys.argv[6] if len(sys.argv) > 6 else ""
        profile = load_profile()
        if name:         profile["name"]         = name
        if email:        profile["email"]        = email
        if organization: profile["organization"] = organization
        if role:         profile["role"]         = role
        save_profile(profile)
        invalidate_context_cache()
        _exit_json({"ok": True, "profile": profile})

    elif command == "get-profile":
        _exit_json({"ok": True, "profile": load_profile()})

    elif command == "get-history":
        items = list(reversed(load_history().get("items", [])))
        _exit_json({"items": items[:100]})

    elif command == "save-profile":
        data = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        complete_onboarding(
            career_area   = data.get("career_area", ""),
            usage_type    = data.get("usage_type", []),
            writing_style = data.get("writing_style", "casual"),
            language      = data.get("language", ""),
        )
        _exit_json({"ok": True, "profile": load_profile()})

    elif command == "is-first-launch":
        _exit_json({"first_launch": is_first_launch()})

    elif command == "list-insertions":
        from storage import load_text_insertions
        _exit_json({"ok": True, "insertions": load_text_insertions()})

    elif command == "save-insertion":
        from storage import save_text_insertion
        label = sys.argv[3] if len(sys.argv) > 3 else ""
        value = sys.argv[4] if len(sys.argv) > 4 else ""
        _exit_json({"ok": save_text_insertion(label, value)})

    elif command == "remove-insertion":
        from storage import remove_text_insertion
        label = sys.argv[3] if len(sys.argv) > 3 else ""
        _exit_json({"ok": remove_text_insertion(label)})

    elif command == "clear-history":
        save_store("history.json", {"items": []})
        _exit_json({"ok": True})

    elif command == "clear-dictionary":
        save_store("dictionary.json", {"terms": []})
        _exit_json({"ok": True})

    elif command == "clear-snippets":
        (app_support_dir() / "snippets.json").write_text(
            json.dumps({"snippets": []}, indent=2), encoding="utf-8"
        )
        _exit_json({"ok": True})

    elif command == "reset-profile":
        save_profile({
            "name": "", "email": "", "organization": "", "role": "",
            "preferences": {"target_language": get_target_language()},
            "learned": {"description": "", "last_updated": 0},
        })
        invalidate_context_cache()
        _exit_json({"ok": True})

    elif command == "reset-all":
        save_store("history.json",    {"items": []})
        save_store("dictionary.json", {"terms": []})
        (app_support_dir() / "snippets.json").write_text(
            json.dumps({"snippets": []}, indent=2), encoding="utf-8"
        )
        save_profile({
            "name": "", "email": "", "organization": "", "role": "",
            "preferences": {"target_language": get_target_language()},
            "learned": {"description": "", "last_updated": 0},
        })
        invalidate_context_cache()
        _exit_json({"ok": True})

    elif command == "set-model":
        model = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_model(model)
        _exit_json({"ok": ok, "model": model, "options": MODEL_OPTIONS}, 0 if ok else 1)

    elif command == "get-model":
        _exit_json({
            "ok":              True,
            "model":           get_model(),
            "options":         MODEL_OPTIONS,
            "requires_key":    requires_api_key(),
            "has_key":         has_api_key("openai"),
        })

    elif command == "set-api-key":
        # argv: cli set-api-key <key> [provider]
        key      = sys.argv[3] if len(sys.argv) > 3 else ""
        provider = sys.argv[4] if len(sys.argv) > 4 else "openai"
        ok = set_api_key(key, provider)
        _exit_json({"ok": ok}, 0 if ok else 1)

    elif command == "get-api-key":
        provider = sys.argv[3] if len(sys.argv) > 3 else "openai"
        _exit_json({"ok": True, "has_key": has_api_key(provider)})

    elif command == "remove-api-key":
        provider = sys.argv[3] if len(sys.argv) > 3 else "openai"
        ok = remove_api_key(provider)
        _exit_json({"ok": ok})

    elif command == "get-balance":
        try:
            import requests
            result = {"ok": True}

            # ── Connectonion balance ──────────────────────────────
            co_key   = os.environ.get("OPENONION_API_KEY", "")
            base_url = os.environ.get("OPENONION_BASE_URL", "https://oo.openonion.ai")
            if co_key:
                try:
                    resp = requests.get(
                        f"{base_url.rstrip('/')}/api/v1/auth/me",
                        headers={"Authorization": f"Bearer {co_key}"},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        result["connectonion"] = {
                            "balance_usd":    data.get("balance_usd"),
                            "credits_usd":    data.get("credits_usd"),
                            "total_cost_usd": data.get("total_cost_usd"),
                        }
                except Exception as e:
                    result["connectonion_error"] = str(e)

            # ── OpenAI balance ────────────────────────────────────
            oai_key = os.environ.get("OPENAI_API_KEY", "")
            if oai_key:
                try:
                    # Try credit grants endpoint first (prepaid credits)
                    resp = requests.get(
                        "https://api.openai.com/v1/dashboard/billing/credit_grants",
                        headers={"Authorization": f"Bearer {oai_key}"},
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        result["openai"] = {
                            "balance_usd": data.get("total_available"),
                            "granted_usd": data.get("total_granted"),
                            "used_usd":    data.get("total_used"),
                        }
                    else:
                        # Fallback: subscription endpoint for pay-as-you-go
                        resp2 = requests.get(
                            "https://api.openai.com/v1/dashboard/billing/subscription",
                            headers={"Authorization": f"Bearer {oai_key}"},
                            timeout=15,
                        )
                        if resp2.status_code == 200:
                            data2 = resp2.json()
                            result["openai"] = {
                                "balance_usd": None,
                                "plan":        data2.get("plan", {}).get("title", "Pay as you go"),
                                "note":        "Pay-as-you-go — no prepaid balance",
                            }
                        else:
                            result["openai_error"] = f"HTTP {resp.status_code}"
                except Exception as e:
                    result["openai_error"] = str(e)

            _exit_json(result)
        except Exception as e:
            _exit_json({"ok": False, "error": str(e)})

    elif command == "calendar":
        text = sys.argv[3] if len(sys.argv) > 3 else "today"
        _exit_json({"output": run_calendar(text, text)})

    else:
        audio_path      = sys.argv[2]
        app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
        target_language = sys.argv[4] if len(sys.argv) > 4 else ""
        result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
        _exit_json({"output": result.get("final_text", "")})