"""
agents/profile.py — User profile learning and context caching.

Runs once at startup in a background thread.
Saves a free-text description of the user to profile.json.
Provides get_user_context() which returns the cached string in 0ms.
"""
from __future__ import annotations

import io as _io
import sys
import threading

_real_stdout = sys.stdout
sys.stdout   = _io.StringIO()
try:
    from connectonion import Agent
finally:
    sys.stdout = _real_stdout

from storage import (
    load_profile, save_profile, load_history,
    load_dictionary, SUPPORTED_LANGUAGES,
)

# ── In-process cache ──────────────────────────────────────
_USER_CONTEXT_CACHE : str  = ""
_USER_CONTEXT_READY : bool = False
_PROFILE_UPDATE_LOCK = threading.Lock()
_PROFILE_UPDATED    : bool = False


# =========================================================
# Context building — disk read only, 0ms after first call
# =========================================================

def is_first_launch() -> bool:
    """True if the user has never completed onboarding."""
    return not load_profile().get("onboarding_done", False)


def complete_onboarding(
    career_area  : str        = "",
    usage_type   : list | None = None,
    writing_style: str        = "casual",
    language     : str        = "",
) -> None:
    """Save onboarding answers and mark setup as done.

    Only stores behavioural preferences — no PII.
    """
    from storage import SUPPORTED_LANGUAGES
    profile = load_profile()
    if career_area:
        profile["career_area"] = career_area.strip()
    profile["usage_type"]    = [u for u in (usage_type or []) if u]
    profile["writing_style"] = writing_style if writing_style in ("formal", "casual", "technical") else "casual"
    if language in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = language
    profile["onboarding_done"] = True
    save_profile(profile)
    invalidate_context_cache()


