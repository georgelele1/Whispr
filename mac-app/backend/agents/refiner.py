"""
agents/refiner.py — Voice transcription cleaning and formatting subagent.

Events:
  after_user_input → inject_profile      (user style + habits)
  after_user_input → inject_dictionary   (known terms to fix)
  after_user_input → generate_expected   (eval plugin)
  before_llm       → inject_language     (language plugin)
  on_complete      → apply_snippets      (applied to return value after LLM)
  on_complete      → update_dictionary_background (debounced, daemon)
  on_complete      → update_profile_background    (debounced, daemon)
  on_complete      → show_summary        (visibility plugin)
  on_complete      → evaluate_output     (eval plugin)
"""
from __future__ import annotations

import re
import sys
import io as _io

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm, on_complete
sys.stdout = _real

from storage import apply_dictionary_corrections
from agents.profile   import inject_profile, update_profile_background
from agents.dictionary_agent import inject_dictionary, update_dictionary_background
from agents.plugins.lang    import inject_language
from agents.plugins.session  import inject_session, session_remember
from agents.plugins.visibility import show_summary
from agents.plugins.eval       import generate_expected, evaluate_and_retry


def _apply_snippets(text: str) -> str:
    """Post-process — expand snippet triggers in the final output. No LLM."""
    from snippets import load_snippets
    for item in load_snippets().get("snippets", []):
        if not item.get("enabled", True):
            continue
        trigger   = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()
        if trigger and expansion:
            text = re.sub(
                rf"\b{re.escape(trigger)}\b", expansion, text, flags=re.IGNORECASE
            )
    return text


def _set_intent(agent) -> None:
    """after_user_input — tag session so eval plugin knows which criteria to apply."""
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
    has_cjk = bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))

    if not has_cjk and len(cleaned.split()) < 5:
        return cleaned

    agent = Agent(
        model="gpt-5.4",
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
            "Output ONLY the final cleaned text.\n""NEVER add preamble like \"A cleaned-up version is:\", \"Here is the text:\", \"Certainly\".\n""NEVER offer follow-up suggestions like \"I can also make it more formal\".\n""NEVER explain what you did. First word of output must be first word of the actual content."
        ),
        on_events=[
            after_user_input(_set_intent),
            after_user_input(inject_session),
            after_user_input(inject_profile),
            after_user_input(inject_dictionary),
            after_user_input(generate_expected),
            before_llm(inject_language),
            on_complete(update_dictionary_background),
            on_complete(update_profile_background),
            on_complete(show_summary),
            on_complete(evaluate_and_retry),
        ],
    )

    # Inject app name into the input so the LLM sees it alongside the text
    prompt = f"[App: {app_name}]\n{cleaned}" if app_name and app_name != "unknown" else cleaned
    result = str(agent.input(prompt)).strip().strip('"').strip("'")
    return _apply_snippets(result)