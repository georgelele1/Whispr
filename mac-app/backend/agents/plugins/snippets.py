"""
agents/plugins/snippets.py — Snippet expansion plugin for Whispr.

Optimized version:
- First tries exact trigger matching locally
- Only calls LLM matcher when no exact match is found
- Uses placeholders like «S0» so snippets survive translation/formatting
"""

from __future__ import annotations

import json
import re

from connectonion import Agent
from snippets import load_snippets
from storage import get_agent_model


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


def _replace_last_user_message(messages: list, content: str) -> None:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            msg["content"] = content
            return


def _trigger_pattern(trigger: str) -> str:
    return rf"(?<![\w]){re.escape(trigger)}(?![\w])"


def _exact_match_snippets(
    snippets: list[dict],
    user_text: str,
) -> tuple[str, dict[str, str], list[int]]:
    result = user_text
    placeholders: dict[str, str] = {}
    matched_indices: list[int] = []

    for idx, item in enumerate(snippets):
        trigger = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()

        if not trigger or not expansion:
            continue

        pattern = _trigger_pattern(trigger)

        if re.search(pattern, result, flags=re.IGNORECASE):
            placeholder = f"«S{idx}»"
            result = re.sub(pattern, placeholder, result, flags=re.IGNORECASE)
            placeholders[placeholder] = expansion
            matched_indices.append(idx)

    return result, placeholders, matched_indices


def _semantic_match_snippets(
    snippets: list[dict],
    raw_input: str,
    user_text: str,
) -> list[int]:
    catalogue = "\n".join(
        f"{i}: {s['trigger']}"
        for i, s in enumerate(snippets)
    )

    matcher = Agent(
        model=get_agent_model(),
        name="whispr_snippet_matcher",
        system_prompt=(
            "You detect which snippet triggers the user intended in their voice input.\n"
            "Match by meaning, not exact wording.\n"
            "The user may speak in any language.\n"
            "Reply ONLY with a JSON array of matched trigger indices, for example [0, 2].\n"
            "If nothing matches, reply with [].\n"
            "No explanation. No markdown."
        ),
    )

    try:
        raw = str(matcher.input(
            f"User said:\n{raw_input or user_text}\n\n"
            f"Snippet triggers:\n{catalogue}"
        )).strip()
    except Exception:
        return []

    try:
        matched = json.loads(raw)
    except Exception:
        return []

    if not isinstance(matched, list):
        return []

    return [
        i for i in matched
        if isinstance(i, int) and 0 <= i < len(snippets)
    ]


def inject_snippets(agent) -> None:
    snippets = _active_snippets()
    if not snippets:
        return

    raw_input = str(agent.current_session.get("snippet_raw_input", "")).strip()
    messages = agent.current_session.get("messages", [])
    user_text = _get_last_user_content(messages)

    if not raw_input and not user_text:
        return

    # 1. Fast path: exact local trigger matching. No LLM.
    result, placeholders, matched_indices = _exact_match_snippets(
        snippets,
        user_text,
    )

    if matched_indices:
        _replace_last_user_message(messages, result)
        agent.current_session["snippet_placeholders"] = placeholders
        return

    # 2. Slow path: semantic cross-language matching. Uses LLM only if needed.
    matched_indices = _semantic_match_snippets(
        snippets,
        raw_input,
        user_text,
    )

    if not matched_indices:
        return

    system_hints: list[str] = []

    placeholders = {}

    for idx in matched_indices:
        item = snippets[idx]
        trigger = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()

        if not trigger or not expansion:
            continue

        placeholder = f"«S{idx}»"
        placeholders[placeholder] = expansion

        system_hints.append(
            f"The user intended to include their '{trigger}'. "
            f"Insert placeholder {placeholder} at the natural location in the output."
        )

    if not placeholders:
        return

    messages.append({
        "role": "system",
        "content": "Snippet instructions:\n" + "\n".join(
            f"- {hint}" for hint in system_hints
        ),
    })

    agent.current_session["snippet_placeholders"] = placeholders


def restore_snippets(agent) -> None:
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
            return
