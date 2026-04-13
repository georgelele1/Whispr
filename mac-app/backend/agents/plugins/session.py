"""
agents/plugins/session.py — Shared session memory across all Whispr agents.

Maintains a rolling window of recent exchanges so each agent has context
of what was said and returned before — enabling continuations like:
  "add a PS at the end"
  "translate that to Chinese"
  "and also mention the deadline"

Usage:
    from agents.plugins.session import inject_session, session_remember, get_session_context

    # In any agent:
    agent = Agent(..., on_events=[after_user_input(inject_session)])

    # After agent completes, store the result:
    session_remember(raw_text, final_output)
"""
from __future__ import annotations

_SESSION: list[dict] = []
_SESSION_MAX = 6  # keep last 3 exchanges (6 messages)


def session_remember(raw: str, output: str) -> None:
    """Store a completed exchange. Call after each agent run."""
    global _SESSION
    if not raw.strip() or not output.strip():
        return
    _SESSION.append({"role": "user",      "content": raw.strip()[:300]})
    _SESSION.append({"role": "assistant", "content": output.strip()[:300]})
    _SESSION = _SESSION[-_SESSION_MAX:]


def get_session_context() -> str:
    """Return formatted session history string for prompt injection."""
    if not _SESSION:
        return ""
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in _SESSION
    )


def is_followup(text: str) -> bool:
    """True if text looks like a continuation of the previous exchange."""
    if not _SESSION:
        return False
    import re
    return bool(re.match(
        r"(and |also |now |add |change |remove |translate |send |make it |"
        r"what does|explain|tell me more|what about|how about|"
        r"can you|could you|please |fix |update |shorten |expand )",
        text.strip(), re.IGNORECASE,
    ))


def inject_session(agent) -> None:
    """
    after_user_input — inject recent session history as system message.
    Gives the LLM context of previous exchanges so it can handle
    continuations and references to previous output.
    """
    context = get_session_context()
    if context:
        agent.current_session["messages"].append({
            "role":    "system",
            "content": f"Recent conversation:\n{context}",
        })