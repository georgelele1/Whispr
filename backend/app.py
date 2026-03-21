from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host, transcribe

BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"

ALLOWED_MODES = {"off", "clean", "formal", "chat", "concise", "meeting", "email", "code"}
ALLOWED_CONTEXTS = {"generic", "email", "chat", "code"}

# =========================================================
# Paths / storage
# =========================================================

def app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME
    else:
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def storage_path(filename: str) -> Path:
    return app_support_dir() / filename


def now_ms() -> int:
    return int(time.time() * 1000)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    write_json(storage_path(filename), data)

# =========================================================
# Defaults
# =========================================================

def default_profile() -> Dict[str, Any]:
    return {
        "name": "Yanbo",
        "email": "z5603812@unsw.edu.au",
        "organization": "UNSW",
        "role": "Student",
        "preferences": {
            "default_mode": "formal",
            "default_context": "generic",
        },
    }


def default_dictionary() -> Dict[str, Any]:
    return {"terms": []}


def default_history() -> Dict[str, Any]:
    return {"items": []}


def load_profile() -> Dict[str, Any]:
    return load_store(PROFILE_FILE, default_profile())


def save_profile(profile: Dict[str, Any]) -> None:
    save_store(PROFILE_FILE, profile)


def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, default_dictionary())


def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, default_history())


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)

# =========================================================
# Common helpers
# =========================================================

def normalize_mode_context(mode: str = "clean", context: str = "generic") -> tuple[str, str]:
    mode = str(mode or "clean").strip().lower()
    context = str(context or "generic").strip().lower()

    if mode not in ALLOWED_MODES:
        mode = "clean"
    if context not in ALLOWED_CONTEXTS:
        context = "generic"

    implied_context = {
        "email": "email",
        "chat": "chat",
        "code": "code",
    }
    if context == "generic" and mode in implied_context:
        context = implied_context[mode]

    return mode, context


def clean_agent_output(result: Any) -> str:
    return str(result).strip().strip('"').strip("'").strip()


def register_tool(agent: Agent, fn: Callable[..., Any]) -> None:
    if hasattr(agent, "add_tools") and callable(getattr(agent, "add_tools")):
        agent.add_tools(fn)
        return
    if hasattr(agent, "add_tool") and callable(getattr(agent, "add_tool")):
        agent.add_tool(fn)
        return

    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return

    raise RuntimeError("Cannot register tool: unknown connectonion tool API in this install.")

# =========================================================
# Dictionary corrections
# =========================================================

def apply_dictionary_corrections(text: str) -> str:
    if not text.strip():
        return text

    result = text
    for item in load_dictionary().get("terms", []):
        if not item.get("approved", True):
            continue

        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue

        for alias in item.get("aliases", []):
            alias = str(alias).strip()
            if alias:
                result = re.sub(rf"\b{re.escape(alias)}\b", phrase, result, flags=re.IGNORECASE)

    return result

# =========================================================
# Instructions
# =========================================================

def get_refine_instruction(mode: str) -> str:
    mode = str(mode or "clean").strip().lower()

    instructions = {
        "off": "Do not modify the transcript.",
        "clean": (
            "Remove false starts, repeated fragments, stutters, and obvious spoken disfluencies. "
            "Then improve punctuation, capitalization, grammar, and readability while staying close to the original wording."
        ),
        "formal": (
            "Remove false starts, repeated fragments, self-corrections, and spoken disfluencies. "
            "Then rewrite in a polished, professional, and grammatically correct style."
        ),
        "chat": (
            "Remove obvious false starts and repeated fragments, but keep the text natural and conversational. "
            "Then improve readability lightly without making it sound stiff."
        ),
        "concise": (
            "Remove false starts, repeated fragments, filler, and verbose spoken phrasing. "
            "Then make the text shorter, clearer, and more direct while preserving meaning."
        ),
        "meeting": (
            "Remove spoken disfluencies and improve structure so the text is easier to use for meeting notes or meeting follow-up."
        ),
        "email": (
            "Remove spoken disfluencies and shape the text into a clean, professional email-ready form."
        ),
        "code": (
            "Remove spoken disfluencies, but preserve technical terms, code snippets, commands, file paths, variable names, "
            "product names, and version strings exactly. Improve readability without corrupting technical content."
        ),
    }

    return instructions.get(mode, instructions["clean"])


def get_context_instruction(context: str) -> str:
    context = str(context or "generic").strip().lower()

    instructions = {
        "generic": "Use a neutral style suitable for general everyday text.",
        "email": "Make the text suitable for email communication.",
        "chat": "Make the text suitable for instant messaging or casual chat.",
        "code": "Be careful with technical terms, code syntax, commands, file paths, and variable names.",
    }

    return instructions.get(context, instructions["generic"])

