"""
Structured Whispr agent loop: classify, route, execute, validate, return.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict

from connectonion import Agent

from agents import calendar_agent, knowledge_agent
from agents.plugins.eval import evaluate_output
from agents.refiner import run as run_refiner
from storage import get_agent_model, get_target_language


VALID_INTENTS = {"refine", "calendar", "knowledge"}


@dataclass
class RouteDecision:
    intent: str = "refine"
    need_tool: bool = False
    tool_name: str = ""
    query: str = ""
    start_iso: str = ""
    end_iso: str = ""
    confidence: float = 0.0
    reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteDecision":
        intent = str(data.get("intent", "refine")).strip().lower()
        if intent not in VALID_INTENTS:
            intent = "refine"

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        return cls(
            intent=intent,
            need_tool=bool(data.get("need_tool", intent != "refine")),
            tool_name=str(data.get("tool_name", "")).strip(),
            query=str(data.get("query", "")).strip(),
            start_iso=str(data.get("start_iso", "")).strip(),
            end_iso=str(data.get("end_iso", "")).strip(),
            confidence=max(0.0, min(confidence, 1.0)),
            reason=str(data.get("reason", "")).strip(),
        )


def _day_range(day_offset: int = 0) -> tuple[str, str]:
    day = datetime.now() + timedelta(days=day_offset)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(timespec="minutes"), (
        start + timedelta(days=1)
    ).isoformat(timespec="minutes")


def _rule_route(text: str) -> RouteDecision | None:
    lowered = str(text or "").strip().lower()

    calendar_terms = (
        "calendar", "schedule", "appointment", "agenda", "meeting",
        "日历", "日程", "行程", "安排", "会议", "会议安排", "有什么会",
    )
    calendar_actions = (
        "check", "show", "find", "what", "查", "看", "告诉", "列出", "查询",
        "什么", "有没有",
    )
    if any(term in lowered for term in calendar_terms) and any(
        action in lowered for action in calendar_actions
    ):
        offset = 0
        if "tomorrow" in lowered or "明天" in lowered:
            offset = 1
        elif "yesterday" in lowered or "昨天" in lowered:
            offset = -1
        start, end = _day_range(offset)
        return RouteDecision(
            intent="calendar",
            need_tool=True,
            tool_name="query_calendar_events",
            query=text,
            start_iso=start,
            end_iso=end,
            confidence=0.98,
            reason="Matched an explicit calendar query.",
        )

    knowledge_terms = (
        "knowledge base", "local knowledge", "internal document", "research paper",
        "文献", "论文", "知识库", "专业资料", "内部资料", "项目资料", "研究数据",
    )
    knowledge_actions = (
        "search", "find", "look up", "according to", "查", "检索", "搜索", "根据",
    )
    if any(term in lowered for term in knowledge_terms) and any(
        action in lowered for action in knowledge_actions
    ):
        return RouteDecision(
            intent="knowledge",
            need_tool=True,
            tool_name="search_knowledge",
            query=text,
            confidence=0.96,
            reason="Matched an explicit local knowledge query.",
        )

    return None


def _extract_json(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip().strip("`").strip()
    if text.lower().startswith("json"):
        text = text[4:].strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def classify(text: str, app_name: str = "unknown") -> RouteDecision:
    rule_decision = _rule_route(text)
    if rule_decision:
        return rule_decision

    now = datetime.now().astimezone().isoformat(timespec="minutes")
    router = Agent(
        model=get_agent_model(),
        name="whispr_intent_router",
        system_prompt=(
            "Classify a voice transcription request into exactly one intent:\n"
            "- refine: dictation cleanup, rewriting, translation, email, code, notes, "
            "or any request that does not require external data.\n"
            "- calendar: reading or searching the user's macOS Calendar.\n"
            "- knowledge: searching the user's local professional documents, papers, "
            "project files, or internal knowledge base.\n\n"
            "Use calendar or knowledge only when the user clearly asks to retrieve data. "
            "Return ONLY valid JSON with these fields:\n"
            '{"intent":"refine|calendar|knowledge","need_tool":false,'
            '"tool_name":"","query":"","start_iso":"","end_iso":"",'
            '"confidence":0.0,"reason":""}\n'
            "For calendar, resolve the requested local time range to ISO datetimes. "
            "For knowledge, put a concise retrieval query in query."
        ),
    )

    try:
        raw = router.input(
            f"Current local datetime: {now}\n"
            f"Active app: {app_name}\n"
            f"User input: {text}"
        )
    except Exception as exc:
        return RouteDecision(reason=f"Router failed; using refiner: {exc}")
    data = _extract_json(str(raw))
    if not data:
        return RouteDecision(reason="Router output was invalid; using refiner.")

    decision = RouteDecision.from_dict(data)
    if decision.confidence < 0.65:
        return RouteDecision(
            confidence=decision.confidence,
            reason="Router confidence was low; using refiner.",
        )
    return decision


def _validate_output(output: str, fallback_text: str, app_name: str) -> str:
    output = str(output or "").strip()
    if output:
        return output
    return run_refiner(fallback_text, app_name)


def run(text: str, app_name: str = "unknown") -> Dict[str, Any]:
    decision = classify(text, app_name)

    if decision.intent == "calendar":
        output = calendar_agent.run(
            user_text=text,
            start_iso=decision.start_iso,
            end_iso=decision.end_iso,
            search_text=decision.query if decision.query != text else "",
        )
    elif decision.intent == "knowledge":
        output = knowledge_agent.run(text, decision.query)
    else:
        output = run_refiner(text, app_name)

    output = _validate_output(output, text, app_name)
    evaluation = evaluate_output(text, output, decision.intent)

    return {
        "output": output,
        "route": asdict(decision),
        "evaluation": evaluation,
        "target_language": get_target_language(),
    }
