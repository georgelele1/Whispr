"""
agents/intent.py — 2-layer intent detection with shared session context.

Layer 1: regex fast-path — obvious trigger words, 0ms, no LLM.
Layer 2: LLM classifier — only fires when Layer 1 misses.

Followup detection uses the SHARED session from plugins/session.py so
a knowledge followup ("what does that mean", "can you explain more")
correctly routes back to the knowledge agent, not the refiner.

Returns: "calendar" | "knowledge" | "refine"
"""
from __future__ import annotations

import re
import sys
import io as _io

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent
sys.stdout = _real

_CALENDAR = re.compile(
    r"\b("
    r"(show|check|see|get|find|what['\u2019]?s|what\s+do\s+i\s+have|do\s+i\s+have)"
    r"\s+(my\s+)?(schedule|calendar|events?|agenda|meetings?|appointments?)"
    r"|what['\u2019]?s\s+(on|happening)\s+(today|tomorrow|this\s+week|next\s+week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|am\s+i\s+(free|available|busy)"
    r"|when\s+is\s+(my\s+)?\w[\w\s]{1,30}?(exam|class|meeting|appointment|tutorial|lecture)"
    r"|search\s+(my\s+)?(calendar|schedule)\s+for"
    r")\b",
    re.IGNORECASE,
)

_KNOWLEDGE = re.compile(
    r"\b("
    r"what\s+is|what\s+are|explain|define|tell\s+me|give\s+me"
    r"|how\s+does|how\s+do|formula|equation|law\s+of"
    r"|difference\s+between|meaning\s+of|example\s+of"
    r"|theory|concept|steps\s+(to|for)"
    r")\b",
    re.IGNORECASE,
)

# Patterns that signal a followup to the PREVIOUS exchange
_FOLLOWUP = re.compile(
    r"^(and\s|also\s|now\s|but\s|so\s|then\s|what\s+about\s|how\s+about\s"
    r"|can\s+you\s|could\s+you\s|please\s|more\s+about\s"
    r"|tell\s+me\s+more|explain\s+more|go\s+deeper|elaborate"
    r"|what\s+does\s+that\s+mean|what\s+do\s+you\s+mean"
    r"|give\s+me\s+an\s+example|show\s+me\s+an\s+example"
    r"|can\s+you\s+explain|break\s+it\s+down"
    r"|translate\s+that|send\s+that|add\s+to\s+that"
    r"|what\s+does\s+.{1,30}\s+(mean|stand\s+for|refer\s+to))",
    re.IGNORECASE,
)


def _layer1(text: str) -> str | None:
    if _CALENDAR.search(text):
        return "calendar"
    if _KNOWLEDGE.search(text):
        return "knowledge"
    return None


def _last_intent() -> str | None:
    """
    Check what the previous exchange was about using the shared session.
    Returns 'knowledge' if the last assistant response was a knowledge answer,
    'refine' if it was cleaned dictation, or None if no session.
    """
    from agents.plugins.session import _SESSION
    if not _SESSION:
        return None
    # Look at last assistant message — if it looks like a knowledge answer
    # (long, contains technical content) vs refined dictation (short prose)
    for msg in reversed(_SESSION):
        if msg["role"] == "assistant":
            content = msg["content"]
            # Knowledge answers tend to be longer and contain explanation patterns
            if len(content) > 100 or any(
                kw in content.lower() for kw in
                ["formula", "equation", "refers to", "defined as", "is a", "are the",
                 "algorithm", "protocol", "function", "method", "concept"]
            ):
                return "knowledge"
            return "refine"
    return None


def _layer2(text: str, session_context: str = "") -> str:
    session_hint = f"\n\nRecent conversation:\n{session_context}" if session_context else ""
    agent = Agent(
        model="gpt-5.4",
        name="whispr_intent_classifier",
        system_prompt=(
            "Classify this voice transcription into exactly one label:\n"
            "  calendar  — asking about schedule, events, appointments\n"
            "  knowledge — asking a question, wanting explanation, fact, formula, definition, "
            "or following up on a previous knowledge answer\n"
            "  refine    — dictating text to clean, format, translate, send, "
            "or continuing previous dictation\n"
            "Use the recent conversation to resolve ambiguous continuations. "
            "If the previous response was a knowledge answer and this continues that topic, "
            "classify as knowledge."
            f"{session_hint}\n\n"
            "Reply ONLY with the label. No explanation."
        ),
    )
    result = str(agent.input(text)).strip().lower()
    return result if result in ("calendar", "knowledge", "refine") else "refine"


def detect_intent(text: str) -> str:
    """Returns: 'calendar' | 'knowledge' | 'refine'"""
    from agents.plugins.session import get_session_context, is_followup

    # Layer 1 — regex on cleaned text
    intent = _layer1(text)
    if intent:
        print(f"[intent] L1 → {intent}", file=sys.stderr)
        return intent

    # Followup fast-path — check if this looks like a continuation
    # and route based on what the PREVIOUS exchange was about
    if is_followup(text):
        last = _last_intent()
        if last:
            print(f"[intent] followup → {last} (based on previous exchange)", file=sys.stderr)
            return last
        # Followup but no session — default to refine
        print("[intent] followup → refine (no session)", file=sys.stderr)
        return "refine"

    # Layer 2 — LLM with session context
    intent = _layer2(text, get_session_context())
    print(f"[intent] L2 → {intent}", file=sys.stderr)
    return intent