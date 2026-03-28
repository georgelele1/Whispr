from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from connectonion.address import load
from connectonion import Agent, host, transcribe

# Disable connectonion eval/log file generation in production
os.environ["CO_EVALS"] = "0"
os.environ["CO_LOGS"]  = "0"

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"

# ── Self-correction (OFF by default — too slow for hot path) ─
ENABLE_SELF_CORRECT  = False   # set True only for batch/offline use
SCORE_THRESHOLD      = 70
MAX_RETRIES          = 2       # reduced from 3

# ── Dictionary auto-update ────────────────────────────────
DICTIONARY_UPDATE_INTERVAL = 60 * 60 * 24

# ── Supported output languages ────────────────────────────
SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"

# ── Intent types ─────────────────────────────────────────
INTENT_TYPES = {"text", "calendar", "snippet"}

# Narrow calendar signal — used only as tier 3 ambiguity gate
# (tier 1 deny and tier 2 allow are checked first)
CALENDAR_KEYWORDS = re.compile(
    r"\b(schedule|calendar|events?|meeting|appointment|agenda|free|available|busy)\b",
    re.IGNORECASE,
)


# =========================================================
# Paths / storage
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


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    write_json(storage_path(filename), data)


# =========================================================
# Defaults
# =========================================================

def default_profile() -> Dict[str, Any]:
    return {
        "name": "", "email": "", "organization": "", "role": "",
        "preferences": {"target_language": DEFAULT_LANGUAGE},
    }


def load_profile() -> Dict[str, Any]:
    return load_store(PROFILE_FILE, default_profile())


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
    profile = load_profile()
    lang = profile.get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
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

def clean_agent_output(result: Any) -> str:
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
# Dictionary corrections  (pure regex — 0ms, no agent)
# =========================================================

def apply_dictionary_corrections(text: str) -> str:
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
# Dictionary auto-update helpers
# =========================================================

def should_update_dictionary() -> bool:
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (time.time() - data.get("last_update", 0)) > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    path = storage_path("dictionary_last_update.json")
    last_ts = 0.0
    if path.exists():
        try:
            last_ts = json.loads(path.read_text(encoding="utf-8")).get("last_update", 0.0)
        except Exception:
            pass
    return [
        item for item in load_history().get("items", [])
        if item.get("ts", 0) / 1000 > last_ts
    ]


