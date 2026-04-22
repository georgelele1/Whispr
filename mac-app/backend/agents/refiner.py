"""
agents/refiner.py — Voice transcription cleaning and formatting subagent.

Events:
  after_user_input → inject_profile      (user style + habits)
  after_user_input → inject_dictionary   (known terms to fix)
  before_llm       → inject_language     (language plugin)
  on_complete      → apply_snippets      (applied to return value, not on_complete)
  on_complete      → update_dictionary_background (debounced, daemon)
  on_complete      → update_profile_background    (debounced, daemon)
  on_complete      → show_summary        (visibility plugin)
"""
from __future__ import annotations

import re
import sys
import io as _io

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm, on_complete
sys.stdout = _real

from storage import apply_dictionary_corrections, get_agent_model
from agents.profile   import inject_profile, update_profile_background
from agents.dictionary_agent import inject_dictionary, update_dictionary_background
from agents.plugins.lang    import inject_language
from agents.plugins.session  import inject_session, session_remember
from agents.plugins.visibility import show_summary


def _apply_snippets(text: str) -> str:
    """Post-process final output — expand trigger words in-place.
    Appends expansion in parentheses so the original word is preserved.
    Applied directly to the return value, not via on_complete.
    """
    from snippets import load_snippets
    for item in load_snippets().get("snippets", []):
        if not item.get("enabled", True):
            continue
        trigger   = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()
        if trigger and expansion:
            # Use lookahead/lookbehind instead of \b so multi-word
            # triggers like "zoom link" match correctly across spaces.
            pattern = rf"(?<![\w]){re.escape(trigger)}(?![\w])"
            escaped_expansion = expansion.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            text = re.sub(
                pattern,
                rf"\g<0> ({escaped_expansion})",
                text,
                flags=re.IGNORECASE,
            )
    return text


def _set_intent(agent) -> None:
    """after_user_input — tag session intent for visibility plugin."""
    agent.current_session["whispr_intent"] = "refiner"


def _quick_clean(text: str) -> str:
    """Remove fillers and stutters — 0ms, no LLM."""
    text = apply_dictionary_corrections(text)
    fillers = re.compile(
        r"\b(uh+|um+|er+|hmm+|ah+|oh+|like|so|basically|actually|"
        r"you know|kind of|sort of|right|okay so|well)\b[,]?\s*",
        re.IGNORECASE,
    )
    text = fillers.sub(" ", text)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", text).strip()


def run(text: str, app_name: str) -> str:
    """Clean and format raw transcribed speech."""
    cleaned = _quick_clean(text)
    has_cjk = bool(re.search(r"[一-鿿぀-ヿ가-힯]", text))

    # Bypass LLM only for very short English — single words or two-word phrases
    if not has_cjk and len(cleaned.split()) < 3:
        return cleaned

    agent = Agent(
        model=get_agent_model(),
        name="whispr_refiner",
        system_prompt=(
            "You are a voice transcription cleaner.\n"
            "1. Fix phonetic mishearings using the known terms in your context.\n"
            "2. Remove stutters, false starts, filler words "
            "(uh, um, like, so, basically, you know, right, okay so).\n"
            "3. Format as a numbered list when ANY of these apply:\n"
            "   a) Explicit list speech: 'point one/two', 'first/second/third', 'number one/two'\n"
            "   b) Long text (4+ sentences) with multiple distinct keypoints, topics, or action items\n"
            "   c) Instructions or steps where sequence matters\n"
            "   For prose sentences that flow naturally together, keep as paragraph — do not force a list.\n"
            "4. Fix punctuation and capitalisation.\n"
            "5. Format for the active app in your context:\n"
            "   - Mail → complete email with Subject:, greeting, body, sign-off\n"
            "   - Slack/Teams → short conversational message\n"
            "   - Notes/Docs → clean paragraphs or lists as appropriate\n"
            "   - Code editor → technical language, preserve code terms exactly\n"
            "6. Match the user's preferred writing style from their profile.\n"
            "Output ONLY the final cleaned text.\n"
            "NEVER add preamble like \"A cleaned-up version is:\", \"Here is the text:\", \"Certainly\".\n"
            "NEVER offer follow-up suggestions like \"I can also make it more formal\".\n"
            "NEVER explain what you did. First word of output must be first word of the actual content."
        ),
        on_events=[
            after_user_input(_set_intent),
            after_user_input(inject_session),
            after_user_input(inject_profile),
            after_user_input(inject_dictionary),
            before_llm(inject_language),
            on_complete(update_dictionary_background),
            on_complete(update_profile_background),
            on_complete(show_summary),
        ],
    )

    prompt = f"[App: {app_name}]\n{cleaned}" if app_name and app_name != "unknown" else cleaned
    result = str(agent.input(prompt)).strip().strip('"').strip("'")
    return _apply_snippets(result)