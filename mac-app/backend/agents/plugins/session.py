"""
agents/plugins/session.py — Shared session memory across all Whispr agents.

Persists to disk so context survives across separate CLI process invocations.
Each transcription is a new process — without disk persistence the session
resets every time and context-aware continuations never work.

Session file: ~/Library/Application Support/Whispr/session.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SESSION_MAX  = 6      # keep last 3 exchanges (6 messages)
_CONTENT_MAX  = 600    # chars per message — enough for full sentences


def _session_path() -> Path:
    import os
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "Whispr"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / "Whispr"
    else:
        base = home / ".local" / "share" / "Whispr"
    base.mkdir(parents=True, exist_ok=True)
    return base / "session.json"


SESSION_TTL_HOURS = 1  # session expires after 60 minutes of inactivity


def _load() -> list[dict]:
    path = _session_path()
    if not path.exists():
        return []
    try:
        import time
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return []
        # Expire session if inactive for more than TTL
        last_updated = raw.get("updated_at", 0)
        if time.time() - last_updated > SESSION_TTL_HOURS * 3600:
            return []
        return raw.get("messages", [])
    except Exception:
        return []


def _save(session: list[dict]) -> None:
    try:
        import time
        _session_path().write_text(
            json.dumps({"updated_at": time.time(), "messages": session}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def session_remember(raw: str, output: str) -> None:
    """Store a completed exchange — persisted to disk immediately."""
    if not raw.strip() or not output.strip():
        return
    session = _load()
    session.append({"role": "user",      "content": raw.strip()[:_CONTENT_MAX]})
    session.append({"role": "assistant", "content": output.strip()[:_CONTENT_MAX]})
    session = session[-_SESSION_MAX:]
    _save(session)


def get_session_context() -> str:
    """Return formatted session history for prompt injection."""
    session = _load()
    if not session:
        return ""
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in session
    )


def is_followup(text: str) -> bool:
    """True if text looks like a continuation of the previous exchange."""
    if not _load():
        return False
    import re
    return bool(re.match(
        r"(and |also |now |add |change |remove |translate |send |make it |"
        r"what does|explain|tell me more|what about|how about|"
        r"can you|could you|please |fix |update |shorten |expand |"
        r"write |draft |compose |create )",
        text.strip(), re.IGNORECASE,
    ))


def inject_session(agent) -> None:
    """after_user_input — inject persisted session history as system message."""
    context = get_session_context()
    if context:
        agent.current_session["messages"].append({
            "role":    "system",
            "content": f"Recent conversation context (use this to inform your response):\n{context}",
        })


def clear_session() -> None:
    """Clear session history — called on reset-all."""
    _save([])