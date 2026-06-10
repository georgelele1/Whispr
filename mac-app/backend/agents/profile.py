"""
agents/profile.py — User profile context injection and background learning.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from connectonion import Agent

from storage import (
    load_profile,
    save_profile,
    load_history,
    SUPPORTED_LANGUAGES,
    get_agent_model,
)


_CONTEXT_CACHE: str = ""
_CONTEXT_READY: bool = False
_CACHE_LOCK = threading.Lock()

_LEARN_EVERY = 50
_LEARN_RUNNING = False
_LEARN_LOCK = threading.Lock()


def _build_context() -> str:
    parts = []
    profile = load_profile()
    learned = profile.get("learned", {})

    career = str(profile.get("career_area", "")).strip()
    if career:
        parts.append(f"Professional area: {career}.")

    usage = profile.get("usage_type", [])
    if usage:
        parts.append(f"Uses Whispr for: {', '.join(usage)}.")

    style = str(profile.get("writing_style", "")).strip()
    if style:
        parts.append(f"Preferred writing style: {style}.")

    description = str(learned.get("description", "")).strip()
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
    career_area: str = "",
    usage_type: list | None = None,
    writing_style: str = "casual",
    language: str = "",
) -> None:
    profile = load_profile()

    career_area = str(career_area or "").strip()
    if career_area:
        profile["career_area"] = career_area

    profile["usage_type"] = [
        str(item).strip()
        for item in (usage_type or [])
        if str(item).strip()
    ]

    profile["writing_style"] = (
        writing_style
        if writing_style in ("formal", "casual", "technical")
        else "casual"
    )

    if language in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = language

    profile["onboarding_done"] = True

    save_profile(profile)
    invalidate_context_cache()


# =========================================================
# Event handlers
# =========================================================

def inject_profile(agent) -> None:
    context = get_user_context()

    if context:
        agent.current_session["messages"].append({
            "role": "system",
            "content": f"User profile: {context}",
        })


def should_learn_profile() -> bool:
    items = load_history().get("items", [])
    history_count = len(items)
    learned = load_profile().get("learned", {})
    last_history_ts = int(learned.get("last_history_ts", 0) or 0)
    learning_started_at = float(learned.get("learning_started_at", 0) or 0)
    if learning_started_at and time.time() - learning_started_at < 600:
        return False

    if last_history_ts:
        new_count = sum(int(item.get("ts", 0) or 0) > last_history_ts for item in items)
    else:
        last_updated = int(learned.get("last_updated", 0) or 0)
        new_count = max(0, history_count - last_updated)

    return history_count >= 5 and new_count >= _LEARN_EVERY


def schedule_profile_learning() -> bool:
    """Start a detached learner so the transcription response is not delayed."""
    if not should_learn_profile():
        return False

    profile = load_profile()
    profile.setdefault("learned", {})["learning_started_at"] = time.time()
    save_profile(profile)

    app_path = Path(__file__).resolve().parent.parent / "app.py"
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )

    try:
        subprocess.Popen(
            [sys.executable, str(app_path), "cli", "learn-profile"],
            **kwargs,
        )
        return True
    except Exception:
        profile = load_profile()
        profile.setdefault("learned", {})["learning_started_at"] = 0
        save_profile(profile)
        return False


def _text_len(text: str) -> int:
    text = str(text or "").strip()

    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
        return len(text)

    return len(text.split())


def learn_profile_now() -> bool:
    global _LEARN_RUNNING

    with _LEARN_LOCK:
        if _LEARN_RUNNING:
            return False
        _LEARN_RUNNING = True

    try:
        items = load_history().get("items", [])[-50:]

        texts = []

        for item in items:
            text = str(item.get("raw_text", "") or item.get("final_text", "")).strip()

            if text and _text_len(text) >= 4:
                app_name = str(item.get("app_name", "")).strip()
                prefix = f"[{app_name}] " if app_name else ""
                texts.append(prefix + text)

        if len(texts) < 5:
            return False

        sample = "\n".join(f"- {text[:120]}" for text in texts[-30:])

        agent = Agent(
            model=get_agent_model(),
            name="whispr_profile_learner",
            system_prompt=(
                "You are a usage-pattern analyser for a voice transcription app. "
                "Extract behavioural habits and work patterns only. Do not extract PII. "
                "Input may be multilingual. Analyse all languages. "
                "Return ONLY valid JSON, no markdown:\n"
                '{"description":"2-3 sentence summary","habits":["topic"],"frequent_apps":["app"]}'
            ),
        )

        raw = str(agent.input(
            f"Analyse these {len(texts[-30:])} voice dictations:\n{sample}"
        )).strip()

        raw = raw.strip("`").strip()

        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

        parsed = json.loads(raw)

        description = str(parsed.get("description", "")).strip()

        habits = [
            str(item).strip()
            for item in parsed.get("habits", [])
            if str(item).strip()
        ][:10]

        freq_apps = [
            str(item).strip()
            for item in parsed.get("frequent_apps", [])
            if str(item).strip()
        ][:8]

        if description:
            profile = load_profile()
            profile.setdefault("learned", {})
            profile["learned"]["description"] = description
            profile["learned"]["habits"] = habits
            profile["learned"]["frequent_apps"] = freq_apps
            profile["learned"]["last_updated"] = len(load_history().get("items", []))
            profile["learned"]["last_history_ts"] = max(
                (int(item.get("ts", 0) or 0) for item in items),
                default=0,
            )
            profile["learned"]["learning_started_at"] = 0

            save_profile(profile)
            invalidate_context_cache()
            return True
        return False

    finally:
        with _LEARN_LOCK:
            _LEARN_RUNNING = False


def startup_init() -> None:
    threading.Thread(target=get_user_context, daemon=True).start()
