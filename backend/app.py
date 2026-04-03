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
import threading as _threading
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
        # Auto-learned — updated by profile agent on startup
        "learned": {
            "description":  "",  # free-text profile summary generated from history
            "last_updated": 0,   # history item count when last updated
        }
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
# Agentic router
#
# One agent with all tools decides what to call.
# No hardcoded regex routing — agent picks the right tool.
# Only a fast deny regex kept to block obvious false positives.
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


# ── Tools the router agent can call ─────────────────────

def tool_get_calendar(date: str = "today", calendar_filter: str = "all") -> str:
    """Fetch Google Calendar schedule for a date.
    Use when user wants to SEE their events or schedule.
    date: today / tomorrow / YYYY-MM-DD
    """
    try:
        from gcalendar import get_schedule, load_current_email
        email = load_current_email()
        if not email:
            return "No Google Calendar connected."
        return get_schedule(date=date, user_id=email, calendar_filter=calendar_filter)
    except Exception as e:
        return f"Calendar error: {e}"


def tool_search_calendar(query: str, calendar_filter: str = "all") -> str:
    """Search Google Calendar for a specific event by keyword.
    Use when user wants to FIND a specific event (exam, meeting, deadline).
    """
    try:
        from gcalendar import search_events, load_current_email
        email = load_current_email()
        if not email:
            return "No Google Calendar connected."
        return search_events(query=query, user_id=email, calendar_filter=calendar_filter)
    except Exception as e:
        return f"Search error: {e}"


def tool_expand_snippet(trigger: str) -> str:
    """Expand a user-defined voice shortcut by trigger word.
    Use when user explicitly requests a snippet by name.
    """
    try:
        from snippets import load_snippets, DYNAMIC_TRIGGERS
        snippets = {
            item["trigger"].lower(): item["expansion"]
            for item in load_snippets().get("snippets", [])
            if item.get("enabled", True)
        }
        t = trigger.lower().strip()
        if t in DYNAMIC_TRIGGERS:
            return tool_get_calendar()
        return snippets.get(t, f"Snippet not found: {trigger}")
    except Exception as e:
        return f"Snippet error: {e}"


def tool_lookup_knowledge(query: str) -> str:
    """Look up knowledge across ALL domains and industries.
    Call this whenever the user asks to explain, define, describe, or give
    formulas/steps/examples for ANY topic — AI/ML, software, science, math,
    medicine, finance, law, networking, physics, chemistry, engineering etc.
    Also call for follow-up questions about something previously explained
    (e.g. 'what does each character mean', 'give me an example', 'explain more').
    query: the full question or topic.
    """
    return knowledge_lookup(query)


def tool_refine_text(text: str) -> str:
    """Clean and format voice transcription — DEFAULT tool.
    Use for normal dictation: removes fillers, fixes punctuation, formats lists.
    Always use this when no other tool is more appropriate.
    """
    return ai_refine_text(text, "", get_target_language())


# ── Router agent ─────────────────────────────────────────

# =========================================================
# Session memory — conversational context within one process
# =========================================================

_SESSION_MEMORY : list = []
_SESSION_MAX    : int  = 6


def session_remember(user_text: str, assistant_text: str) -> None:
    global _SESSION_MEMORY
    _SESSION_MEMORY.append({"role": "user",      "content": user_text})
    _SESSION_MEMORY.append({"role": "assistant",  "content": assistant_text})
    _SESSION_MEMORY = _SESSION_MEMORY[-_SESSION_MAX:]


def session_context() -> str:
    if not _SESSION_MEMORY:
        return ""
    lines = [
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
        for m in _SESSION_MEMORY
    ]
    return "\n".join(lines)


