"""
agents/profile.py — User profile learning and context caching.

Runs once at startup in a background thread.
Saves a free-text description of the user to profile.json.
Provides get_user_context() which returns the cached string in 0ms.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

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

def _build_user_context() -> str:
    """Build context string merging manual profile + auto-learned description.

    Manual fields (set by user in Settings) take priority.
    Learned description adds behavioural context from usage history.
    Recent history adds short-term memory.
    """
    parts   = []
    profile = load_profile()
    learned = profile.get("learned", {})

    # Manual identity fields — set by user in Settings UI
    name  = profile.get("name", "").strip()
    role  = profile.get("role", "").strip()
    org   = profile.get("organization", "").strip()
    email = profile.get("email", "").strip()
    if name:           parts.append(f"User: {name}.")
    if role and org:   parts.append(f"Role: {role} at {org}.")
    elif role or org:  parts.append(f"Role: {role or org}.")
    if email:          parts.append(f"Email: {email}.")

    # Auto-learned description — generated from usage history
    # Merged with manual fields: adds behavioural context the user didn't manually specify
    description = learned.get("description", "").strip()
    if description:
        # Avoid repeating info already in manual fields
        if name and name.lower() in description.lower():
            parts.append(description)
        elif not name:
            parts.append(description)
        else:
            parts.append(description)

    # Short-term memory — last 5 utterances
    recent = [
        str(i.get("final_text", ""))[:80]
        for i in load_history().get("items", [])[-5:]
        if str(i.get("final_text", "")).strip()
    ]
    if recent:         parts.append("Recent: " + " | ".join(recent) + ".")

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