def _build_user_context() -> str:
    """Build a concise behavioural context string for all agents.

    No PII — only habits, usage patterns, and learned behaviour.
    Zero LLM calls — reads from disk only.
    """
    parts   = []
    profile = load_profile()
    learned = profile.get("learned", {})

    career = profile.get("career_area", "").strip()
    if career:
        parts.append(f"Professional area: {career}.")

    usage = profile.get("usage_type", [])
    if usage:
        parts.append(f"Uses Whispr mainly for: {', '.join(usage)}.")

    style = profile.get("writing_style", "").strip()
    if style:
        parts.append(f"Preferred writing style: {style}.")

    lang = profile.get("preferences", {}).get("target_language", "")
    if lang and lang != "English":
        parts.append(f"Output language: {lang}.")

    description = learned.get("description", "").strip()
    if description:
        parts.append(description)

    habits = learned.get("habits", [])
    if habits:
        parts.append(f"Recurring topics/phrases: {', '.join(habits[:6])}.")

    freq_apps = learned.get("frequent_apps", [])
    if freq_apps:
        parts.append(f"Frequently used apps: {', '.join(freq_apps[:5])}.")

    insertions = profile.get("text_insertions", [])
    if insertions:
        labels = [
            f"{i['label']} = {i['value']}"
            for i in insertions
            if i.get("label") and i.get("value")
        ]
        if labels:
            parts.append(f"Text insertion shortcuts: {'; '.join(labels)}.")

    # ── Recent speech — time-bounded, current session context ───────────────
    # Only include dictations from the last 2 hours so the refiner knows
    # what topic the user is currently working on, not month-old content.
    # Beyond 2h it's no longer "recent" — the learned habits cover long-term.
    import time as _time
    TWO_HOURS_MS = 2 * 60 * 60 * 1000
    now_ms       = int(_time.time() * 1000)

    _SKIP = {"i can help", "no google calendar", "could not fetch", "schedule for",
             "your calendar is clear", "no events found", "could not fetch"}
    recent_raw = []
    for item in reversed(load_history().get("items", [])[-50:]):
        # Skip if older than 2 hours
        ts = item.get("ts", 0)
        if (now_ms - ts) > TWO_HOURS_MS:
            break  # items are newest-first after reverse, so stop here
        raw = str(item.get("raw_text", "")).strip()
        if not raw:
            continue
        # CJK-aware minimum length
        import re as _re2
        _is_cjk = bool(_re2.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", raw))
        if (_is_cjk and len(raw) < 4) or (not _is_cjk and len(raw.split()) < 3):
            continue
        if any(s in raw.lower() for s in _SKIP):
            continue
        recent_raw.append(raw[:80])
        if len(recent_raw) >= 5:
            break

    if recent_raw:
        parts.append(f"Recent speech: {' | '.join(recent_raw)}.")

    return " ".join(parts)


def get_user_context() -> str:
    """Return cached user context — built once per process, 0ms after first call."""
    global _USER_CONTEXT_CACHE, _USER_CONTEXT_READY
    if not _USER_CONTEXT_READY:
        _USER_CONTEXT_CACHE = _build_user_context()
        _USER_CONTEXT_READY = True
    return _USER_CONTEXT_CACHE


def invalidate_context_cache() -> None:
    """Force context to be rebuilt on next call."""
    global _USER_CONTEXT_READY
    _USER_CONTEXT_READY = False


# =========================================================
# Profile learning agent — runs once at startup
# =========================================================

def update_profile_from_history() -> None:
    """Learn user profile from transcription history.

    Runs ONCE per process in a background thread.
    Makes one LLM call. Saves free-text description to profile.json.
    Next startup loads the updated profile instantly.
    """
    global _USER_CONTEXT_CACHE, _USER_CONTEXT_READY, _PROFILE_UPDATED
    with _PROFILE_UPDATE_LOCK:
        if _PROFILE_UPDATED:
            return
        _PROFILE_UPDATED = True
    try:
        items = load_history().get("items", [])[-50:]
        # Use raw_text so the LLM learns from what user said, not plugin output
        def _text_len(t: str) -> int:
            """CJK-aware length: count chars for CJK, words for Latin."""
            import re as _re
            if _re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", t):
                return len(t.strip())  # Chinese has no spaces — count chars
            return len(t.split())      # Latin — count words

        texts = [
            str(i.get("raw_text", "") or i.get("final_text", "")).strip()
            for i in items
            if _text_len(str(i.get("raw_text", "") or i.get("final_text", "")).strip()) >= 4
        ]
        texts = [t for t in texts if t]
        if len(texts) < 5:
            return

        sample = "\n".join(f"- {t[:120]}" for t in texts[-30:])
        prompt_input = (
            f"Transcription samples ({len(texts[-30:])} entries):\n{sample}\n\n"
            "Analyse these voice dictations and extract behavioural patterns only. "
            "Input may be multilingual (English, Chinese, or mixed) — analyse all languages. "
            "No names, no emails, no personal identifiers. Focus on:\n"
            "1. Professional domain and topics\n"
            "2. What they use voice dictation for\n"
            "3. Recurring technical terms or jargon\n"
            "4. Communication style\n"
            "Return ONLY valid JSON: "
            '{"description": "2-3 sentence behavioural summary", '
            '"habits": ["phrase or topic", ...], '
            '"frequent_apps": ["app name", ...]}'  
        )

        # Structured JSON extraction — fast model is sufficient
        agent = Agent(
            model="gpt-5.4",
            name="whispr_profile_learner",
            system_prompt=(
                "You are a usage-pattern analyser for a voice transcription app. "
                "Extract behavioural habits and work patterns only — no PII. "
                "Return ONLY valid JSON with keys: description, habits, frequent_apps. "
                "No markdown, no explanation, no preamble."
            ),
        )

        raw = str(agent.input(prompt_input)).strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        try:
            import json as _json
            parsed      = _json.loads(raw)
            description = str(parsed.get("description", "")).strip()
            habits      = [str(h).strip() for h in parsed.get("habits", []) if str(h).strip()][:10]
            freq_apps   = [str(a).strip() for a in parsed.get("frequent_apps", []) if str(a).strip()][:8]
        except Exception:
            description = raw[:400] if raw else ""
            habits, freq_apps = [], []

        if not description:
            return

        profile = load_profile()
        profile.setdefault("learned", {})
        profile["learned"]["description"]   = description
        profile["learned"]["habits"]        = habits
        profile["learned"]["frequent_apps"] = freq_apps
        profile["learned"]["last_updated"]  = len(load_history().get("items", []))
        save_profile(profile)

        # Rebuild cache with new description
        _USER_CONTEXT_CACHE = _build_user_context()
        _USER_CONTEXT_READY = True
        print(f"[profile] learned: {description[:80]}", file=sys.stderr)

    except Exception as e:
        print(f"[profile] update failed: {e}", file=sys.stderr)


def startup_init() -> None:
    """Call once at process start — pre-warms context and updates profile."""
    threading.Thread(target=get_user_context, daemon=True).start()
    threading.Thread(target=update_profile_from_history, daemon=True).start()