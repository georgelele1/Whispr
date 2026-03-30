from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host, transcribe

# ── Suppress connectonion eval/log files in production ───
os.environ["CO_EVALS"] = "0"
os.environ["CO_LOGS"]  = "0"

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

# ── Self-correction: off by default (too slow for real-time) ─
ENABLE_SELF_CORRECT = False
SCORE_THRESHOLD     = 70
MAX_RETRIES         = 2

# ── Calendar intent regexes ───────────────────────────────

# Tier 1: calendar words present but clearly NOT a fetch request
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

# Tier 2: unambiguously requesting a calendar fetch
_CALENDAR_ALLOW = re.compile(
    r"\b("
    r"(show|check|see|get|what.?s|give me|tell me|look at|open|pull up|read)"
    r"\s+(me\s+)?(my\s+)?(schedule|calendar|events?|agenda|appointments?|meetings?)"
    r"|what.?s\s+(on|happening)\s+(today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday)"
    r"|am\s+i\s+(free|available|busy)\s+(today|tomorrow|on|this|next)"
    r"|do\s+i\s+have\s+(anything|something|a meeting|an appointment)"
    r"|what\s+time\s+is\s+my|when\s+is\s+my\s+next"
    r")\b",
    re.IGNORECASE,
)

# Tier 3 gate: calendar keywords that might be ambiguous
_CALENDAR_KEYWORDS = re.compile(
    r"\b(schedule|calendar|events?|meeting|appointment|agenda|free|available|busy)\b",
    re.IGNORECASE,
)

# Snippet: action verb + known trigger word
_SNIPPET_ALLOW = re.compile(
    r"^\s*(give me|insert|paste|use|add|put|show me|open|pull up)\b",
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
# Profile / history / dictionary accessors
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
    """Tool: return approved dictionary terms so the refiner agent
    can apply corrections in context during refinement."""
    terms = [
        {"phrase": str(item.get("phrase", "")).strip(),
         "aliases": item.get("aliases", [])}
        for item in load_dictionary().get("terms", [])
        if item.get("approved", True) and str(item.get("phrase", "")).strip()
    ]
    return {"terms": terms, "count": len(terms)}


def apply_dictionary_corrections(text: str) -> str:
    """Fallback regex corrections — used only when agent is skipped (short clean text)."""
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
# Intent detection — 3-tier hybrid
#
#  Tier 1 (0ms)   hard DENY regex  — calendar words but NOT a request
#  Tier 2 (0ms)   hard ALLOW regex — unambiguous fetch request
#  Tier 3 (~1.5s) LLM fallback     — ambiguous calendar context only
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


def _llm_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    agent = Agent(
        model="gpt-5",
        name="whispr_intent_detector",
        system_prompt=(
            "Classify voice input as 'text', 'calendar', or 'snippet'. "
            "'calendar' = user REQUESTS to SEE/CHECK their schedule or events — "
            "NOT if they are merely mentioning being busy. "
            "'snippet' = user requests a known shortcut by name. "
            "'text' = normal dictation. "
            + (f"Known snippet triggers: {json.dumps(snippet_triggers)}. " if snippet_triggers else "")
            + 'Reply ONLY with JSON: {"type":"...","trigger":null,"date":"today|tomorrow|YYYY-MM-DD","calendar":"name|all"}'
        ),
    )
    try:
        result = json.loads(_clean(agent.input(raw_text)))
        if result.get("type") not in {"text", "calendar", "snippet"}:
            result["type"] = "text"
        return result
    except Exception:
        return {"type": "text", "trigger": None, "date": None, "calendar": None}


def detect_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    text_lower = raw_text.lower()

    # Tier 1: hard deny
    if _CALENDAR_DENY.search(raw_text):
        print("[intent] deny → text", file=sys.stderr)
        return {"type": "text", "trigger": None, "date": None, "calendar": None}

    # Snippet check
    if _SNIPPET_ALLOW.search(raw_text):
        for trigger in snippet_triggers:
            if trigger.lower() in text_lower:
                print(f"[intent] snippet → {trigger}", file=sys.stderr)
                return {"type": "snippet", "trigger": trigger, "date": None, "calendar": None}

    # Tier 2: hard allow
    if _CALENDAR_ALLOW.search(raw_text):
        print("[intent] allow → calendar", file=sys.stderr)
        return {"type": "calendar", "trigger": None, "date": None, "calendar": None}

    # Tier 3: LLM only when keywords present but ambiguous
    if _CALENDAR_KEYWORDS.search(raw_text):
        print("[intent] ambiguous → LLM", file=sys.stderr)
        return _llm_intent(raw_text, snippet_triggers)

    print("[intent] no signal → text", file=sys.stderr)
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

    translate_step = f"5. Translate to {lang} if needed." if lang != "English" else ""

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are a voice transcription cleaner. "
            f"{app_hint}"
            f"Output language: {lang}. "
            "Steps: "
            "1. Call get_dictionary_terms to get the user's personal dictionary. "
            "2. Remove stutters, false starts, filler words (uh, um, like), repeated words. "
            "3. Apply dictionary corrections: replace any alias with the correct phrase. "
            "4. Fix punctuation and capitalisation. "
            f"{translate_step} "
            "Output ONLY the final cleaned text."
        ),
    )
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

    current = refined
    best    = refined
    best_score = 0
    lang = target_language.strip() or get_target_language()

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text": raw_text, "final_text": current, "app_name": app_name,
        }], verbose=False)
        if not results:
            break

        score  = results[0]["score"]
        reason = results[0]["reason"]
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
    return str(transcribe(audio_path)).strip()


# =========================================================
# Core pipeline
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
    print(f"[pipeline] transcribe {(time.perf_counter()-t0)*1000:.0f}ms  {raw_text[:60]!r}", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app = app_name.strip() or "unknown"

    # 2. Detect intent (regex first, LLM only if ambiguous)
    snippet_triggers = _load_snippet_triggers()
    intent      = detect_intent(raw_text, snippet_triggers)
    intent_type = intent.get("type", "text")

    # 3. Route
    final_text = raw_text
    try:
        if intent_type == "calendar":
            from gcalendar import get_schedule, extract_calendar_intent
            import getpass
            # LLM used here for accurate date/calendar extraction only
            cal = extract_calendar_intent(raw_text)
            final_text = get_schedule(
                date=cal.get("date") or "today",
                user_id=getpass.getuser(),
                calendar_filter=cal.get("calendar") or "all",
            )

        elif intent_type == "snippet":
            trigger = intent.get("trigger")
            try:
                from snippets import load_snippets, handle_dynamic_trigger, DYNAMIC_TRIGGERS
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
                    intent_type = "text"  # fallthrough
            except Exception:
                intent_type = "text"

        if intent_type == "text":
            # Agent calls get_dictionary_terms tool internally during refinement
            refined    = ai_refine_text(raw_text, effective_app, target_language)
            final_text = self_correct_text(raw_text, refined, effective_app, target_language)

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

    # ── transcribe ────────────────────────────────────────
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

    # ── calendar ──────────────────────────────────────────
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

    # ── set-language ──────────────────────────────────────
    elif command == "set-language":
        language = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = set_target_language(language)
        _exit_json({
            "ok": ok,
            "language": language,
            "error": f"unsupported: {language}" if not ok else None,
            "supported": SUPPORTED_LANGUAGES,
        }, 0 if ok else 1)

    # ── get-language ──────────────────────────────────────
    elif command == "get-language":
        _exit_json({"ok": True, "language": get_target_language(), "supported": SUPPORTED_LANGUAGES})

    # ── legacy: argv[2] is audio path ────────────────────
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