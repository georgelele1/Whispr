"""agents/plugins/language.py"""
from storage import get_target_language

def inject_language(agent) -> None:
    lang = get_target_language()
    agent.current_session["messages"].append({
        "role":    "system",
        "content": f"Your response MUST be in {lang}.",
    })