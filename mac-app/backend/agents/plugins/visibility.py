"""
agents/plugins/visibility.py

Debug-only visibility summary.
Only prints when WHISPR_DEBUG_LOGS=1.
"""
from __future__ import annotations

import sys
import time

from storage import DEBUG_LOGS


def show_summary(agent) -> None:
    if not DEBUG_LOGS:
        return

    session = agent.current_session
    tool_calls = session.get("tool_call_count", 0)
    start = session.get("start_time", 0)
    end = session.get("end_time", time.time())

    duration = int((end - start) * 1000) if start else 0

    parts = [f"agent={agent.name}"]

    if duration:
        parts.append(f"{duration}ms")

    if tool_calls:
        parts.append(f"{tool_calls} tool calls")

    print(f"[visibility] {' | '.join(parts)}", file=sys.stderr)