def get_optimal_sample_size(items: List[Any]) -> int:
    total = len(items)
    if total == 0:  return 0
    if total < 20:  return total
    if total < 100: return max(20, total // 3)
    return max(40, total // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ]
    return deduplicate_items(texts)


# =========================================================
# Intent detection — 3-tier hybrid system
#
# Tier 1 (0ms):  Hard DENY regex — phrases that contain calendar
#                words but are clearly NOT a fetch request.
#                e.g. "my calendar is full", "I don't have time"
#
# Tier 2 (0ms):  Hard ALLOW regex — phrases that unambiguously
#                request a calendar fetch or snippet expansion.
#                e.g. "what's my schedule", "show me my calendar"
#
# Tier 3 (~1.5s): LLM — only fires when tier 1 and 2 both miss,
#                meaning the text has calendar words but context
#                is genuinely ambiguous.
#
# This means:
#   "my calendar is full"          → Tier 1 DENY → text (0ms)
#   "check my schedule for today"  → Tier 2 ALLOW → calendar (0ms)
#   "let me see if I'm free Friday"→ Tier 3 LLM → calendar (~1.5s)
# =========================================================

# Tier 1: These phrases look like calendar words but are NOT requests
_CALENDAR_DENY = re.compile(
    r"\b("
    r"(my |the )?(calendar|schedule) is (full|busy|packed|crazy|hectic|clear|empty|free)"
    r"|don.?t have time"
    r"|no time for"
    r"|too busy"
    r"|out of time"
    r"|running late"
    r"|already (booked|scheduled|taken|busy)"
    r"|cancel(led)? (the |my )?(meeting|appointment|event)"
    r"|reschedule"
    r"|missed (the |my )?(meeting|appointment)"
    r")\b",
    re.IGNORECASE,
)

# Tier 2: These phrases unambiguously request a calendar fetch
_CALENDAR_ALLOW = re.compile(
    r"\b("
    r"(show|check|see|get|what.?s|give me|tell me|look at|open|pull up|read)"
    r"\s+(me\s+)?(my\s+)?(schedule|calendar|events?|agenda|appointments?|meetings?)"
    r"|what.?s\s+(on|happening)\s+(today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday)"
    r"|am\s+i\s+(free|available|busy)\s+(today|tomorrow|on|this|next)"
    r"|do\s+i\s+have\s+(anything|something|a meeting|an appointment)"
    r"|what\s+time\s+is\s+my"
    r"|when\s+is\s+my\s+next"
    r")\b",
    re.IGNORECASE,
)

# Snippet: unambiguous request with action verb + known trigger
_SNIPPET_ALLOW = re.compile(
    r"^\s*(give me|insert|paste|use|add|put|show me|open|pull up)\b",
    re.IGNORECASE,
)


def _load_snippet_triggers() -> List[str]:
    try:
        from snippets import load_snippets
        data = load_snippets()
        return [
            item["trigger"]
            for item in data.get("snippets", [])
            if item.get("enabled", True) and str(item.get("trigger", "")).strip()
        ]
    except Exception:
        return []


def _next_weekday_date(day_name: str) -> str:
    """Convert day name like wednesday to next YYYY-MM-DD date."""
    from datetime import datetime as _dt, timedelta as _td
    days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    today = _dt.now()
    days_ahead = (days.index(day_name.lower()) - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return (today + _td(days=days_ahead)).strftime("%Y-%m-%d")


def _extract_date_cal(text_lower: str) -> tuple:
    """Extract date and calendar name. Converts day names to YYYY-MM-DD."""
    date = "today"
    if "tomorrow" in text_lower:
        date = "tomorrow"
    else:
        day_match = re.search(
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            text_lower
        )
        if day_match:
            date = _next_weekday_date(day_match.group(0))

    cal = "all"
    for word in ["work","personal","family","school","uni","unsw","university","study","class","lecture"]:
        if word in text_lower:
            cal = word
            break

    return date, cal


def _llm_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    """Tier 3: LLM intent for genuinely ambiguous cases (~1.5s)."""
    triggers_hint = (
        f"Known snippet triggers: {json.dumps(snippet_triggers)}. "
        if snippet_triggers else ""
    )
    agent = Agent(
        model="gpt-5",
        name="whispr_intent_detector",
        system_prompt=(
            "Classify voice input as 'text', 'calendar', or 'snippet'. "
            "'calendar' = user REQUESTS to SEE/CHECK/GET their schedule or events. "
            "NOT calendar if user is just mentioning being busy or full schedule. "
            "'snippet' = user requests a known shortcut by name. "
            "'text' = normal dictation. "
            f"{triggers_hint}"
            'Reply ONLY with JSON: {"type":"...","trigger":null,"date":"today|tomorrow|day","calendar":"name|all"}'
        ),
    )
    try:
        result = json.loads(str(agent.input(raw_text)).strip())
        if result.get("type") not in {"text", "calendar", "snippet"}:
            result["type"] = "text"
        return result
    except Exception:
        return {"type": "text", "trigger": None, "date": None, "calendar": None}


def detect_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    """3-tier intent detection: deny regex → allow regex → LLM fallback."""
    text_lower = raw_text.lower()

    # ── Tier 1: Hard deny (0ms) ───────────────────────────
    # Calendar words present but clearly NOT a fetch request
    if _CALENDAR_DENY.search(raw_text):
        print("[intent] tier1 DENY → text", file=sys.stderr)
        return {"type": "text", "trigger": None, "date": None, "calendar": None}

    # ── Snippet check (0ms) ───────────────────────────────
    if _SNIPPET_ALLOW.search(raw_text):
        for trigger in snippet_triggers:
            if trigger.lower() in text_lower:
                print(f"[intent] snippet → {trigger}", file=sys.stderr)
                return {"type": "snippet", "trigger": trigger, "date": None, "calendar": None}

    # ── Tier 2: Hard allow (0ms) ──────────────────────────
    # Unambiguous calendar fetch request
    if _CALENDAR_ALLOW.search(raw_text):
        date, cal = _extract_date_cal(text_lower)
        print(f"[intent] tier2 ALLOW → calendar date={date} cal={cal}", file=sys.stderr)
        return {"type": "calendar", "trigger": None, "date": date, "calendar": cal}

    # ── Tier 3: LLM fallback (~1.5s) ─────────────────────
    # Only fires if calendar keywords present but context ambiguous
    if CALENDAR_KEYWORDS.search(raw_text):
        print("[intent] tier3 LLM → ambiguous", file=sys.stderr)
        return _llm_intent(raw_text, snippet_triggers)

    # No calendar or snippet signal at all → normal text (0ms)
    print("[intent] no signal → text", file=sys.stderr)
    return {"type": "text", "trigger": None, "date": None, "calendar": None}


# =========================================================
# AI refine  (single agent call — the ONLY LLM call for normal text)
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

    # Skip refine entirely if language is English and text is already clean
    # (short texts with no obvious disfluencies)
    if (lang == "English"
            and len(text.split()) < 5
            and not re.search(r"\b(uh|um|er|like|so so|I I|the the)\b", text, re.IGNORECASE)):
        return apply_dictionary_corrections(text)

    app_hint = (
        f"Active app: {app_name.strip()}."
        if app_name.strip() and app_name.strip() != "unknown"
        else ""
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are a voice transcription cleaner. "
            f"{app_hint} "
            f"Output language: {lang}.\n"
            "Remove stutters, false starts, filler words (uh, um, like), "
            "repeated words, and fix punctuation and capitalisation. "
            f"{'Translate to ' + lang + ' if needed. ' if lang != 'English' else ''}"
            "Output ONLY the cleaned text — nothing else."
        ),
    )

    return clean_agent_output(agent.input(text))


# =========================================================
# Self-correction  (DISABLED in hot path — use offline only)
# =========================================================

def self_correct_text(
    raw_text: str,
    initial_refined: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    """Only runs when ENABLE_SELF_CORRECT=True — too slow for real-time use."""
    if not ENABLE_SELF_CORRECT:
        return initial_refined

    try:
        from Eval_run import run_refinement_eval
    except ImportError:
        return initial_refined

    current    = initial_refined
    best_text  = initial_refined
    best_score = 0
    lang       = target_language.strip() or get_target_language()

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text": raw_text, "final_text": current, "app_name": app_name,
        }], verbose=False)

        if not results:
            break

        score  = results[0]["score"]
        reason = results[0]["reason"]

        if score > best_score:
            best_score = score
            best_text  = current

        print(f"[self-correct] attempt {attempt + 1}  score={score}/100", file=sys.stderr)

        if score >= SCORE_THRESHOLD:
            break

        agent = Agent(
            model="gpt-5",
            name="whispr_self_corrector",
            system_prompt=(
                f"Fix the issues in this text. Output ONLY corrected {lang} text."
            ),
        )
        current = clean_agent_output(agent.input(
            f"Raw: {raw_text}\nPrevious: {current}\nFeedback: {reason}"
        ))

    return best_text


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    return str(transcribe(audio_path)).strip()


