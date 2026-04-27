"""
agents/refiner.py — Production version

- Agent-first pipeline
- App-aware formatting via event injection + prompt
- Session + profile + dictionary + snippets
"""

from __future__ import annotations

import io as _io
import re
import sys

_real_stdout = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm
sys.stdout = _real_stdout

from storage import apply_dictionary_corrections, get_agent_model

from agents.profile import inject_profile
from agents.dictionary_agent import inject_dictionary
from agents.plugins.appname import inject_app
from agents.plugins.lang import inject_language
from agents.plugins.session import inject_session
from agents.plugins.snippets import inject_snippets


def _set_intent(agent) -> None:
    agent.current_session["whispr_intent"] = "refiner"


def _quick_clean(text: str) -> str:
    text = apply_dictionary_corrections(text)

    fillers = re.compile(
        r"\b(uh+|um+|er+|hmm+|ah+|oh+|like|so|basically|actually|"
        r"you know|kind of|sort of|right|okay so|well)\b[,]?\s*",
        re.IGNORECASE,
    )

    text = fillers.sub(" ", text)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text)

    return text.strip()


def _build_events(raw_text: str, app_name: str):
    def _inject_snippets_with_raw(agent) -> None:
        agent.current_session["snippet_raw_input"] = raw_text
        inject_snippets(agent)

    def _inject_app_with_name(agent) -> None:
        agent.current_session["whispr_app_name"] = app_name
        inject_app(agent)

    return [
        after_user_input(_set_intent),
        after_user_input(inject_session),
        after_user_input(_inject_snippets_with_raw),
        after_user_input(inject_profile),
        after_user_input(inject_dictionary),
        before_llm(_inject_app_with_name),
        before_llm(inject_language),
    ]


def _restore_placeholders(agent, result: str) -> str:
    session = getattr(agent, "current_session", None) or {}
    placeholders = session.get("snippet_placeholders", {}) or {}

    for placeholder, expansion in placeholders.items():
        result = result.replace(placeholder, expansion)

    return result


def run(text: str, app_name: str = "unknown") -> str:
    raw_text = str(text or "").strip()
    app_name = str(app_name or "unknown").strip() or "unknown"

    if not raw_text:
        return ""

    cleaned = _quick_clean(raw_text)

    agent = Agent(
        model=get_agent_model(),
        name="whispr_refiner",
        system_prompt=(
            "You are a voice transcription cleaner and formatter.\n"
            "Your job is to convert raw speech transcription into clean, accurate, and context-aware text.\n\n"

            "Core principles:\n"
            "1. Preserve the user's meaning exactly. Never add new facts or assumptions.\n"
            "2. Fix transcription errors, including phonetic mishearings, using known dictionary terms.\n"
            "3. Remove filler words and disfluencies such as 'uh', 'um', 'like', 'so', 'basically', 'you know'.\n"
            "4. Fix grammar, punctuation, spacing, and capitalisation.\n"
            "5. Respect the target output language provided in system context.\n"
            "6. Match the user's writing style from profile context when available.\n\n"

            "Formatting rules:\n"
            "- Convert fragmented speech into natural, well-structured text.\n"
            "- Use paragraphs for continuous ideas.\n"
            "- Use numbered lists ONLY when the user clearly expresses multiple distinct steps, points, or items.\n"
            "- Do NOT force a list if the content is naturally a single idea.\n"
            "- Each list item must be a complete, clean sentence.\n\n"

            "App-aware behaviour:\n"
            "- You will receive the active app name as context.\n"
            "- Infer the correct output format based on BOTH the app name AND the user's intent.\n"
            "- Do NOT rely on a fixed list of apps. Reason dynamically.\n\n"

            "When deciding format:\n"
            "- If the context suggests coding, terminal, shell, or developer tools:\n"
            "  Output the correct command or code directly.\n"
            "  Combine multiple packages into one command when appropriate.\n"
            "  Preserve flags, paths, filenames, identifiers, and quoted strings exactly.\n"
            "  Do NOT add markdown formatting.\n\n"

            "- If the active app context suggests email, mail, Gmail, Outlook, or formal communication:\n"
            "  Format the output as an email when the user appears to be writing or replying to someone.\n"
            "  Use a natural email structure when appropriate:\n"
            "  greeting, body, closing.\n"
            "  If the user provides a recipient name, use it in the greeting.\n"
            "  If no recipient is provided, use a neutral greeting such as 'Hi,' only when a full email is appropriate.\n"
            "  If the input is very short and only sounds like a sentence, keep it as a polished email sentence.\n"

            "- If the context suggests chat or messaging:\n"
            "  Keep the tone concise and conversational.\n\n"

            "- If the context suggests notes, documents, or writing tools:\n"
            "  Use structured paragraphs or lists when appropriate.\n\n"

            "- If the app context is unclear:\n"
            "  Default to clean, neutral, well-formatted text.\n\n"

            "Snippet rules:\n"
            "- Preserve placeholders like «S0» exactly.\n"
            "- Do NOT translate, remove, or modify placeholders.\n\n"

            "Strict constraints:\n"
            "- Do NOT invent content.\n"
            "- Do NOT over-format.\n"
            "- Do NOT change meaning.\n"
            "- Do NOT add explanations.\n\n"

            "Context-awareness rules:\n"
            "- Recent conversation context may be provided.\n"
            "- Decide whether the current input depends on previous context by meaning, not keywords.\n"
            "- If it is a follow-up, revise or transform the previous assistant output.\n"
            "- If it is independent, ignore the previous context.\n"
            "- Do NOT output the follow-up instruction itself.\n\n"

            "Output rules:\n"
            "- Output ONLY the final cleaned text.\n"
            "- No preamble.\n"
            "- No commentary.\n"
            "- No extra text."
        ),
        on_events=_build_events(raw_text, app_name),
    )

    prompt = (
        f"Active app: {app_name}\n"
        f"Raw transcription:\n{cleaned}\n\n"
        "Generate final output."
    )

    result = str(agent.input(prompt)).strip()
    result = result.strip('"').strip("'").strip()
    result = _restore_placeholders(agent, result)

    return result