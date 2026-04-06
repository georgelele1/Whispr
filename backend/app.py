"""
app.py — Whispr main pipeline orchestrator.

Thin entry point — all logic lives in agents/ modules:
  agents/profile.py   — user context + profile learning
  agents/knowledge.py — facts, formulas, definitions
  agents/refiner.py   — text cleaning and formatting
  agents/router.py    — intent detection and routing

Other modules:
  storage.py          — shared disk read/write helpers
  gcalendar.py        — Google Calendar integration
  snippets.py         — voice shortcuts
  dictionary_agent.py — personal dictionary learning
"""
from __future__ import annotations

import io as _io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import threading as _threading

# Ensure backend root is on sys.path — required on Windows
import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parent)
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

_real_stdout, _real_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = _io.StringIO()
try:
    from connectonion.address import load
    from connectonion import Agent, host, transcribe
finally:
    sys.stdout = _real_stdout
    sys.stderr = _real_stderr

from storage import (
    app_support_dir, storage_path, now_ms, load_store, save_store,
    load_profile, save_profile, load_dictionary, load_history, append_history,
    get_target_language, set_target_language, apply_dictionary_corrections,
    SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, APP_NAME,
)
from agents.profile   import get_user_context, startup_init
from agents.refiner   import ai_refine_text, quick_clean
from agents.router    import route, _load_snippet_triggers
from agents.plugins.knowledge import session_remember

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"


def transcribe_audio(audio_path: str) -> str:
    import re
    raw = str(transcribe(audio_path)).strip()
    raw = re.sub(
        r"^(sure,?\s+)?(here\s+is\s+the\s+transcription|transcription)[^:]*:\s*",
        "", raw, flags=re.IGNORECASE | re.DOTALL
    ).strip()
    return raw


def apply_inline_snippets(text: str) -> str:
    import re
    if not text.strip():
        return text
    try:
        from snippets import load_snippets
        dynamic  = {"calendar"}
        snippets = {
            item["trigger"].lower(): item["expansion"]
            for item in load_snippets().get("snippets", [])
            if item.get("enabled", True)
            and str(item.get("trigger", "")).strip()
            and str(item.get("expansion", "")).strip()
            and item["trigger"].lower() not in dynamic
        }
        if not snippets:
            return text
        result = text
        for trigger, expansion in snippets.items():
            result = re.sub(rf"\b{re.escape(trigger)}\b", expansion, result, flags=re.IGNORECASE)
        return result
    except Exception as e:
        print(f"[snippets] inline error: {e}", file=sys.stderr)
        return text