# =========================================================
# Core pipeline  — optimised for minimum latency
#
# Agent calls per transcription:
#   Normal text:    1  (ai_refine only)
#   Calendar:       0  (regex intent + direct API call)
#   Snippet:        0  (regex intent + local lookup)
#
# Expected times:
#   Normal text:    ~4s  (was ~28s)
#   Calendar:       ~8s  (API call dominates)
#   Snippet:        ~0s  (local)
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:

    audio_path = str(Path(audio_path).expanduser())
    if not Path(audio_path).exists():
        return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}

    # ── Step 1: Transcribe ────────────────────────────────
    t0 = time.perf_counter()
    raw_text = transcribe_audio(audio_path)
    print(f"[pipeline] transcribe: {(time.perf_counter()-t0)*1000:.0f}ms  raw={raw_text[:60]!r}", file=sys.stderr)

    if not raw_text.strip():
        return {"ok": False, "error": "transcription returned empty", "ts": now_ms()}

    effective_app = app_name.strip() or "unknown"

    # ── Step 2: Intent detection ──────────────────────────
    snippet_triggers = _load_snippet_triggers()
    intent = detect_intent(raw_text, snippet_triggers)
    intent_type = intent.get("type", "text")

    # ── Step 3: Route on intent ───────────────────────────
    final_text = raw_text

    try:
        if intent_type == "calendar":
            # Use LLM to extract date properly — handles "next Wednesday",
            # "this Friday", "in 2 days" etc. much better than regex.
            # The intent detection (tier1/tier2) is still regex — only the
            # date/calendar extraction uses the LLM here.
            from gcalendar import get_schedule, extract_calendar_intent
            import getpass
            t1 = time.perf_counter()
            cal_intent = extract_calendar_intent(raw_text)
            final_text = get_schedule(
                date=cal_intent.get("date") or "today",
                user_id=getpass.getuser(),
                calendar_filter=cal_intent.get("calendar") or "all",
            )
            print(f"[pipeline] calendar fetch: {(time.perf_counter()-t1)*1000:.0f}ms", file=sys.stderr)

        elif intent_type == "snippet":
            # Zero LLM calls — local dictionary lookup
            trigger = intent.get("trigger")
            try:
                from snippets import load_snippets, handle_dynamic_trigger, DYNAMIC_TRIGGERS
                data     = load_snippets()
                snippets = {
                    item["trigger"]: item["expansion"]
                    for item in data.get("snippets", [])
                    if item.get("enabled", True)
                }
                if trigger and trigger in snippets:
                    final_text = (
                        handle_dynamic_trigger(trigger, raw_text)
                        if trigger.lower() in DYNAMIC_TRIGGERS
                        else snippets[trigger]
                    )
                else:
                    # Trigger not found — fall through to normal refine
                    intent_type = "text"
            except Exception:
                intent_type = "text"

        if intent_type == "text":
            # Single LLM call — refine only
            t1 = time.perf_counter()
            refined    = ai_refine_text(raw_text, effective_app, target_language)
            corrected  = self_correct_text(raw_text, refined, effective_app, target_language)
            final_text = apply_dictionary_corrections(corrected)
            print(f"[pipeline] refine: {(time.perf_counter()-t1)*1000:.0f}ms", file=sys.stderr)

    except Exception as exc:
        print(f"[pipeline] error — fallback to raw: {exc}", file=sys.stderr)
        final_text = apply_dictionary_corrections(raw_text)

    print(f"[pipeline] total: {(time.perf_counter()-t0)*1000:.0f}ms", file=sys.stderr)

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
# Tool functions
# =========================================================

