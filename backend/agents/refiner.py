"""
agents/refiner.py — Voice transcription cleaning and formatting.

Handles:
  - Filler/stutter removal
  - Phonetic correction using context and dictionary
  - Numbered list detection and formatting
  - App-aware formatting (email, code, chat, document)
  - Translation to target language
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

_real_stdout = sys.stdout
sys.stdout   = _io.StringIO()
try:
    from connectonion import Agent
finally:
    sys.stdout = _real_stdout

from storage import (
    load_dictionary, get_target_language, apply_dictionary_corrections,
    SUPPORTED_LANGUAGES,
)


# =========================================================
# App-aware formatting hint
# =========================================================

def _app_hint(app_name: str) -> str:
    """Return formatting instruction based on active app."""
    app = app_name.strip().lower()
    if any(x in app for x in ("mail", "outlook", "gmail")):
        return (
            "Active app: Mail (email client). "
            "Format output as a professional email — proper greeting, clear body, sign-off. "
        )
    if any(x in app for x in ("xcode", "vscode", "code", "pycharm", "cursor", "intellij")):
        return (
            "Active app: Code editor. "
            "Format as code comments or technical notes. "
            "Use precise technical language. Preserve code terms exactly. "
        )
    if any(x in app for x in ("word", "pages", "docs", "notion", "confluence")):
        return (
            "Active app: Document editor. "
            "Format as polished document text — clear paragraphs, proper structure. "
        )
    if any(x in app for x in ("slack", "teams", "discord", "messages", "telegram")):
        return (
            "Active app: Chat/messaging. "
            "Keep output conversational and concise — suitable for chat. "
        )
    if app and app != "unknown":
        return f"Active app: {app_name.strip()}. "
    return ""


# =========================================================
# Quick clean — 0ms, no LLM
# =========================================================

def quick_clean(text: str) -> str:
    """Fast pre-clean before intent detection.

    Applies dictionary corrections + removes fillers/stutters using regex.
    No LLM — runs in 0ms.
    """
    text = apply_dictionary_corrections(text)

    fillers = re.compile(
        r"\b(uh+|um+|er+|hmm+|ah+|oh+|like|so|basically|actually|"
        r"you know|kind of|sort of|right|okay so|well)\b[,]?\s*",
        re.IGNORECASE,
    )
    text = fillers.sub(" ", text)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


# =========================================================
# Dictionary tool
# =========================================================

def get_dictionary_terms() -> dict:
    """Tool: return approved dictionary terms for the refiner agent."""
    terms = [
        {"phrase": str(item.get("phrase", "")).strip(), "aliases": item.get("aliases", [])}
        for item in load_dictionary().get("terms", [])
        if item.get("approved", True) and str(item.get("phrase", "")).strip()
    ]
    return {"terms": terms, "count": len(terms)}


# =========================================================
# Register tool helper
# =========================================================

def _register_tool(agent: Agent, fn) -> None:
    for attr in ("add_tools", "add_tool"):
        if hasattr(agent, attr) and callable(getattr(agent, attr)):
            getattr(agent, attr)(fn)
            return
    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return


# =========================================================
# Main refiner
# =========================================================

def ai_refine_text(
    text           : str,
    app_name       : str = "",
    target_language: str = "",
    user_context   : str = "",
) -> str:
    """Clean and format voice transcription text.

    Args:
        text:            Raw transcribed speech.
        app_name:        Active app name for format hints.
        target_language: Output language.
        user_context:    Pre-built user profile string.

    Returns:
        Cleaned, formatted text.
    """
    if not text.strip():
        return text

    lang = target_language.strip()
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = get_target_language()

    # Skip LLM only for short clean English-only text.
    # NEVER skip when:
    #   - text contains CJK characters (Chinese/Japanese/Korean) — no spaces so
    #     split() always returns 1 word regardless of length
    #   - translation is needed
    _has_cjk = bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    _needs_translate = True  # always enforce target language, including English
    if (
        not _has_cjk
        and not _needs_translate
        and len(text.split()) < 5
        and not re.search(r"\b(uh|um|er|so so|I I|the the)\b", text, re.IGNORECASE)
    ):
        return apply_dictionary_corrections(text)

    app_fmt  = _app_hint(app_name)
    ctx_hint = f"User context: {user_context} " if user_context else ""
    trans    = (
        f"Your entire output MUST be in {lang}. "
        f"Translate the user's speech into {lang} whenever the source language differs. "
        "If the source is already in the target language, keep it in that language while refining it. "
        "Keep technical symbols, code terms, file paths, commands, APIs, version strings, and proper nouns unchanged when appropriate."
    )

    # Skip dictionary tool — quick_clean already applied regex corrections before routing.
    # Only use tool for longer texts where context-aware correction matters.
    word_count = len(text.split())
    has_dict   = bool(load_dictionary().get("terms")) and word_count > 15
    dict_step  = "1. Call get_dictionary_terms and apply corrections. " if has_dict else ""
    offset     = 2 if has_dict else 1

    agent = Agent(
        model="gpt-5.4",
        name="whispr_text_refiner",
        system_prompt=(
            "You are a personal voice transcription assistant. "
            f"{ctx_hint}{app_fmt}"
            f"Output language: {lang}. "
            f"{dict_step}"
            f"{offset}. Fix phonetic mishearings using context and user profile. "
            f"{offset+1}. Remove ALL stutters, false starts, repeated words, "
            "filler words (uh, um, like, so, basically, actually, you know, right, okay so), "
            "interjections (ah, oh, hmm, yeah, well). "
            f"{offset+2}. Detect numbered list (point one/two, first/second/third, number one/two) "
            "→ format as numbered list, one item per line. Otherwise prose. "
            f"{offset+3}. Apply app-specific formatting strictly: "
            "If Mail/email app → structure as complete email with Subject:, greeting, body, sign-off. "
            "If code editor → use technicag zl language, preserve code terms. "
            "If chat app → keep concise and conversational. "
            "If document editor → use clear paragraphs and proper structure. "
            f"{offset+4}. Fix punctuation and capitalisation. "
            f"{trans} "
            "Output ONLY the final formatted text. No explanation."
        ),
    )
    if has_dict:
        _register_tool(agent, get_dictionary_terms)

    return str(agent.input(text)).strip().strip('"').strip("'").strip()