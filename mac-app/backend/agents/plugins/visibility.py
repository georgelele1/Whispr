"""agents/plugins/visibility.py"""
import sys
import time

def show_summary(agent) -> None:
    session    = agent.current_session
    tool_calls = session.get("tool_call_count", 0)
    start      = session.get("start_time", 0)
    end        = session.get("end_time", time.time())
    duration   = int((end - start) * 1000) if start else 0
    parts = [f"agent={agent.name}"]
    if duration:
        parts.append(f"{duration}ms")
    if tool_calls:
        parts.append(f"{tool_calls} tool calls")
    print(f"[visibility] {' | '.join(parts)}", file=sys.stderr)