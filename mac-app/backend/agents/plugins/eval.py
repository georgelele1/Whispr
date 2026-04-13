"""
agents/plugins/eval.py — Output evaluation with retry loop.

Event flow:
  after_user_input → generate_expected: describe what correct output looks like
  on_complete      → evaluate_and_retry: score actual vs expected
                     if FAIL or PARTIAL → re-run agent with correction prompt
                     up to MAX_RETRIES times

Session keys set:
  agent.current_session["expected"]    — expected outcome description
  agent.current_session["evaluation"]  — final verdict string
  agent.current_session["retries"]     — number of retries used
"""
from __future__ import annotations

import sys
import io as _io

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent
sys.stdout = _real

from storage import get_target_language

MAX_RETRIES = 2

_CRITERIA = {
    "refiner":   "Clean text, no fillers, correct language, formatted for active app.",
    "knowledge": "Direct answer, no preamble, factually accurate, correct domain.",
    "calendar":  "Actual schedule data or clear no-events message, correct date.",
}


def _get_last_assistant(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            return str(msg.get("content", "")).strip()
    return ""


def _get_last_user(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content", "")).strip()
    return ""


def _judge(expected: str, actual: str) -> tuple[str, str]:
    """Run eval judge. Returns (verdict, reason) where verdict is PASS/PARTIAL/FAIL."""
    evaluator = Agent(
        model="gpt-5.4",
        name="whispr_eval_judge",
        system_prompt=(
            "Evaluate if the actual output meets the expected criteria.\n"
            "Reply with exactly: PASS / PARTIAL / FAIL — then one sentence explaining why.\n"
            "Be strict — PARTIAL means it mostly works but has a clear fixable issue.\n"
            "FAIL means it clearly does not meet the criteria."
        ),
    )
    result = str(evaluator.input(
        f"Expected criteria: {expected}\n\nActual output: {actual[:600]}"
    )).strip()

    upper = result.upper()
    if upper.startswith("PASS"):
        verdict = "PASS"
    elif upper.startswith("PARTIAL"):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    reason = result[len(verdict):].strip().lstrip("-:— ").strip()
    return verdict, reason


def generate_expected(agent) -> None:
    """
    after_user_input — generate expected outcome and store in session.
    Called once per agent run before any LLM iteration.
    """
    messages   = agent.current_session.get("messages", [])
    user_input = _get_last_user(messages)
    if not user_input:
        return

    intent   = agent.current_session.get("whispr_intent", "refiner")
    criteria = _CRITERIA.get(intent, _CRITERIA["refiner"])
    lang     = get_target_language()

    evaluator = Agent(
        model="gpt-5.4",
        name="whispr_eval_expected",
        system_prompt=(
            "Describe what a correct output looks like for a voice transcription assistant. "
            "1-2 sentences, specific to the input. No examples."
        ),
    )
    expected = str(evaluator.input(
        f"Input: {user_input}\n"
        f"Intent: {intent}\n"
        f"Language: {lang}\n"
        f"Criteria: {criteria}"
    )).strip()

    agent.current_session["expected"] = expected
    agent.current_session["retries"]  = 0
    print(f"[eval] expected: {expected[:80]}", file=sys.stderr)


def evaluate_and_retry(agent) -> None:
    """
    on_complete — evaluate output against expected.
    If FAIL or PARTIAL: inject correction prompt and re-run up to MAX_RETRIES.
    Stores final verdict in session["evaluation"].
    """
    expected = agent.current_session.get("expected", "")
    if not expected:
        return

    messages = agent.current_session.get("messages", [])
    actual   = _get_last_assistant(messages)
    if not actual:
        print("[eval] no output to evaluate", file=sys.stderr)
        return

    verdict, reason = _judge(expected, actual)
    retries = agent.current_session.get("retries", 0)

    icon = "✓" if verdict == "PASS" else ("~" if verdict == "PARTIAL" else "✗")
    print(f"[eval] {icon} {verdict} — {reason}", file=sys.stderr)

    if verdict == "PASS" or retries >= MAX_RETRIES:
        agent.current_session["evaluation"] = f"{verdict} — {reason}"
        if retries > 0:
            print(f"[eval] completed after {retries} retries", file=sys.stderr)
        return

    # ── Retry with correction prompt ───────────────────────────────────────────
    retries += 1
    agent.current_session["retries"] = retries
    print(f"[eval] retrying ({retries}/{MAX_RETRIES}) — {reason}", file=sys.stderr)

    correction_prompt = (
        f"Your previous output had an issue: {reason}\n\n"
        f"Previous output:\n{actual}\n\n"
        f"Expected criteria: {expected}\n\n"
        "Please fix the output and return the corrected version only. "
        "No explanation, no preamble."
    )

    agent.current_session["messages"].append({
        "role":    "user",
        "content": correction_prompt,
    })

    # Re-run the agent — on_complete will fire again with the new output
    corrected = str(agent.input(correction_prompt)).strip().strip('"').strip("'")

    # Update last assistant message with corrected output
    for msg in reversed(agent.current_session.get("messages", [])):
        if msg.get("role") == "assistant":
            msg["content"] = corrected
            break