"""
agents/intent.py — LLM-based intent detection.

Classifies intent into: calendar | knowledge | refine

Followup detection uses shared session context so consecutive questions
route correctly based on previous exchange type.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure backend root is on sys.path when run from agents/ subdirectory
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from connectonion import Agent
from storage import get_model, get_agent_model


def _classify(text: str, session_context: str = "") -> str:
    session_hint = f"\n\nRecent conversation:\n{session_context}" if session_context else ""

    agent = Agent(
        model=get_agent_model(),
        name="whispr_intent_classifier",
        system_prompt=(
            "Classify this voice transcription into exactly one label:\n\n"
            "  calendar  — the user is ASKING A QUESTION or making a QUERY directed at\n"
            "              their calendar system. They want to retrieve schedule information.\n"
            "              exams, deadlines, meetings, or asking when something is.\n"
            "              Examples: 'what is my exam date', 'when is my dentist',\n"
            "              'do I have anything today', 'search my calendar for '\n\n"
            "  knowledge — asking a factual question, wanting an explanation, definition,\n"
            "              formula, concept, or how something works.\n"
            "              Examples: 'what is Newton's law', 'explain TCP vs UDP',\n"
            "              'give me the formula for kinetic energy'\n\n"
            "  refine    — dictating text to clean up, format, translate, or send.\n"
            "              Also continuations of previous dictation.\n"
            "              Examples: 'send an email to the team', 'translate that to Chinese',\n"
            "              'and also mention the deadline'\n\n"
            "Use the recent conversation to resolve ambiguous continuations.\n"
            "If the previous response was a knowledge answer and this continues that topic,\n"
            "classify as knowledge. If it continues dictation, classify as refine."
            f"{session_hint}\n\n"
            "Reply ONLY with the label. No explanation."
        ),
    )
    result = str(agent.input(text)).strip().lower()
    return result if result in ("calendar", "knowledge", "refine") else "refine"


def detect_intent(text: str) -> str:
    """Returns: 'calendar' | 'knowledge' | 'refine'"""
    from agents.plugins.session import get_session_context, is_followup, _SESSION

    if is_followup(text) and _SESSION:
        for msg in reversed(_SESSION):
            if msg["role"] == "assistant":
                content = msg["content"]
                if len(content) > 100 or any(
                    kw in content.lower() for kw in
                    ["formula", "equation", "defined as", "refers to", "is a type",
                     "algorithm", "protocol", "theorem", "law of", "concept"]
                ):
                    return "knowledge"
                return "refine"

    return _classify(text, get_session_context())