def is_followup(text: str) -> bool:
    if not _SESSION_MEMORY:
        return False
    return bool(re.match(
        r"(what (does|is|are)|explain|tell me more|and |also |now "
        r"|each (character|letter|symbol|variable|term|part|one)"
        r"|the (formula|equation|rule|law|definition|first|second|third)"
        r"|what about|how about|give me (an )?example"
        r"|can you explain|break (it|them|this) down"
        r"|what does .{1,20} (mean|stand for|represent))",
        text.strip(), re.IGNORECASE
    ))


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

    if (lang == "English"
            and len(text.split()) < 5
            and not re.search(r"\b(uh|um|er|so so|I I|the the)\b", text, re.IGNORECASE)):
        return apply_dictionary_corrections(text)

    app_hint  = f"Active app: {app_name.strip()}. " if app_name.strip() and app_name.strip() != "unknown" else ""
    user_ctx  = get_user_context()
    ctx_hint  = f"User context: {user_ctx} " if user_ctx else ""
    trans     = f"Translate to {lang}." if lang != "English" else ""

    has_dict  = bool(load_dictionary().get("terms"))
    dict_step = "1. Call get_dictionary_terms and apply corrections. " if has_dict else ""
    offset    = 2 if has_dict else 1

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are a personal voice transcription assistant. "
            f"{ctx_hint}{app_hint}"
            f"Output language: {lang}. "
            f"{dict_step}"
            f"{offset}. Fix phonetic mishearings using context. "
            f"{offset+1}. Remove stutters, false starts, fillers (uh, um, like, so, basically), interjections (ah, oh, hmm). "
            f"{offset+2}. Detect numbered list (point one/two, first/second) → format as numbered list. Otherwise prose. "
            f"{offset+3}. Fix punctuation and capitalisation. "
            f"{trans} Output ONLY the final text."
        ),
    )
    if has_dict:
        register_tool(agent, get_dictionary_terms)
    return _clean(agent.input(text))


def self_correct_text(raw_text: str, refined: str, app_name: str = "", target_language: str = "") -> str:
    return refined  # disabled — too slow for real-time


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    raw = str(transcribe(audio_path)).strip()
    raw = re.sub(
        r"^(sure,?\s+)?(here\s+is\s+the\s+transcription|transcription)[^:]*:\s*",
        "", raw, flags=re.IGNORECASE | re.DOTALL
    ).strip()
    return raw


def quick_clean(text: str) -> str:
    """Fast 0ms pre-clean before intent detection.
    Removes fillers and stutters using regex — no LLM needed.
    Makes intent detection more accurate on clean text.
    """
    # Apply dictionary corrections first (alias → correct term)
    text = apply_dictionary_corrections(text)

    # Remove filler words
    fillers = re.compile(
        r"\b(uh+|um+|er+|hmm+|ah+|oh+|like|so|basically|actually|"
        r"you know|kind of|sort of|right|okay so|well)\b[,]?\s*",
        re.IGNORECASE
    )
    text = fillers.sub(" ", text)

    # Remove stutters (repeated words: "the the", "I I")
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)

    # Collapse extra spaces
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text