def create_or_update_profile(
    name: str = "", email: str = "",
    organization: str = "", role: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    profile = load_profile()
    for key, value in {
        "name": name, "email": email,
        "organization": organization, "role": role,
    }.items():
        if str(value).strip():
            profile[key] = str(value).strip()
    if target_language.strip() in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = target_language.strip()
    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def transcribe_and_enhance(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        app_name=app_name,
        target_language=target_language,
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

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":

        if len(sys.argv) < 3:
            print(json.dumps({"output": ""}, ensure_ascii=False))
            sys.exit(1)

        command = sys.argv[2]

        if command == "transcribe":
            audio_path      = sys.argv[3] if len(sys.argv) > 3 else ""
            app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
            target_language = sys.argv[5] if len(sys.argv) > 5 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)
            print(f"TARGET LANGUAGE: {target_language or get_target_language()}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        elif command == "calendar":
            import getpass
            text    = sys.argv[3] if len(sys.argv) > 3 else "today"
            user_id = sys.argv[4] if len(sys.argv) > 4 else getpass.getuser()
            try:
                from gcalendar import get_schedule, extract_calendar_intent
                intent   = extract_calendar_intent(text)
                schedule = get_schedule(
                    date=intent.get("date", "today"),
                    user_id=user_id,
                    calendar_filter=intent.get("calendar", "all"),
                )
                print(json.dumps({"output": schedule}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        elif command == "set-language":
            language = sys.argv[3] if len(sys.argv) > 3 else ""
            ok = set_target_language(language)
            print(json.dumps({
                "ok": ok, "language": language,
                "error": f"unsupported: {language}" if not ok else None,
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0 if ok else 1)

        elif command == "get-language":
            print(json.dumps({
                "ok": True,
                "language": get_target_language(),
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0)

        else:
            # Legacy: direct audio path as argv[2]
            audio_path      = sys.argv[2]
            app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
            target_language = sys.argv[4] if len(sys.argv) > 4 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

    else:
        addr = load(CO_DIR)
        host(
            create_agent,
            relay_url=None,
            whitelist=[addr["address"]],
            blacklist=[],
        )