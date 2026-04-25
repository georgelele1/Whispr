"""
app.py — Whispr main pipeline orchestrator.

Responsibilities:
  - Transcribe audio → raw text
  - Dispatch to refiner
  - Append to history
  - Expose CLI commands

All context injection, language, eval, snippet expansion, and background
updates are handled inside the refiner via on_events — not here.

File layout:
  app.py
  dictionary_agent.py
  snippets.py
  storage.py
  agents/
    profile.py
    refiner.py
  plugins/
    __init__.py
    lang.py
    visibility.py
    eval.py
    snippets.py
    session.py
"""
from __future__ import annotations

import io as _io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parent)
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

_real_stdout, _real_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = _io.StringIO()
from connectonion.address import load
from connectonion import Agent, host, transcribe
sys.stdout = _real_stdout
sys.stderr = _real_stderr

from storage import _env_path
from storage import (
    app_support_dir, now_ms, load_store, save_store,
    load_profile, save_profile, load_history, append_history,
    get_target_language, set_target_language,
    get_model, set_model, get_agent_model,
    get_api_key, set_api_key, remove_api_key, has_api_key,
    SUPPORTED_LANGUAGES, SUPPORTED_MODELS, MODEL_OPTIONS,
)
from agents.profile  import get_user_context, startup_init, invalidate_context_cache
from agents.profile  import is_first_launch, complete_onboarding
from agents.plugins.session import session_remember
from agents.refiner  import run as run_refiner

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"


# =========================================================
# Audio transcription
# =========================================================

def _transcribe_audio(audio_path: str) -> str:
    import re
    import time as _time

    MAX_RETRIES = 3
    BACKOFF     = [2, 5, 10]

    def _clean(raw: str) -> str:
        raw = re.sub(
            r"^(sure,?\s+)?(here\s+is\s+the\s+transcription|transcription)[^:ï¼]*[:ï¼]\s*",
            "", raw, flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        raw = re.sub(
            r"^(好的[，,\s]*)?(以下是(?:音檔|音频|音訊)?的?逐字稿如下|以下是轉錄結果)[：:\s]*",
            "", raw, flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        return raw.strip("「」\"' \n\t")

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return _clean(str(transcribe(audio_path)).strip())
        except Exception as e:
            last_error = e
            err_str = str(e)
            if any(code in err_str for code in ("400", "401", "403")):
                raise
            if attempt < MAX_RETRIES - 1:
                wait = BACKOFF[attempt]
                print(f"[transcribe] attempt {attempt + 1} failed ({err_str[:80]}), retrying in {wait}s…", file=sys.stderr)
                _time.sleep(wait)

    raise RuntimeError(f"Transcription failed after {MAX_RETRIES} attempts: {last_error}")


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
        print(f"[pipeline] transcribe {(time.perf_counter()-t0)*1000:.0f}ms  {raw_text[:60]!r}", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app = app_name.strip() or "unknown"

    final_text = run_refiner(raw_text, effective_app)

    session_remember(raw_text, final_text)

    print(f"[pipeline] total {(time.perf_counter()-t0)*1000:.0f}ms", file=sys.stderr)

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

def transcribe_and_enhance(audio_path, app_name="", target_language=""):
    return transcribe_and_enhance_impl(audio_path=audio_path, app_name=app_name, target_language=target_language)


def create_or_update_profile(name="", email="", organization="", role="", target_language=""):
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


def create_agent():
    agent = Agent(
        model=get_agent_model(),   # reads from storage instead of hardcoded "gpt-5"
        name="whispr_orchestrator",
        system_prompt="You are Whispr. You orchestrate audio transcription and refinement.",
    )
    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
        for attr in ("add_tools", "add_tool"):
            if hasattr(agent, attr):
                getattr(agent, attr)(fn)
                break
    return agent


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
        print(f"PATH: {audio_path}  EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)
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

    # ── Model management ──────────────────────────────────

    elif command == "get-model":
        _exit_json({"ok": True, "model": get_model(), "supported": SUPPORTED_MODELS})

    elif command == "set-model":
        model = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_model(model)
        _exit_json({"ok": ok, "model": get_model()}, 0 if ok else 1)

    # ── API key management ────────────────────────────────

    elif command == "get-api-key":
        provider = sys.argv[3] if len(sys.argv) > 3 else "openai"
        _exit_json({"ok": True, "has_key": has_api_key(provider), "provider": provider})

    elif command == "set-api-key":
        key      = sys.argv[3] if len(sys.argv) > 3 else ""
        provider = sys.argv[4] if len(sys.argv) > 4 else "openai"
        print(f"[set-api-key] provider={provider!r} key_len={len(key)} key_prefix={key[:6]!r}", file=sys.stderr)
        print(f"[set-api-key] env_path={str(_env_path())}", file=sys.stderr)
        print(f"[set-api-key] env_path_exists={_env_path().parent.exists()}", file=sys.stderr)
        try:
            ok = set_api_key(key, provider)
            print(f"[set-api-key] set_api_key returned ok={ok}", file=sys.stderr)
        except Exception as e:
            print(f"[set-api-key] EXCEPTION: {e}", file=sys.stderr)
            ok = False
        _exit_json({"ok": ok}, 0 if ok else 1)

    elif command == "remove-api-key":
        provider = sys.argv[3] if len(sys.argv) > 3 else "openai"
        ok = remove_api_key(provider)
        _exit_json({"ok": ok}, 0 if ok else 1)

    # ── Balance ───────────────────────────────────────────

    elif command == "get-balance":
        result: Dict[str, Any] = {"ok": True}

        # Connectonion balance — read from connectonion balance API if available
        try:
            from connectonion import get_balance as _co_balance
            co = _co_balance()
            result["connectonion"] = {
                "balance_usd":    co.get("balance_usd") or co.get("balance"),
                "total_cost_usd": co.get("total_cost_usd") or co.get("used"),
            }
        except Exception:
            result["connectonion"] = {"balance_usd": None, "total_cost_usd": None}

        # OpenAI balance — only attempt if key exists
        if has_api_key("openai"):
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://api.openai.com/v1/dashboard/billing/credit_grants",
                    headers={"Authorization": f"Bearer {get_api_key('openai')}"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read())
                result["openai"] = {
                    "balance_usd": data.get("total_available"),
                    "plan": None,
                }
            except Exception:
                result["openai"] = {"balance_usd": None, "plan": "Pay as you go"}
        else:
            result["openai"] = {"balance_usd": None, "plan": None}

        _exit_json(result)

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
        data  = load_history()
        items = list(reversed(data.get("items", [])))
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
        from agents.plugins.session import clear_session
        clear_session()
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

    elif command == "calendar":
        text = sys.argv[3] if len(sys.argv) > 3 else "today"
        _exit_json({"output": run_calendar(text, text)})

    else:
        audio_path      = sys.argv[2]
        app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
        target_language = sys.argv[4] if len(sys.argv) > 4 else ""
        result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
        _exit_json({"output": result.get("final_text", "")})