"""
agents/plugins/appname.py — Active app context injection.

Injects the active frontend app name into the refiner agent as system context.
This helps the agent decide whether to format as email, chat, terminal command,
code, notes, or general prose.
"""

from __future__ import annotations


def inject_app(agent) -> None:
    app_name = str(
        agent.current_session.get("whispr_app_name", "unknown")
    ).strip() or "unknown"

    agent.current_session["messages"].append({
        "role": "system",
        "content": (
            f"Active application: {app_name}.\n"
            "Use this app context together with the user's intent to decide the best output format. "
            "Do not rely on a fixed app list. Reason from the app name and the content."
        ),
    })