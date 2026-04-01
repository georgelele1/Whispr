from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

# Swallow [env] line connectonion prints to stdout on import
import io as _io
_real_stdout, _real_stderr = sys.stdout, sys.stderr
sys.stdout = sys.stderr = _io.StringIO()
try:
    from connectonion.address import load
    from connectonion import Agent, host, transcribe
finally:
    sys.stdout = _real_stdout
    sys.stderr = _real_stderr

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"

SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"

ENABLE_SELF_CORRECT = False
SCORE_THRESHOLD     = 70
MAX_RETRIES         = 2

# ── Intent deny regex (0ms) ───────────────────────────────
# Calendar words present but clearly NOT a fetch request
_CALENDAR_DENY = re.compile(
    r"\b("
    r"(my |the )?(calendar|schedule) is (full|busy|packed|crazy|hectic|clear|empty|free)"
    r"|don.?t have time|no time for|too busy|out of time|running late"
    r"|already (booked|scheduled|taken|busy)"
    r"|cancel(led)? (the |my )?(meeting|appointment|event)"
    r"|reschedule|missed (the |my )?(meeting|appointment)"
    r")\b",
    re.IGNORECASE,
)


# =========================================================
# Storage helpers
# =========================================================

def app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME
    else:
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def storage_path(filename: str) -> Path:
    return app_support_dir() / filename


def now_ms() -> int:
    return int(time.time() * 1000)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return _read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    _write_json(storage_path(filename), data)


# =========================================================
# Profile / history / dictionary
# =========================================================

def load_profile() -> Dict[str, Any]:
    return load_store(PROFILE_FILE, {
        "name": "", "email": "", "organization": "", "role": "",
        "preferences": {"target_language": DEFAULT_LANGUAGE},
    })


def save_profile(profile: Dict[str, Any]) -> None:
    save_store(PROFILE_FILE, profile)


def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, {"items": []})


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data  = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)