def route_with_agent(raw_text: str, snippet_triggers: List[str]) -> str:
    """Single agent with full context — reads everything and responds directly.

    The agent has:
    - Full user profile + learned description
    - Session memory (recent conversation)
    - Recent transcription history
    - All tools available

    It decides what to do based on the WHOLE context, not just keywords.
    For knowledge requests it answers directly using its own LLM capability.
    For calendar/snippets it calls the relevant tool.
    For plain dictation it cleans the text.
    """
    user_context  = get_user_context()
    session       = session_context()
    history_items = load_history().get("items", [])[-5:]
    recent_texts  = [str(i.get("final_text",""))[:100] for i in history_items
                     if str(i.get("final_text","")).strip()]

    # Build full context block — agent reads ALL of this
    context_block = []
    if user_context:
        context_block.append(f"USER PROFILE:\n{user_context}")
    if recent_texts:
        context_block.append(f"RECENT HISTORY:\n" + "\n".join(f"- {t}" for t in recent_texts))
    if session:
        context_block.append(f"CURRENT CONVERSATION:\n{session}")
    if snippet_triggers:
        context_block.append(f"USER SHORTCUTS: {', '.join(snippet_triggers)}")

    full_context = "\n\n".join(context_block)

    agent = Agent(
        model="gpt-5",
        name="whispr_router",
        system_prompt=(
            "You are a voice assistant. Decide how to handle this input.\n"
            f"Context about the user: {full_context[:300]}\n\n"
            "DECISION RULES — apply in order:\n"
            "1. Does the input ask for FACTS, KNOWLEDGE, FORMULAS, LAWS, DEFINITIONS, "
            "SCIENCE, MATH, HISTORY, or EXPLANATIONS? "
            "→ Answer it yourself RIGHT NOW. Write the actual answer. "
            "Example: 'give me Newton second law' → write 'Newton\'s Second Law: F = ma\n"
            "F = Force (Newtons)\nm = mass (kg)\na = acceleration (m/s²)'\n"
            "Example: 'explain redox' → write the actual chemistry explanation.\n"
            "DO NOT call any tool for knowledge. Just answer.\n\n"
            "2. Does it reference something from a previous answer "
            "(e.g. 'each character', 'an example', 'what does F mean')? "
            f"→ Use this conversation history: {session[:400] if session else 'none'}\n"
            "Answer directly. No tool.\n\n"
            "3. Does it ask to CHECK a calendar or schedule? "
            "→ Call tool_get_calendar(date).\n\n"
            "4. Does it ask to FIND a specific event? "
            "→ Call tool_search_calendar(query).\n\n"
            "5. Does it name one of these shortcuts: "
            f"{json.dumps(snippet_triggers)}? "
            "→ Call tool_expand_snippet(trigger).\n\n"
            "6. Everything else (plain speech, dictation): "
            "→ Return the input text unchanged.\n\n"
            "OUTPUT: Only the answer or result. No explanation of what you did."
        ),
    )

    # Do NOT register tool_refine_text — agent answers knowledge directly
    # and returns a signal for plain dictation
    for fn in (tool_get_calendar, tool_search_calendar, tool_expand_snippet):
        register_tool(agent, fn)

    result = _clean(agent.input(raw_text))

    # If agent returned the input largely unchanged → plain dictation
    # Text is already pre-cleaned — just fix punctuation/formatting
    if not result or result.lower().strip(".") == raw_text.lower().strip("."):
        result = ai_refine_text(raw_text)  # app_name not available here — passed via pipeline
        result = apply_inline_snippets(result)

    if result:
        session_remember(raw_text, result)
    return result if result else raw_text


def detect_intent(raw_text: str, snippet_triggers: List[str]) -> Dict[str, Any]:
    """Kept for backward compatibility with refine CLI test command.
    Returns a basic intent dict — actual routing now done by route_with_agent().
    """
    # Only keep the fast deny for obvious false positives
    if _CALENDAR_DENY.search(raw_text):
        return {"type": "text", "trigger": None, "date": None, "calendar": None}
    # Delegate everything else to the router agent
    return {"type": "agent", "trigger": None, "date": None, "calendar": None}


# =========================================================
# Inline snippet replacement
# Replaces trigger words found anywhere in refined text with their expansion.
# e.g. "send the zoom link to John" → "send https://zoom.us/j/123 to John"
# Only static snippets — dynamic (calendar) are skipped here.
# =========================================================