def transcribe_and_enhance_impl(
    audio_path         : str,
    app_name           : str = "",
    target_language    : str = "",
    _raw_text_override : str = "",
) -> Dict[str, Any]:

    t0 = time.perf_counter()

    if _raw_text_override:
        raw_text = _raw_text_override
        print(f"[pipeline] text override: {raw_text[:60]!r}", file=sys.stderr)
    else:
        audio_path = str(Path(audio_path).expanduser())
        if not Path(audio_path).exists():
            return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}
        raw_text = transcribe_audio(audio_path)
        print(f"[pipeline] transcribe {(time.perf_counter()-t0)*1000:.0f}ms  {raw_text[:60]!r}", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app    = app_name.strip() or "unknown"
    snippet_triggers = _load_snippet_triggers()
    user_context     = get_user_context()
    final_text       = raw_text

    try:
        clean_text = quick_clean(raw_text)
        print(f"[pipeline] pre-clean: {clean_text[:60]!r}", file=sys.stderr)

        result = route(
            raw_text        = raw_text,
            clean_text      = clean_text,
            snippet_triggers= snippet_triggers,
            app_name        = app_name,
            target_language = target_language,
            user_context    = user_context,
            effective_app   = effective_app,
        )

        if result is not None:
            final_text = result
        else:
            refined    = ai_refine_text(
                raw_text,
                app_name        = effective_app,
                target_language = target_language,
                user_context    = user_context,
            )
            final_text = apply_inline_snippets(refined)
            session_remember(raw_text, final_text)

    except Exception as exc:
        print(f"[pipeline] error — fallback: {exc}", file=sys.stderr)
        final_text = apply_dictionary_corrections(raw_text)

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


def transcribe_and_enhance(audio_path, app_name="", target_language=""):
    return transcribe_and_enhance_impl(audio_path=audio_path, app_name=app_name, target_language=target_language)


def _register_tool(agent, fn):
    for attr in ("add_tools", "add_tool"):
        if hasattr(agent, attr) and callable(getattr(agent, attr)):
            getattr(agent, attr)(fn)
            return


def create_agent():
    agent = Agent(model="gpt-5", name="whispr_orchestrator",
                  system_prompt="You are Whispr. You orchestrate audio transcription and refinement.")
    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
        _register_tool(agent, fn)
    return agent


startup_init()


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
        print(f"PATH: {audio_path}  EXISTS: {os.path.exists(audio_path)}  LANG: {target_language or get_target_language()}", file=sys.stderr)
        try:
            result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
            _exit_json({"output": result.get("final_text", "")})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)

    elif command == "refine":
        raw_text        = sys.argv[3] if len(sys.argv) > 3 else ""
        app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
        target_language = sys.argv[5] if len(sys.argv) > 5 else ""
        if not raw_text:
            _exit_json({"error": "no text provided"}, 1)
        try:
            result = transcribe_and_enhance_impl("", app_name, target_language, _raw_text_override=raw_text)
            _exit_json({"input": raw_text, "intent": "agent", "output": result.get("final_text", "")})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)

    elif command == "calendar":
        import getpass
        text    = sys.argv[3] if len(sys.argv) > 3 else "today"
        user_id = sys.argv[4] if len(sys.argv) > 4 else getpass.getuser()
        try:
            from gcalendar import get_schedule, extract_calendar_intent
            intent = extract_calendar_intent(text)
            _exit_json({"output": get_schedule(date=intent.get("date", "today"), user_id=user_id, calendar_filter=intent.get("calendar", "all"))})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)

    elif command == "set-language":
        language = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_target_language(language)
        _exit_json({"ok": ok, "language": language, "error": f"unsupported: {language}" if not ok else None, "supported": SUPPORTED_LANGUAGES}, 0 if ok else 1)

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
        # Invalidate context cache so next call picks up new values
        from agents.profile import invalidate_context_cache
        invalidate_context_cache()
        _exit_json({"ok": True, "profile": profile})

    elif command == "get-profile":
        _exit_json({"ok": True, "profile": load_profile()})

    elif command == "get-language":
        _exit_json({"ok": True, "language": get_target_language(), "supported": SUPPORTED_LANGUAGES})

    elif command == "get-history":
        data  = load_history()
        items = list(reversed(data.get("items", [])))
        _exit_json({"items": items[:100]})

    # ── Data-management commands ─────────────────────────────────────────────

    elif command == "clear-history":
        save_store("history.json", {"items": []})
        _exit_json({"ok": True, "message": "History cleared"})

    elif command == "clear-dictionary":
        save_store("dictionary.json", {"terms": []})
        _exit_json({"ok": True, "message": "Dictionary cleared"})

    elif command == "clear-snippets":
        snippets_path = app_support_dir() / "snippets.json"
        snippets_path.write_text(
            json.dumps({"snippets": []}, indent=2), encoding="utf-8"
        )
        _exit_json({"ok": True, "message": "Snippets cleared"})

    elif command == "reset-profile":
        current_lang  = get_target_language()
        blank_profile = {
            "name": "", "email": "", "organization": "", "role": "",
            "preferences": {"target_language": current_lang},
            "learned": {"description": "", "last_updated": 0},
        }
        save_profile(blank_profile)
        try:
            from agents.profile import invalidate_context_cache
            invalidate_context_cache()
        except Exception:
            pass
        _exit_json({"ok": True, "message": "Profile reset", "profile": blank_profile})

    elif command == "reset-all":
        save_store("history.json",    {"items": []})
        save_store("dictionary.json", {"terms": []})
        snippets_path = app_support_dir() / "snippets.json"
        snippets_path.write_text(
            json.dumps({"snippets": []}, indent=2), encoding="utf-8"
        )
        current_lang  = get_target_language()
        blank_profile = {
            "name": "", "email": "", "organization": "", "role": "",
            "preferences": {"target_language": current_lang},
            "learned": {"description": "", "last_updated": 0},
        }
        save_profile(blank_profile)
        try:
            from agents.profile import invalidate_context_cache
            invalidate_context_cache()
        except Exception:
            pass
        _exit_json({"ok": True, "message": "Full reset complete"})

    else:
        audio_path      = sys.argv[2]
        app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
        target_language = sys.argv[4] if len(sys.argv) > 4 else ""
        print(f"PATH: {audio_path}  EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)
        try:
            result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
            _exit_json({"output": result.get("final_text", "")})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)