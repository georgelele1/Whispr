"""
Low-cost output evaluation.

Default path is deterministic and uses no model calls. Set WHISPR_DEBUG_EVAL=1
to add one LLM judge call for diagnostics.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from connectonion import Agent

from storage import DEBUG_EVAL, get_agent_model


def _local_evaluate(
    user_text: str,
    output: str,
    intent: str,
) -> Dict[str, Any]:
    output = str(output or "").strip()
    if not output:
        return {"verdict": "FAIL", "reason": "Output is empty.", "method": "local"}

    if len(output) > 12000:
        return {
            "verdict": "PARTIAL",
            "reason": "Output exceeds the safety length limit.",
            "method": "local",
        }

    if intent == "refine":
        fillers = re.findall(
            r"\b(uh+|um+|basically|you know)\b",
            output,
            flags=re.IGNORECASE,
        )
        if fillers:
            return {
                "verdict": "PARTIAL",
                "reason": "Unexpected filler words remain.",
                "method": "local",
            }

    return {"verdict": "PASS", "reason": "", "method": "local"}


def _llm_evaluate(
    user_text: str,
    output: str,
    intent: str,
) -> Dict[str, Any]:
    judge = Agent(
        model=get_agent_model(),
        name="whispr_eval_judge",
        system_prompt=(
            "Check whether the output fulfills the input without inventing facts. "
            "Reply exactly PASS, PARTIAL, or FAIL followed by one short reason."
        ),
    )
    raw = str(judge.input(
        f"Intent: {intent}\nInput: {user_text[:600]}\nOutput: {output[:1200]}"
    )).strip()
    upper = raw.upper()
    verdict = (
        "PASS" if upper.startswith("PASS")
        else "PARTIAL" if upper.startswith("PARTIAL")
        else "FAIL"
    )
    return {
        "verdict": verdict,
        "reason": raw[len(verdict):].strip(" -:"),
        "method": "llm",
    }


def evaluate_output(
    user_text: str,
    output: str,
    intent: str,
) -> Dict[str, Any]:
    result = _local_evaluate(user_text, output, intent)
    if DEBUG_EVAL and result["verdict"] == "PASS":
        try:
            return _llm_evaluate(user_text, output, intent)
        except Exception as exc:
            result["debug_error"] = str(exc)
    return result
