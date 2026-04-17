"""
agents/profile.py — User profile context injection and background learning.

Pipeline roles:
  inject_profile()            → after_user_input on refiner + knowledge subagents
  update_profile_background() → on_complete on refiner + knowledge subagents
                                debounced every 50, daemon thread
"""
from __future__ import annotations

import json
import threading

from connectonion import Agent

from storage import load_profile, save_profile, load_history, SUPPORTED_LANGUAGES

_CONTEXT_CACHE : str  = ""
_CONTEXT_READY : bool = False
_CACHE_LOCK           = threading.Lock()

_LEARN_COUNTER = 0
_LEARN_EVERY   = 50
_LEARN_RUNNING = False
_LEARN_LOCK    = threading.Lock()


def _build_context() -> str:
    parts   = []
    profile = load_profile()
    learned = profile.get("learned", {})

    career = profile.get("career_area", "").strip()
    if career:
        parts.append(f"Professional area: {career}.")

    usage = profile.get("usage_type", [])
    if usage:
        parts.append(f"Uses Whispr for: {', '.join(usage)}.")

    style = profile.get("writing_style", "").strip()
    if style:
        parts.append(f"Preferred writing style: {style}.")

    description = learned.get("description", "").strip()
    if description:
        parts.append(description)

    habits = learned.get("habits", [])
    if habits:
        parts.append(f"Recurring topics: {', '.join(habits[:6])}.")

    freq_apps = learned.get("frequent_apps", [])
    if freq_apps:
        parts.append(f"Frequent apps: {', '.join(freq_apps[:5])}.")

    return " ".join(parts)


def get_user_context() -> str:
    global _CONTEXT_CACHE, _CONTEXT_READY
    with _CACHE_LOCK:
        if not _CONTEXT_READY:
            _CONTEXT_CACHE = _build_context()
            _CONTEXT_READY = True
    return _CONTEXT_CACHE


def invalidate_context_cache() -> None:
    global _CONTEXT_READY
    with _CACHE_LOCK:
        _CONTEXT_READY = False


def is_first_launch() -> bool:
    return not load_profile().get("onboarding_done", False)


def complete_onboarding(
    career_area  : str        = "",
    usage_type   : list | None = None,
    writing_style: str        = "casual",
    language     : str        = "",
) -> None:
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


# =========================================================
# Event handlers
# =========================================================

def inject_profile(agent) -> None:
    """after_user_input — inject user profile as system message. 0ms, no LLM."""
    context = get_user_context()
    if context:
        agent.current_session["messages"].append({
            "role":    "system",
            "content": f"User profile: {context}",
        })


def update_profile_background(agent) -> None:
    """on_complete — debounced background profile learner. Daemon thread."""
    global _LEARN_COUNTER, _LEARN_RUNNING
    _LEARN_COUNTER += 1
    if _LEARN_COUNTER % _LEARN_EVERY != 0:
        return
    with _LEARN_LOCK:
        if _LEARN_RUNNING:
            return
        _LEARN_RUNNING = True
    threading.Thread(target=_learn, daemon=True).start()


def _learn() -> None:
    global _LEARN_RUNNING

    items = load_history().get("items", [])[-50:]

    def _len(t: str) -> int:
        import re
        return len(t.strip()) if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", t) else len(t.split())

    texts = [
        str(i.get("raw_text", "") or i.get("final_text", "")).strip()
        for i in items
        if _len(str(i.get("raw_text", "") or i.get("final_text", "")).strip()) >= 4
    ]
    texts = [t for t in texts if t]

    if len(texts) < 5:
        with _LEARN_LOCK:
            _LEARN_RUNNING = False
        return

    sample = "\n".join(f"- {t[:120]}" for t in texts[-30:])

    agent = Agent(
        model="gpt-5.4",
        name="whispr_profile_learner",
        system_prompt=(
            "You are a usage-pattern analyser for a voice transcription app. "
            "Extract behavioural habits and work patterns only — no PII. "
            "Input may be multilingual — analyse all languages. "
            "Return ONLY valid JSON, no markdown:\n"
            '{"description":"2-3 sentence summary","habits":["topic"],"frequent_apps":["app"]}'
        ),
    )

    raw = str(agent.input(
        f"Analyse these {len(texts[-30:])} voice dictations:\n{sample}"
    )).strip().strip("`")
    if raw.startswith("json"):
        raw = raw[4:].strip()

    parsed      = json.loads(raw)
    description = str(parsed.get("description", "")).strip()
    habits      = [str(h).strip() for h in parsed.get("habits", []) if str(h).strip()][:10]
    freq_apps   = [str(a).strip() for a in parsed.get("frequent_apps", []) if str(a).strip()][:8]

    if description:
        profile = load_profile()
        profile.setdefault("learned", {})
        profile["learned"]["description"]   = description
        profile["learned"]["habits"]        = habits
        profile["learned"]["frequent_apps"] = freq_apps
        profile["learned"]["last_updated"]  = len(load_history().get("items", []))
        save_profile(profile)
        invalidate_context_cache()

    with _LEARN_LOCK:
        _LEARN_RUNNING = False


def startup_init() -> None:
    threading.Thread(target=get_user_context, daemon=True).start()