def get_target_language() -> str:
    lang = load_profile().get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_target_language(language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["target_language"] = language
    save_profile(profile)
    return True


# =========================================================
# Common helpers
# =========================================================

def _clean(result: Any) -> str:
    return str(result).strip().strip('"').strip("'").strip()


def register_tool(agent: Agent, fn: Callable[..., Any]) -> None:
    for attr in ("add_tools", "add_tool"):
        if hasattr(agent, attr) and callable(getattr(agent, attr)):
            getattr(agent, attr)(fn)
            return
    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return
    raise RuntimeError("Cannot register tool.")


# =========================================================
# Dictionary corrections
# =========================================================

def get_dictionary_terms() -> Dict[str, Any]:
    """Tool: return approved dictionary terms for the refiner agent."""
    terms = [
        {"phrase": str(item.get("phrase", "")).strip(), "aliases": item.get("aliases", [])}
        for item in load_dictionary().get("terms", [])
        if item.get("approved", True) and str(item.get("phrase", "")).strip()
    ]
    return {"terms": terms, "count": len(terms)}


def apply_dictionary_corrections(text: str) -> str:
    """Fallback regex corrections — used when agent is skipped."""
    if not text.strip():
        return text
    result = text
    for item in load_dictionary().get("terms", []):
        if not item.get("approved", True):
            continue
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        for alias in item.get("aliases", []):
            alias = str(alias).strip()
            if alias:
                result = re.sub(
                    rf"\b{re.escape(alias)}\b", phrase, result, flags=re.IGNORECASE
                )
    return result


# =========================================================
# Intent detection
#
# Tier 1 (0ms):   Hard deny regex — obvious non-calendar text
# Tier 2 (~7s):   Agent — classifies text/calendar/search/snippet
# =========================================================

def _load_snippet_triggers() -> List[str]:
    try:
        from snippets import load_snippets
        return [
            item["trigger"]
            for item in load_snippets().get("snippets", [])
            if item.get("enabled", True) and str(item.get("trigger", "")).strip()
        ]
    except Exception:
        return []


def detect_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    if _CALENDAR_DENY.search(raw_text):
        print("[intent] deny → text", file=sys.stderr)
        return {"type": "text", "trigger": None, "date": None, "calendar": None}

    triggers_hint = (
        f"Known snippet triggers: {json.dumps(snippet_triggers)}. "
        if snippet_triggers else ""
    )
    agent = Agent(
        model="gpt-5",
        name="whispr_intent_detector",
        system_prompt=(
            "Classify voice input into exactly one type: text, calendar, search, or snippet.\n"
            "calendar = user wants to SEE their schedule for a date.\n"
            "search   = user wants to FIND a specific event by name (exam, deadline, dentist etc).\n"
            "snippet  = user EXPLICITLY requests a shortcut using action words like "
            "'give me', 'insert', 'paste', 'use', 'open', 'show me'. "
            "NOT snippet if the trigger appears naturally mid-sentence.\n"
            "text     = everything else, including sentences that mention shortcut keywords naturally.\n"
            + triggers_hint +
            'Reply ONLY with JSON: {"type":"...","trigger":null,"date":"today|tomorrow|YYYY-MM-DD|null","calendar":"name|all|null"}'
        ),
    )
    try:
        result = json.loads(_clean(agent.input(raw_text)))
        if result.get("type") not in {"text", "calendar", "search", "snippet"}:
            result["type"] = "text"
        print(f"[intent] agent → {result['type']}", file=sys.stderr)
        return result
    except Exception:
        print("[intent] agent failed → text", file=sys.stderr)
        return {"type": "text", "trigger": None, "date": None, "calendar": None}


# =========================================================
# AI refine
# =========================================================

def ai_refine_text(
    text: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    if not text.strip():
        return text

    lang = target_language.strip()
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = get_target_language()

    # Skip LLM for short clean English text
    if (lang == "English"
            and len(text.split()) < 5
            and not re.search(r"\b(uh|um|er|so so|I I|the the)\b", text, re.IGNORECASE)):
        return apply_dictionary_corrections(text)

    app_hint = (
        f"Active app: {app_name.strip()}. "
        if app_name.strip() and app_name.strip() != "unknown"
        else ""
    )
    translate_step = f"4. Translate to {lang} if needed." if lang != "English" else ""

    # Only inject dictionary tool if terms exist — skips extra LLM call when empty
    has_dictionary = bool(load_dictionary().get("terms"))
    dict_step      = "1. Call get_dictionary_terms and apply corrections. " if has_dictionary else ""
    step_offset    = 2 if has_dictionary else 1

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are a voice transcription cleaner. "
            f"{app_hint}"
            f"Output language: {lang}. "
            f"{dict_step}"
            f"{step_offset}. Remove stutters, false starts, filler words (uh, um, like), repeated words. "
            f"{step_offset+1}. Fix punctuation and capitalisation. "
            f"{translate_step} "
            "Output ONLY the final cleaned text."
        ),
    )
    if has_dictionary:
        register_tool(agent, get_dictionary_terms)

    return _clean(agent.input(text))


# =========================================================
# Self-correction  (disabled in hot path)
# =========================================================