# =========================================================
# AI refine
# =========================================================

def ai_refine_text(text: str, context: str = "generic", mode: str = "clean") -> str:
    if not text.strip():
        return text

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are Whispr's text refinement agent.\n"
            "Your job is to first correct false starts, repeated fragments, self-corrections, "
            "stutters, filler-like spoken artifacts, and broken spoken structures.\n"
            "Then improve punctuation, capitalization, grammar, clarity, and readability.\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT change meaning.\n"
            "- For code mode, preserve commands, code snippets, file paths, variable names, versions, and product names exactly.\n"
            "- Output ONLY the final refined text.\n"
        )
    )

    instruction = f"""
Context: {context}
Mode: {mode}

Context instruction:
{get_context_instruction(context)}

Refinement instruction:
{get_refine_instruction(mode)}

Input text:
{text}

Task:
First remove backtracking, false starts, repeated fragments, self-corrections, stutters, and spoken disfluencies where appropriate.
Then refine the text according to the requested mode and context.
Do not add new facts.
Output only the final refined text.
""".strip()

    return clean_agent_output(agent.input(instruction))

# =========================================================
# Core
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    mode: str = "clean",
    context: str = "generic",
    prompt: str = "",
) -> Dict[str, Any]:
    mode, context = normalize_mode_context(mode, context)
    audio_path = str(Path(audio_path).expanduser())

    if not Path(audio_path).exists():
        return {
            "ok": False,
            "error": f"audio file not found: {audio_path}",
            "ts": now_ms(),
        }

    raw = transcribe(audio_path, prompt=prompt) if prompt else transcribe(audio_path)
    raw_text = str(raw).strip()

    if mode == "off":
        final_text = apply_dictionary_corrections(raw_text)
    else:
        try:
            final_text = apply_dictionary_corrections(
                ai_refine_text(text=raw_text, context=context, mode=mode)
            )
        except Exception:
            final_text = apply_dictionary_corrections(raw_text)

    append_history({
        "ts": now_ms(),
        "audio_path": audio_path,
        "raw_text": raw_text,
        "final_text": final_text,
        "context": context,
        "mode": mode,
    })

    return {
        "ok": True,
        "raw_text": raw_text,
        "final_text": final_text,
        "ts": now_ms(),
    }

# =========================================================
# Tool functions
# =========================================================

def create_or_update_profile(
    name: str = "",
    email: str = "",
    organization: str = "",
    role: str = "",
    default_mode: str = "clean",
    default_context: str = "generic",
) -> Dict[str, Any]:
    profile = load_profile()

    for key, value in {
        "name": name,
        "email": email,
        "organization": organization,
        "role": role,
    }.items():
        if str(value).strip():
            profile[key] = str(value).strip()

    mode, context = normalize_mode_context(default_mode, default_context)
    profile["preferences"] = {
        "default_mode": mode,
        "default_context": context,
    }

    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def get_supported_options() -> Dict[str, Any]:
    return {
        "ok": True,
        "modes": sorted(ALLOWED_MODES),
        "contexts": sorted(ALLOWED_CONTEXTS),
    }


def transcribe_and_enhance(
    audio_path: str,
    mode: str = "clean",
    context: str = "generic",
    prompt: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        mode=mode,
        context=context,
        prompt=prompt,
    )

# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription and text refinement."
        ),
    )

    for fn in (
        create_or_update_profile,
        get_profile,
        transcribe_and_enhance,
        get_supported_options,
    ):
        register_tool(agent, fn)

    return agent

# =========================================================
# CLI / host
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        if len(sys.argv) < 3:
            print(json.dumps({"output": ""}, ensure_ascii=False))
            sys.exit(1)

        audio_path = sys.argv[2]
        mode = sys.argv[3] if len(sys.argv) > 3 else "clean"
        context = sys.argv[4] if len(sys.argv) > 4 else "generic"
        prompt = sys.argv[5] if len(sys.argv) > 5 else ""

        print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
        print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

        try:
            result = transcribe_and_enhance_impl(
                audio_path=audio_path,
                mode=mode,
                context=context,
                prompt=prompt,
            )

            print(json.dumps({
                "output": result.get("final_text", "")
            }, ensure_ascii=False))
            sys.exit(0)

        except Exception as e:
            print(json.dumps({
                "output": ""
            }, ensure_ascii=False))
            print(f"ERROR: {str(e)}", file=sys.stderr)
            sys.exit(1)

    else:
        addr = load(CO_DIR)
        my_agent_address = addr["address"]

        host(
            create_agent,
            relay_url=None,
            whitelist=[my_agent_address],
            blacklist=[],
        )