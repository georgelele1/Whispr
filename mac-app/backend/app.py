"""
app.py — Whispr main pipeline orchestrator.

Responsibilities:
- Transcribe audio to raw text
- Send raw text + active app name to refiner agent
- Save history and session memory
- Expose CLI commands for frontend
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from connectonion.address import load
from connectonion import Agent, host, transcribe

from storage import (
    app_support_dir,
    now_ms,
    save_store,
    load_env_into_os,
    load_profile,
    save_profile,
    load_history,
    append_history,
    get_target_language,
    set_target_language,
    get_model,
    set_model,
    get_agent_model,
    set_api_key,
    remove_api_key,
    has_api_key,
    SUPPORTED_LANGUAGES,
    SUPPORTED_MODELS,
)

from agents.profile import (
    startup_init,
    invalidate_context_cache,
    is_first_launch,
    complete_onboarding,
    learn_profile_now,
    schedule_profile_learning,
)

from agents.plugins.session import session_remember, clear_session
from agents.agent_loop import run as run_agent_loop


BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"

load_env_into_os()
startup_init()


# =========================================================
# Audio transcription
# =========================================================

def _clean_transcription(raw: str) -> str:
    raw = str(raw or "").strip()

    raw = re.sub(
        r"^(sure,?\s+)?(here\s+is\s+the\s+transcription|transcription)[^:：]*[:：]\s*",
        "",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    raw = re.sub(
        r"^(好的[，,\s]*)?(以下是(?:音檔|音频|音訊)?的?逐字稿如下|以下是轉錄結果)[：:\s]*",
        "",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    return raw.strip("「」\"' \n\t")


def _transcribe_audio(audio_path: str) -> str:
    max_retries = 3
    backoff = [2, 5, 10]
    last_error = None

    for attempt in range(max_retries):
        try:
            return _clean_transcription(transcribe(audio_path))
        except Exception as e:
            last_error = e
            err = str(e)

            if any(code in err for code in ("400", "401", "403")):
                raise

            if attempt < max_retries - 1:
                time.sleep(backoff[attempt])

    raise RuntimeError(f"Transcription failed after {max_retries} attempts: {last_error}")


# =========================================================
# Main pipeline
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
    _raw_text_override: str = "",
) -> Dict[str, Any]:

    if _raw_text_override:
        raw_text = str(_raw_text_override).strip()
        audio_path = ""
    else:
        audio_path = str(Path(audio_path).expanduser())

        if not Path(audio_path).exists():
            return {
                "ok": False,
                "error": f"audio file not found: {audio_path}",
                "ts": now_ms(),
            }

        raw_text = _transcribe_audio(audio_path)

    if not raw_text.strip():
        return {
            "ok": False,
            "error": "transcription returned empty",
            "ts": now_ms(),
        }

    effective_app = str(app_name or "unknown").strip() or "unknown"

    loop_result = run_agent_loop(raw_text, effective_app)
    final_text = str(loop_result.get("output", "")).strip()

    session_remember(raw_text, final_text)

    append_history({
        "ts": now_ms(),
        "audio_path": audio_path,
        "raw_text": raw_text,
        "final_text": final_text,
        "app_name": effective_app,
        "target_language": target_language or get_target_language(),
        "route": loop_result.get("route", {}),
        "evaluation": loop_result.get("evaluation", {}),
    })

    schedule_profile_learning()

    return {
        "ok": True,
        "raw_text": raw_text,
        "final_text": final_text,
        "app_name": effective_app,
        "route": loop_result.get("route", {}),
        "evaluation": loop_result.get("evaluation", {}),
        "ts": now_ms(),
    }


# =========================================================
# Orchestrator agent
# =========================================================

def transcribe_and_enhance(audio_path, app_name="", target_language=""):
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        app_name=app_name,
        target_language=target_language,
    )


def create_or_update_profile(
    name="",
    email="",
    organization="",
    role="",
    target_language="",
):
    profile = load_profile()

    for key, value in {
        "name": name,
        "email": email,
        "organization": organization,
        "role": role,
    }.items():
        value = str(value or "").strip()
        if value:
            profile[key] = value

    target_language = str(target_language or "").strip()
    if target_language in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = target_language

    save_profile(profile)
    invalidate_context_cache()

    return {"ok": True, "profile": profile}


def get_profile():
    return {"ok": True, "profile": load_profile()}


def create_agent():
    agent = Agent(
        model=get_agent_model(),
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription, "
            "text refinement, and profile management."
        ),
    )

    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
        for attr in ("add_tool", "add_tools"):
            if hasattr(agent, attr):
                getattr(agent, attr)(fn)
                break

    return agent


# =========================================================
# CLI helpers
# =========================================================

def _exit_json(data, code=0):
    print(json.dumps(data, ensure_ascii=False))
    sys.exit(code)


def _arg(index: int, default: str = "") -> str:
    return sys.argv[index] if len(sys.argv) > index else default


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    if not (len(sys.argv) > 1 and sys.argv[1] == "cli"):
        addr = load(CO_DIR)
        host(create_agent, relay_url=None, whitelist=[addr["address"]], blacklist=[])
        sys.exit(0)

    if len(sys.argv) < 3:
        _exit_json({"ok": False, "error": "missing command"}, 1)

    command = sys.argv[2]

    if command == "transcribe":
        audio_path = _arg(3)
        app_name = _arg(4, "unknown")
        target_language = _arg(5)

        result = transcribe_and_enhance_impl(audio_path, app_name, target_language)
        _exit_json({
            "ok": result.get("ok", False),
            "output": result.get("final_text", ""),
            "route": result.get("route", {}),
            "evaluation": result.get("evaluation", {}),
            "error": result.get("error", ""),
        }, 0 if result.get("ok") else 1)

    elif command == "refine":
        raw_text = _arg(3)
        app_name = _arg(4, "unknown")
        target_language = _arg(5)

        if not raw_text:
            _exit_json({"ok": False, "error": "no text provided"}, 1)

        result = transcribe_and_enhance_impl(
            "",
            app_name,
            target_language,
            _raw_text_override=raw_text,
        )

        _exit_json({
            "ok": result.get("ok", False),
            "input": raw_text,
            "output": result.get("final_text", ""),
            "route": result.get("route", {}),
            "evaluation": result.get("evaluation", {}),
            "error": result.get("error", ""),
        }, 0 if result.get("ok") else 1)

    elif command == "route":
        from agents.agent_loop import classify

        raw_text = _arg(3)
        app_name = _arg(4, "unknown")
        decision = classify(raw_text, app_name)
        _exit_json({"ok": True, "route": decision.__dict__})

    elif command == "learn-profile":
        _exit_json({"ok": learn_profile_now()})

    elif command == "knowledge-search":
        from agents.knowledge_agent import search_knowledge

        query = _arg(3)
        _exit_json(search_knowledge(query))

    elif command == "calendar-query":
        from agents.calendar_agent import query_calendar_events

        start_iso = _arg(3)
        end_iso = _arg(4)
        search_text = _arg(5)
        result = query_calendar_events(start_iso, end_iso, search_text)
        _exit_json(result, 0 if result.get("ok") else 1)

    elif command == "set-language":
        language = _arg(3)
        ok = set_target_language(language)
        _exit_json({
            "ok": ok,
            "language": get_target_language(),
            "supported": SUPPORTED_LANGUAGES,
        }, 0 if ok else 1)

    elif command == "get-language":
        _exit_json({
            "ok": True,
            "language": get_target_language(),
            "supported": SUPPORTED_LANGUAGES,
        })

    elif command == "get-model":
        _exit_json({
            "ok": True,
            "model": get_model(),
            "supported": SUPPORTED_MODELS,
        })

    elif command == "set-model":
        model = _arg(3)
        ok = set_model(model)
        _exit_json({
            "ok": ok,
            "model": get_model(),
            "supported": SUPPORTED_MODELS,
        }, 0 if ok else 1)

    elif command == "get-api-key":
        provider = _arg(3, "openai")
        _exit_json({
            "ok": True,
            "provider": provider,
            "has_key": has_api_key(provider),
        })

    elif command == "set-api-key":
        key = _arg(3)
        provider = _arg(4, "openai")
        ok = set_api_key(key, provider)
        _exit_json({
            "ok": ok,
            "provider": provider,
            "has_key": has_api_key(provider),
        }, 0 if ok else 1)

    elif command == "remove-api-key":
        provider = _arg(3, "openai")
        ok = remove_api_key(provider)
        _exit_json({
            "ok": ok,
            "provider": provider,
            "has_key": has_api_key(provider),
        }, 0 if ok else 1)

    elif command == "set-profile":
        name = _arg(3)
        email = _arg(4)
        organization = _arg(5)
        role = _arg(6)

        profile = load_profile()

        if name:
            profile["name"] = name
        if email:
            profile["email"] = email
        if organization:
            profile["organization"] = organization
        if role:
            profile["role"] = role

        save_profile(profile)
        invalidate_context_cache()
        _exit_json({"ok": True, "profile": profile})

    elif command == "get-profile":
        _exit_json({"ok": True, "profile": load_profile()})

    elif command == "save-profile":
        data = json.loads(_arg(3, "{}"))

        complete_onboarding(
            career_area=data.get("career_area", ""),
            usage_type=data.get("usage_type", []),
            writing_style=data.get("writing_style", "casual"),
            language=data.get("language", ""),
        )

        _exit_json({"ok": True, "profile": load_profile()})

    elif command == "is-first-launch":
        _exit_json({"ok": True, "first_launch": is_first_launch()})

    elif command == "get-history":
        data = load_history()
        items = list(reversed(data.get("items", [])))
        _exit_json({"ok": True, "items": items[:100]})

    elif command == "clear-history":
        save_store("history.json", {"items": []})
        _exit_json({"ok": True})

    elif command == "clear-dictionary":
        save_store("dictionary.json", {"terms": []})
        _exit_json({"ok": True})

    elif command == "clear-snippets":
        (app_support_dir() / "snippets.json").write_text(
            json.dumps({"snippets": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _exit_json({"ok": True})

    elif command == "reset-profile":
        profile = load_profile()

        profile.update({
            "name": "",
            "email": "",
            "organization": "",
            "role": "",
            "career_area": "",
            "usage_type": [],
            "writing_style": "",
            "onboarding_done": False,
            "learned": {
                "description": "",
                "habits": [],
                "frequent_apps": [],
                "last_updated": 0,
                "last_history_ts": 0,
                "learning_started_at": 0,
            },
        })

        save_profile(profile)
        invalidate_context_cache()
        _exit_json({"ok": True, "profile": profile})

    elif command == "reset-all":
        clear_session()
        save_store("history.json", {"items": []})
        save_store("dictionary.json", {"terms": []})

        (app_support_dir() / "snippets.json").write_text(
            json.dumps({"snippets": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        profile = load_profile()
        profile.update({
            "name": "",
            "email": "",
            "organization": "",
            "role": "",
            "career_area": "",
            "usage_type": [],
            "writing_style": "",
            "onboarding_done": False,
            "text_insertions": [],
            "learned": {
                "description": "",
                "habits": [],
                "frequent_apps": [],
                "last_updated": 0,
                "last_history_ts": 0,
                "learning_started_at": 0,
            },
        })

        save_profile(profile)
        invalidate_context_cache()

        _exit_json({"ok": True})

    elif command == "list-insertions":
        from storage import load_text_insertions
        _exit_json({"ok": True, "insertions": load_text_insertions()})

    elif command == "save-insertion":
        from storage import save_text_insertion

        label = _arg(3)
        value = _arg(4)

        _exit_json({"ok": save_text_insertion(label, value)})

    elif command == "remove-insertion":
        from storage import remove_text_insertion

        label = _arg(3)

        _exit_json({"ok": remove_text_insertion(label)})

    else:
        _exit_json({"ok": False, "error": f"unknown command: {command}"}, 1)
