from __future__ import annotations

import base64
import json
from pathlib import Path

from connectonion import Agent


AUDIO_FILE = Path("Test.wav")  # change this to your real audio file


def try_agent_with_file_path(agent: Agent, audio_path: Path) -> None:
    print("\n=== TEST 1: pass file path as plain text ===")
    prompt = f"""
You are testing whether you can accept an audio file path.

Audio file path:
{audio_path.resolve()}

Task:
1. Tell me whether you can directly read/transcribe this audio file by yourself.
2. If yes, transcribe it.
3. If no, clearly say you cannot access local files directly.

Return plain text only.
""".strip()

    try:
        result = agent.input(prompt)
        print("RESULT:")
        print(str(result))
    except Exception as e:
        print("ERROR:", repr(e))


def try_agent_with_base64(agent: Agent, audio_path: Path) -> None:
    print("\n=== TEST 2: pass audio bytes as base64 in prompt ===")
    try:
        audio_bytes = audio_path.read_bytes()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as e:
        print("ERROR reading file:", repr(e))
        return

    prompt = f"""
You are testing whether you can process audio content passed in text form.

The following is a base64-encoded WAV audio file:
{audio_b64[:12000]}

Task:
1. Tell me whether you are able to decode and transcribe this audio from base64 content.
2. If yes, transcribe it.
3. If no, clearly say you cannot process it this way.

Return plain text only.
""".strip()

    try:
        result = agent.input(prompt)
        print("RESULT:")
        print(str(result))
    except Exception as e:
        print("ERROR:", repr(e))


def try_agent_with_structured_payload(agent: Agent, audio_path: Path) -> None:
    print("\n=== TEST 3: pass structured payload ===")
    payload = {
        "task": "transcribe_audio",
        "file": {
            "path": str(audio_path.resolve()),
            "name": audio_path.name,
            "suffix": audio_path.suffix,
            "exists": audio_path.exists(),
        },
        "instruction": (
            "Check whether you can directly access this local audio file. "
            "If yes, transcribe it. If not, say clearly that local file access is unavailable."
        ),
    }

    try:
        result = agent.input(json.dumps(payload, ensure_ascii=False, indent=2))
        print("RESULT:")
        print(str(result))
    except Exception as e:
        print("ERROR:", repr(e))


def main() -> None:
    if not AUDIO_FILE.exists():
        print(f"Audio file not found: {AUDIO_FILE.resolve()}")
        return

    agent = Agent(
        model="gpt-5",
        name="audio_input_probe",
        system_prompt=(
            "You are a capability test agent. "
            "Be honest about whether you can directly access or transcribe provided audio files."
        ),
    )

    print("Using audio file:", AUDIO_FILE.resolve())
    try_agent_with_file_path(agent, AUDIO_FILE)
    try_agent_with_base64(agent, AUDIO_FILE)
    try_agent_with_structured_payload(agent, AUDIO_FILE)


if __name__ == "__main__":
    main()