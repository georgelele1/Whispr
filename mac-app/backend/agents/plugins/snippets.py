"""
agents/plugins/snippets.py — Snippet expansion plugin for the refiner.

Event flow:
  after_user_input → inject_snippets:  LLM semantically matches triggers
                     against the raw speech (any language), replaces them
                     with neutral placeholders («S0», «S1», ...) in the
                     user message, and stores the placeholder→expansion map
                     in the session.

  on_complete      → restore_snippets: swaps placeholders back to their
                     expansions in the final assistant message verbatim —
                     after translation, after formatting, after eval retries.

Why placeholders survive translation:
  «S0» contains no natural language so the LLM never rephrases, translates,
  or drops it. The restore step runs after all LLM passes are complete,
  guaranteeing the expansion is always inserted exactly as the user defined it.

Why LLM matching instead of regex:
  Regex can only match literal text. A trigger defined as 'zoom link' would
  never match '我的zoom链接' or 'mon lien zoom'. The matcher LLM resolves
  intent by meaning across any input language.

Session keys:
  agent.current_session["snippet_placeholders"] — {«Si»: expansion}
  agent.current_session["snippet_raw_input"]    — original user speech
                                                   for the matcher prompt
"""
from __future__ import annotations

import json
import re

from connectonion import Agent
from snippets import load_snippets
from storage import get_agent_model


# ── helpers ──────────────────────────────────────────────────────────────────

def _active_snippets() -> list[dict]:
    return [
        s for s in load_snippets().get("snippets", [])
        if s.get("enabled", True)
        and str(s.get("trigger", "")).strip()
        and str(s.get("expansion", "")).strip()
    ]


def _get_last_user_content(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", "")).strip()
    return ""


def _get_last_assistant_content(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return str(msg.get("content", "")).strip()
    return ""


# ── event handlers ────────────────────────────────────────────────────────────

def inject_snippets(agent) -> None:
    """after_user_input — semantically match triggers, inject placeholders.

    Reads the raw input stored by the refiner under 'snippet_raw_input',
    asks the matcher LLM which snippets apply (by meaning, any language),
    then rewrites the last user message replacing each matched trigger with
    its placeholder so the main LLM processes the resolved content.
    """
    snippets = _active_snippets()
    if not snippets:
        return

    raw_input = agent.current_session.get("snippet_raw_input", "")
    messages  = agent.current_session.get("messages", [])
    user_text = _get_last_user_content(messages)
    if not raw_input and not user_text:
        return

    catalogue = "\n".join(f"{i}: {s['trigger']}" for i, s in enumerate(snippets))

    matcher = Agent(
        model=get_agent_model(),
        name="whispr_snippet_matcher",
        system_prompt=(
            "You detect which snippet triggers the user intended in their voice input.\n"
            "The user may speak in any language — match by meaning, not exact wording.\n"
            "Reply ONLY with a JSON array of matched trigger indices, e.g. [0, 2].\n"
            "If nothing matches, reply with [].\n"
            "No explanation. No markdown. Raw JSON only."
        ),
    )
    raw = str(matcher.input(
        f"User said: {raw_input or user_text}\n\nSnippet triggers:\n{catalogue}"
    )).strip()

    try:
        matched = json.loads(raw)
        if not isinstance(matched, list):
            matched = []
    except Exception:
        matched = []

    if not matched:
        return

    placeholders: dict[str, str] = {}
    result = user_text
    system_hints: list[str] = []

    for idx in matched:
        if not isinstance(idx, int) or idx >= len(snippets):
            continue
        item        = snippets[idx]
        trigger     = str(item["trigger"]).strip()
        expansion   = str(item["expansion"]).strip()
        placeholder = f"«S{idx}»"

        pattern = rf"(?<![\w]){re.escape(trigger)}(?![.\w])"
        if re.search(pattern, result, flags=re.IGNORECASE):
            # Same-language: trigger found literally — replace in-place
            result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)
        else:
            # Cross-language: user intended this snippet but said it in another language.
            # Inject as a system instruction so the LLM weaves it into the right spot
            # rather than appending a dangling placeholder to the user text.
            system_hints.append(
                f"The user intended to include their '{trigger}'. "
                f"Insert the placeholder {placeholder} at the natural location in your output "
                f"where this belongs (e.g. where a link or contact detail would go)."
            )

        placeholders[placeholder] = expansion

    # Rewrite the last user message with in-place placeholder substitutions
    for msg in reversed(messages):
        if msg.get("role") == "user":
            msg["content"] = result
            break

    # Inject cross-language snippet instructions as a system message
    if system_hints:
        messages.append({
            "role":    "system",
            "content": "Snippet instructions:\n" + "\n".join(f"- {h}" for h in system_hints),
        })

    agent.current_session["snippet_placeholders"] = placeholders


def restore_snippets(agent) -> None:
    """on_complete — swap placeholders back to expansions in the output.

    Runs after all LLM passes (including eval retries) so the final
    assistant message always contains the verbatim expansion text.
    """
    placeholders: dict[str, str] = agent.current_session.get("snippet_placeholders", {})
    if not placeholders:
        return

    messages = agent.current_session.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = str(msg.get("content", ""))
            for placeholder, expansion in placeholders.items():
                content = content.replace(placeholder, expansion)
            msg["content"] = content
            break