def apply_inline_snippets(text: str) -> str:
    """Replace snippet triggers inline using regex — 0ms, no LLM.
    Expansion is already formatted (e.g. "Zoom link (https://...)").
    """
    if not text.strip():
        return text
    try:
        from snippets import load_snippets
        dynamic = {"calendar"}
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
            result = re.sub(
                rf"\b{re.escape(trigger)}\b",
                expansion,
                result,
                flags=re.IGNORECASE,
            )
        print(f"[snippets] inline applied {len(snippets)} triggers", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[snippets] inline error: {e}", file=sys.stderr)
        return text


# =========================================================
# Profile learning + user context cache
# Built once at startup — 0ms on every transcription call
# =========================================================

_USER_CONTEXT_CACHE : str  = ""
_USER_CONTEXT_READY : bool = False
_PROFILE_UPDATE_LOCK = _threading.Lock()
_PROFILE_UPDATED    : bool = False


def _build_user_context() -> str:
    """Read profile.json and recent history — no LLM, pure disk read."""
    parts   = []
    profile = load_profile()
    learned = profile.get("learned", {})

    name = profile.get("name", "").strip()
    role = profile.get("role", "").strip()
    org  = profile.get("organization", "").strip()
    if name:           parts.append(f"User: {name}.")
    if role and org:   parts.append(f"Role: {role} at {org}.")
    elif role or org:  parts.append(f"Role: {role or org}.")

    description = learned.get("description", "").strip()
    if description:    parts.append(description)

    recent = [
        str(i.get("final_text", ""))[:80]
        for i in load_history().get("items", [])[-5:]
        if str(i.get("final_text", "")).strip()
    ]
    if recent:         parts.append(f"Recent: {' | '.join(recent)}.")

    return " ".join(parts)


def get_user_context() -> str:
    """Return cached user context — built once per process, 0ms after first call."""
    global _USER_CONTEXT_CACHE, _USER_CONTEXT_READY
    if not _USER_CONTEXT_READY:
        _USER_CONTEXT_CACHE = _build_user_context()
        _USER_CONTEXT_READY = True
    return _USER_CONTEXT_CACHE


def update_profile_from_history() -> None:
    """Profile learning agent — runs ONCE at startup in background thread.
    One LLM call. Saves a free-text description to profile.json.
    """
    global _USER_CONTEXT_CACHE, _USER_CONTEXT_READY, _PROFILE_UPDATED
    with _PROFILE_UPDATE_LOCK:
        if _PROFILE_UPDATED:
            return
        _PROFILE_UPDATED = True
    try:
        items = load_history().get("items", [])[-50:]
        texts = [str(i.get("final_text", "")).strip() for i in items
                 if str(i.get("final_text", "")).strip()]
        if len(texts) < 5:
            return

        sample       = "\n".join(f"- {t[:100]}" for t in texts[-30:])
        prompt_input = (
            f"Recent transcriptions (last 30):\n{sample}\n\n"
            "Write a 2-4 sentence profile of this user based on their transcriptions. "
            "Be specific — use actual names, project codes, tools from the text. "
            "Plain text only."
        )

        agent = Agent(
            model="gpt-5",
            name="whispr_profile_learner",
            system_prompt=(
                "You are a user profiling agent. "
                "Analyse transcriptions and write a concise personal profile. "
                "Plain text, 2-4 sentences, no bullet points."
            ),
        )

        description = str(agent.input(prompt_input)).strip()
        if not description:
            return

        profile = load_profile()
        profile.setdefault("learned", {})
        profile["learned"]["description"]  = description
        profile["learned"]["last_updated"] = len(load_history().get("items", []))
        save_profile(profile)

        _USER_CONTEXT_CACHE = _build_user_context()
        _USER_CONTEXT_READY = True
        print(f"[profile] learned: {description[:80]}", file=sys.stderr)

    except Exception as e:
        print(f"[profile] update failed: {e}", file=sys.stderr)


# =========================================================
# Knowledge lookup
# User asks for facts, formulas, definitions — agent looks them up
# =========================================================

def knowledge_lookup(text: str, app_name: str = "") -> str:
    """Look up facts, formulas, definitions — with session memory for follow-ups.

    Turn 1: "Newton second law"  → "F = ma"
    Turn 2: "what does each character mean" → uses memory → "F=Force, m=mass, a=acceleration"
    Turn 3: "give me an example" → uses memory → "A 10kg object..."
    """
    user_context = get_user_context()
    context_hint = f"User context: {user_context} " if user_context else ""
    app_hint     = f"Active app: {app_name}. " if app_name and app_name != "unknown" else ""
    session      = session_context()
    session_hint = f"\n\nConversation so far:\n{session}" if session else ""

    agent = Agent(
        model="gpt-5",
        name="whispr_knowledge_agent",
        system_prompt=(
            "You are a universal knowledge assistant embedded in a voice transcription app. "
            "You cover ALL domains: AI/ML, software engineering, physics, chemistry, "
            "mathematics, medicine, finance, law, biology, business, history, and more. "
            f"{context_hint}"
            f"{app_hint}"
            "Rules: "
            "1. Follow-ups ('the formula', 'each character', 'an example', 'explain more') "
            "   → resolve from conversation history. "
            "2. Formulas → proper notation + variable meanings. "
            "3. Steps/processes → numbered list. "
            "4. Definitions → concise and domain-specific. "
            "5. Tailor answer to active app context if relevant "
            "(e.g. if app is Xcode → favour code examples; Mail → prose explanation). "
            "6. Output ONLY the answer — no preamble ('Here is', 'Sure'). "
            f"{session_hint}"
        ),
    )
    try:
        result = _clean(agent.input(text))
        if result:
            session_remember(text, result)
        return result if result else text
    except Exception as e:
        print(f"[knowledge] lookup failed: {e}", file=sys.stderr)
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
        # 2. Pre-clean: fast 0ms regex — dict corrections + fillers removed
        clean_text = quick_clean(raw_text)
        print(f"[pipeline] pre-clean: {clean_text[:60]!r}", file=sys.stderr)

        snippet_triggers = _load_snippet_triggers()

        # 3. Knowledge fast-path — regex detects knowledge requests reliably
        #    Bypasses router agent to avoid misclassification
        _KNOWLEDGE_RE = re.compile(
            r"\b(give me|show me|what is|what are|explain|define|tell me|"
            r"write|list|describe|how does|how do|formula|equation|law|"
            r"definition|theory|concept|rule|steps|example of|meaning of)\b",
            re.IGNORECASE,
        )
        if _KNOWLEDGE_RE.search(clean_text) or is_followup(clean_text):
            print(f"[pipeline] knowledge fast-path", file=sys.stderr)
            final_text = knowledge_lookup(clean_text, app_name=effective_app)
            session_remember(raw_text, final_text)

        # 4. Calendar/snippet fast-path using regex
        elif _CALENDAR_ALLOW.search(clean_text):
            print(f"[pipeline] calendar fast-path", file=sys.stderr)
            from gcalendar import get_schedule, extract_calendar_intent
            import getpass
            cal = extract_calendar_intent(clean_text)
            final_text = get_schedule(
                date=cal.get("date") or "today",
                user_id=getpass.getuser(),
                calendar_filter=cal.get("calendar") or "all",
            )

        elif _CALENDAR_SEARCH.search(clean_text):
            print(f"[pipeline] search fast-path", file=sys.stderr)
            from gcalendar import search_events, extract_search_intent
            import getpass
            si = extract_search_intent(clean_text)
            final_text = search_events(
                query=si.get("query") or clean_text,
                user_id=getpass.getuser(),
            )

        elif _SNIPPET_EXPLICIT.search(clean_text) and any(t in clean_text.lower() for t in snippet_triggers):
            print(f"[pipeline] snippet fast-path", file=sys.stderr)
            final_text = route_with_agent(clean_text, snippet_triggers)
            session_remember(raw_text, final_text)

        # 5. Plain dictation — refine the original raw text
        else:
            print(f"[pipeline] refine", file=sys.stderr)
            refined    = ai_refine_text(raw_text, effective_app, target_language)
            final_text = apply_inline_snippets(refined)
            session_remember(raw_text, final_text)
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


# ── Startup: build context cache + update profile once in background ──
def _startup_init() -> None:
    """Called once when module is imported.
    Builds user context cache and runs profile update in background.
    No latency impact — both run in daemon threads.
    """
    # Pre-build context cache (fast, disk read only)
    _threading.Thread(target=get_user_context, daemon=True).start()
    # Update learned profile once (one LLM call, background)
    _threading.Thread(target=update_profile_from_history, daemon=True).start()

_startup_init()


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
            elif intent_type == "knowledge":
                output = knowledge_lookup(raw_text)
            else:
                refined  = ai_refine_text(raw_text, app_name, target_language)
                corrected = self_correct_text(raw_text, refined, app_name, target_language)
                output    = apply_inline_snippets(corrected)

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

    elif command == "get-history":
        data  = load_history()
        items = list(reversed(data.get("items", [])))  # newest first
        _exit_json({"items": items[:100]})  # cap at 100

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