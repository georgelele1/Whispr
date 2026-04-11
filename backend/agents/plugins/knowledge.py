"""
agents/plugins/knowledge.py — Knowledge lookup plugin.

Handles: facts, formulas, scientific laws, definitions, follow-up questions.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

import io as _io
import re
import sys

_real = sys.stdout
sys.stdout = _io.StringIO()
try:
    from connectonion import Agent
finally:
    sys.stdout = _real

from agents.plugins.base import WhisprPlugin
from storage import SUPPORTED_LANGUAGES, load_profile

# =========================================================
# Session memory — in-process conversation context
# =========================================================

_SESSION: list = []
_SESSION_MAX   = 6


def session_remember(user: str, assistant: str) -> None:
    global _SESSION
    _SESSION.append({"role": "user",      "content": user})
    _SESSION.append({"role": "assistant",  "content": assistant})
    _SESSION = _SESSION[-_SESSION_MAX:]


def session_context() -> str:
    if not _SESSION:
        return ""
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:200]}"
        for m in _SESSION
    )


def is_followup(text: str) -> bool:
    if not _SESSION:
        return False
    return bool(re.match(
        r"(what (does|is|are)|explain|tell me more|and |also |now "
        r"|each (character|letter|symbol|variable|term|part|one)"
        r"|the (formula|equation|rule|law|definition|first|second|third)"
        r"|what about|how about|give me (an )?example"
        r"|can you explain|break (it|them|this) down"
        r"|what does .{1,20} (mean|stand for|represent))",
        text.strip(), re.IGNORECASE,
    ))


# =========================================================
# Knowledge plugin
# =========================================================

_TRIGGERS = re.compile(
    r"\b(give me|show me|what is|what are|explain|define|tell me|"
    r"want explanation|want to know|want to understand|"
    r"describe|how does|how do|formula|equation|law|"
    r"difference between|compare|what.?s the difference|"
    r"definition|theory|concept|rule|steps|example of|meaning of)\b",
    re.IGNORECASE,
)


class KnowledgePlugin(WhisprPlugin):
    name        = "knowledge"
    description = (
        "Answers questions about facts, formulas, scientific laws, definitions, "
        "explanations, history, math, chemistry, physics, CS concepts, and any "
        "domain knowledge. Also handles follow-up questions about previous answers."
    )
    examples    = [
        "give me Newton second law",
        "explain redox in chemistry",
        "what is the formula for gravity",
        "what does each character mean",
        "difference between if and while loop",
    ]
    priority    = 10

    def can_handle(self, text: str, context: dict) -> bool:
        # Fast-path for very clear knowledge requests
        return bool(_TRIGGERS.search(text)) or is_followup(text)

    def run(self, text: str, context: dict) -> str:
        app_name        = context.get("app_name", "")
        target_language = context.get("target_language", "")
        user_context    = context.get("user_context", "")

        lang = target_language.strip()
        if not lang or lang not in SUPPORTED_LANGUAGES:
            lang = load_profile().get("preferences", {}).get("target_language", "English")

        context_hint = f"User context: {user_context} " if user_context else ""
        app_hint     = f"Active app: {app_name}. " if app_name and app_name != "unknown" else ""
        session      = session_context()
        session_hint = f"\n\nConversation so far:\n{session}" if session else ""
        lang_hint    = (
            f"IMPORTANT: Your entire response MUST be in {lang}. "
            f"Translate everything to {lang} — keep only technical symbols as-is. "
            if lang != "English" else ""
        )

        agent = Agent(
            model="gpt-5.4",
            name="whispr_knowledge_agent",
            system_prompt=(
                "You are a universal knowledge assistant. "
                "Cover ALL domains: physics, chemistry, math, CS, medicine, "
                "finance, law, biology, history, engineering, and more. "
                f"{context_hint}{app_hint}"
                "Rules:\n"
                "1. Follow-ups → resolve from conversation history.\n"
                "2. Formulas → proper notation + variable meanings.\n"
                "3. Steps/processes → numbered list.\n"
                "4. Definitions → concise and domain-specific.\n"
                "5. Tailor to active app (Xcode→code; Mail→prose).\n"
                "6. CRITICAL — no preamble ever: never start with 'Here is', 'Sure', "
                "'Here\\'s the', 'This is the', 'Transcription:', 'Output:', or any introduction. "
                "Your first word must be the first word of the actual answer.\n"
                f"7. {lang_hint}"
                f"{session_hint}"
            ),
        )
        try:
            result = str(agent.input(text)).strip().strip('"').strip("'")
            if result:
                session_remember(text, result)
            return result if result else text
        except Exception as e:
            print(f"[knowledge] failed: {e}", file=sys.stderr)
            return text


# Export singleton
plugin = KnowledgePlugin()