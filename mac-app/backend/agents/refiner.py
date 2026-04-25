"""
agents/refiner.py — Voice transcription cleaning and formatting subagent.

Optimised version:
  - Keeps dictionary/profile/language/snippet/session context
  - Disables eval by default to reduce latency and cost
  - Shows visibility logs only when WHISPR_DEBUG_LOGS=1
  - Enables eval only when WHISPR_DEBUG_EVAL=1
"""
from __future__ import annotations

import io as _io
import re
import sys

_real_stdout = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm, on_complete
sys.stdout = _real_stdout

from storage import (
    apply_dictionary_corrections,
    get_agent_model,
    DEBUG_EVAL,
    DEBUG_LOGS,
)
from agents.profile import inject_profile, update_profile_background
from agents.dictionary_agent import inject_dictionary, update_dictionary_background
from agents.plugins.lang import inject_language
from agents.plugins.session import inject_session
from agents.plugins.snippets import inject_snippets


_CODE_APPS = {
    "terminal", "iterm", "iterm2", "warp", "hyper", "kitty", "alacritty",
    "xterm", "bash", "zsh", "fish", "powershell", "cmd",
    "vscode", "visual studio code", "cursor", "windsurf", "zed",
    "pycharm", "intellij", "webstorm", "clion", "goland", "rider",
    "xcode", "android studio", "sublime text", "vim", "neovim", "emacs",
    "jupyter", "jupyter notebook", "jupyterlab",
}


def _is_code_app(app_name: str) -> bool:
    return app_name.strip().lower() in _CODE_APPS


def _set_intent(agent) -> None:
    agent.current_session["whispr_intent"] = "refiner"


def _quick_clean(text: str) -> str:
    """
    Fast local cleaning.
    This runs before the LLM and reduces unnecessary cleanup work.
    """
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


def _build_events(raw_text: str):
    def _inject_snippets_with_raw(agent) -> None:
        agent.current_session["snippet_raw_input"] = raw_text
        inject_snippets(agent)

    events = [
        after_user_input(_set_intent),
        after_user_input(inject_session),
        after_user_input(_inject_snippets_with_raw),
        after_user_input(inject_profile),
        after_user_input(inject_dictionary),
        before_llm(inject_language),
        on_complete(update_dictionary_background),
        on_complete(update_profile_background),
    ]

    if DEBUG_EVAL:
        from agents.plugins.eval import generate_expected, evaluate_and_retry
        events.insert(5, after_user_input(generate_expected))
        events.append(on_complete(evaluate_and_retry))

    if DEBUG_LOGS:
        from agents.plugins.visibility import show_summary
        events.append(on_complete(show_summary))

    return events


def _restore_placeholders(agent, result: str) -> str:
    placeholders: dict = {}

    if getattr(agent, "current_session", None):
        placeholders = agent.current_session.get("snippet_placeholders", {}) or {}

    for placeholder, expansion in placeholders.items():
        result = result.replace(placeholder, expansion)

    return result


def run(text: str, app_name: str) -> str:
    """
    Clean and format raw transcribed speech.
    """
    raw_text = str(text or "").strip()
    app_name = str(app_name or "unknown").strip() or "unknown"

    if not raw_text:
        return ""

    is_code = _is_code_app(app_name)
    cleaned = raw_text if is_code else _quick_clean(raw_text)

    has_cjk = bool(re.search(r"[一-鿿가-힯]", raw_text))

    # Very short English text does not need LLM.
    # Do not bypass code apps because even short commands need formatting.
    if not is_code and not has_cjk and len(cleaned.split()) < 3:
        return cleaned

    agent = Agent(
        model=get_agent_model(),
        name="whispr_refiner",
        system_prompt=(
            "You are a voice transcription cleaner.\n"
            "Your job is to turn raw speech transcription into polished text.\n\n"

            "Core rules:\n"
            "1. Fix phonetic mishearings using known dictionary terms.\n"
            "2. Remove filler words and stutters such as uh, um, like, so, basically, you know.\n"
            "3. Preserve the user's meaning. Do not add new facts.\n"
            "4. Fix punctuation, spacing, and capitalisation.\n"
            "5. Respect the target output language from system context.\n"
            "6. Match the user's writing style from profile context.\n\n"

            "List formatting rules:\n"
            "- Format as a numbered list whenever the user gives multiple distinct points,\n"
            "  steps, or ideas — even if they use natural connectors like 'first', 'second',\n"
            "  'third', 'also', 'and then', 'next', 'another thing is', 'on top of that'.\n"
            "- Each list item should be a clean, complete sentence.\n"
            "- Use a numbered list (1. 2. 3.) not bullets.\n"
            "- Keep as prose only when ideas flow together as a single connected thought.\n\n"

            "App formatting rules:\n"
            "- Mail: produce a complete email when the user clearly dictates an email.\n"
            "- Slack/Teams/Chat: keep it concise and conversational.\n"
            "- Notes/Docs: use clean paragraphs or numbered lists as appropriate.\n"
            "- Terminal/code editor: convert natural speech directly into the correct shell\n"
            "  command or code. Apply these package manager conventions automatically:\n"
            "    * 'install X' or 'pip install X' → pip install X\n"
            "    * 'conda install X' or 'activate env Y' → conda install X / conda activate Y\n"
            "    * 'npm install X' or 'brew install X' → use that manager's syntax\n"
            "    * Multiple packages in one sentence → single command with all packages\n"
            "  Do not add markdown fences. Preserve flags, paths, and identifiers exactly.\n\n"

            "Snippet rules:\n"
            "- Preserve placeholders like «S0» exactly. Do not translate or remove them.\n\n"
            
            "Output rules:\n"
            "- Output ONLY the final cleaned text.\n"
            "- No preamble.\n"
            "- No explanation.\n"
            "- No follow-up suggestions."
        ),
        on_events=_build_events(raw_text),
    )

    prompt = f"[App: {app_name}]\n{cleaned}" if app_name != "unknown" else cleaned

    result = str(agent.input(prompt)).strip()
    result = result.strip('"').strip("'").strip()
    result = _restore_placeholders(agent, result)

    return result