def self_correct_text(
    raw_text: str,
    refined: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    if not ENABLE_SELF_CORRECT:
        return refined
    try:
        from Eval_run import run_refinement_eval
    except ImportError:
        return refined

    current    = refined
    best       = refined
    best_score = 0
    lang       = target_language.strip() or get_target_language()

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text": raw_text, "final_text": current, "app_name": app_name,
        }], verbose=False)
        if not results:
            break
        score, reason = results[0]["score"], results[0]["reason"]
        if score > best_score:
            best_score, best = score, current
        print(f"[self-correct] attempt {attempt+1} score={score}/100", file=sys.stderr)
        if score >= SCORE_THRESHOLD:
            break
        current = _clean(Agent(
            model="gpt-5", name="whispr_self_corrector",
            system_prompt=f"Fix issues. Output ONLY corrected {lang} text.",
        ).input(f"Raw: {raw_text}\nPrevious: {current}\nFeedback: {reason}"))

    return best


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio and strip connectonion wrapper preamble."""
    raw = str(transcribe(audio_path)).strip()
    raw = re.sub(
        r"^(sure,?\s+)?(here\s+is\s+the\s+transcription|transcription)[^:]*:\s*",
        "", raw, flags=re.IGNORECASE | re.DOTALL
    ).strip()
    return raw


# =========================================================
# Inline snippet replacement
# Replaces trigger words found anywhere in refined text with their expansion.
# e.g. "send the zoom link to John" → "send https://zoom.us/j/123 to John"
# Only static snippets — dynamic (calendar) are skipped here.
# =========================================================

def apply_inline_snippets(text: str) -> str:
    """Replace snippet triggers found inline in text with their expansion."""
    if not text.strip():
        return text
    try:
        from snippets import load_snippets, DYNAMIC_TRIGGERS
        snippets = {
            item["trigger"].lower(): item["expansion"]
            for item in load_snippets().get("snippets", [])
            if item.get("enabled", True)
            and str(item.get("trigger", "")).strip()
            and str(item.get("expansion", "")).strip()
            and item["trigger"].lower() not in DYNAMIC_TRIGGERS
        }
        result = text
        for trigger, expansion in snippets.items():
            result = re.sub(
                rf"{re.escape(trigger)}",
                expansion,
                result,
                flags=re.IGNORECASE,
            )
        return result
    except Exception:
        return text


# =========================================================
# Core pipeline
#
# Agent calls per request:
#   text:              intent (~7s) + refine (~8s) = ~15s
#   calendar/search:   intent (~7s) + API (~3s)    = ~10s
#   snippet:           intent (~7s) + local (0ms)  = ~7s
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:

    audio_path = str(Path(audio_path).expanduser())
    if not Path(audio_path).exists():
        return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}

    t0 = time.perf_counter()

    # 1. Transcribe
    raw_text = transcribe_audio(audio_path)
    t1 = time.perf_counter()
    print(f"[pipeline] transcribe {(t1-t0)*1000:.0f}ms  {raw_text[:60]!r}", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app    = app_name.strip() or "unknown"
    snippet_triggers = _load_snippet_triggers()
    final_text       = raw_text

    try:
        # 2. Detect intent
        intent      = detect_intent(raw_text, snippet_triggers)
        intent_type = intent.get("type", "text")
        print(f"[pipeline] intent={intent_type} {(time.perf_counter()-t1)*1000:.0f}ms", file=sys.stderr)

        # 3. Route
        if intent_type == "search":
            from gcalendar import search_events, extract_search_intent
            import getpass
            si = extract_search_intent(raw_text)
            final_text = search_events(
                query=si.get("query") or raw_text,
                user_id=getpass.getuser(),
                calendar_filter=si.get("calendar") or "all",
            )

        elif intent_type == "calendar":
            from gcalendar import get_schedule, extract_calendar_intent
            import getpass
            cal = extract_calendar_intent(raw_text)
            final_text = get_schedule(
                date=cal.get("date") or "today",
                user_id=getpass.getuser(),
                calendar_filter=cal.get("calendar") or "all",
            )

        elif intent_type == "snippet":
            trigger = intent.get("trigger")
            try:
                from snippets import load_snippets, DYNAMIC_TRIGGERS, handle_dynamic_trigger
                snippets = {
                    item["trigger"]: item["expansion"]
                    for item in load_snippets().get("snippets", [])
                    if item.get("enabled", True)
                }
                if trigger and trigger in snippets:
                    final_text = (
                        handle_dynamic_trigger(trigger, raw_text)
                        if trigger.lower() in DYNAMIC_TRIGGERS
                        else snippets[trigger]
                    )
                else:
                    intent_type = "text"
            except Exception:
                intent_type = "text"

        if intent_type == "text":
            refined    = ai_refine_text(raw_text, effective_app, target_language)
            corrected  = self_correct_text(raw_text, refined, effective_app, target_language)
            final_text = apply_inline_snippets(corrected)

    except Exception as exc:
        print(f"[pipeline] error — fallback: {exc}", file=sys.stderr)
        final_text = apply_dictionary_corrections(raw_text)

    print(f"[pipeline] total {(time.perf_counter()-t0)*1000:.0f}ms", file=sys.stderr)

    append_history({
        "ts":              now_ms(),
        "audio_path":      audio_path,
        "raw_text":        raw_text,
        "final_text":      final_text,
        "app_name":        effective_app,
        "target_language": target_language or get_target_language(),
    })

    return {"ok": True, "raw_text": raw_text, "final_text": final_text, "ts": now_ms()}


# =========================================================
# Agent tool functions
# =========================================================

def create_or_update_profile(
    name: str = "", email: str = "",
    organization: str = "", role: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    profile = load_profile()
    for key, val in {"name": name, "email": email, "organization": organization, "role": role}.items():
        if str(val).strip():
            profile[key] = str(val).strip()
    if target_language.strip() in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = target_language.strip()
    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def transcribe_and_enhance(
    audio_path: str, app_name: str = "", target_language: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path, app_name=app_name, target_language=target_language,
    )


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt="You are Whispr. You orchestrate audio transcription and refinement.",
    )
    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
        register_tool(agent, fn)
    return agent


# =========================================================
# CLI / host
# =========================================================

def _exit_json(data: Dict[str, Any], code: int = 0) -> None:
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

    elif command == "calendar":
        import getpass
        text    = sys.argv[3] if len(sys.argv) > 3 else "today"
        user_id = sys.argv[4] if len(sys.argv) > 4 else getpass.getuser()
        try:
            from gcalendar import get_schedule, extract_calendar_intent
            intent = extract_calendar_intent(text)
            _exit_json({"output": get_schedule(
                date=intent.get("date", "today"),
                user_id=user_id,
                calendar_filter=intent.get("calendar", "all"),
            )})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)

    elif command == "refine":
        # Test refine pipeline with raw text — no audio file needed
        # Usage: python app.py cli refine "uh so the meeting is uh tomorrow" [app_name] [language]
        raw_text        = sys.argv[3] if len(sys.argv) > 3 else ""
        app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
        target_language = sys.argv[5] if len(sys.argv) > 5 else ""
        if not raw_text:
            _exit_json({"error": "no text provided"}, 1)
        try:
            snippet_triggers = _load_snippet_triggers()
            intent           = detect_intent(raw_text, snippet_triggers)
            intent_type      = intent.get("type", "text")
            print(f"[test] intent={intent_type}", file=sys.stderr)

            if intent_type == "search":
                from gcalendar import search_events, extract_search_intent
                import getpass
                si = extract_search_intent(raw_text)
                output = search_events(query=si.get("query") or raw_text, user_id=getpass.getuser())
            elif intent_type == "calendar":
                from gcalendar import get_schedule, extract_calendar_intent
                import getpass
                cal = extract_calendar_intent(raw_text)
                output = get_schedule(date=cal.get("date") or "today", user_id=getpass.getuser())
            else:
                refined = ai_refine_text(raw_text, app_name, target_language)
                output  = self_correct_text(raw_text, refined, app_name, target_language)

            _exit_json({"input": raw_text, "intent": intent_type, "output": output})
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            _exit_json({"output": ""}, 1)

    elif command == "set-language":
        language = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_target_language(language)
        _exit_json({
            "ok": ok, "language": language,
            "error": f"unsupported: {language}" if not ok else None,
            "supported": SUPPORTED_LANGUAGES,
        }, 0 if ok else 1)

    elif command == "get-language":
        _exit_json({"ok": True, "language": get_target_language(), "supported": SUPPORTED_LANGUAGES})

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