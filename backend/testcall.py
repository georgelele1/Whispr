import json
import uuid
import requests
from pathlib import Path

from connectonion.address import load
from connectonion.network.connect import RemoteAgent

HTTP_BASE = "http://127.0.0.1:8000"

# Load the REAL signing key + address from .co
addr = load(Path(".co"))
keys = {
    "address": addr["address"],
    "signing_key": addr["signing_key"],
}

# Use RemoteAgent only to build a correctly signed message
ra = RemoteAgent(HTTP_BASE, keys=keys)

payload = {
    "tool": "transcribe_and_enhance",
    "args": {
        "audio_path": "./Test.wav",  # <-- Changed to a simple, local path
        "mode": "formal",
        "context": "chat",
        "prompt": "You are Whispr. Improve the transcript.\n"
                    "Rules:\n"
                    "- Do NOT add new facts.\n"
                    "- Do NOT change meaning.\n"
                    "- Fix punctuation, capitalization, and grammar.\n"
                    "- Remove filler words (um/uh/like/you know), stutters, and repeated fragments.\n"
                    "- Resolve false starts and self-corrections (keep only the corrected version).\n"
                    "- Output ONLY the final improved text. No quotes. No commentary."
    }
}

# Generate a unique ID for every run to bypass replay protection
unique_id = f"local-test-{uuid.uuid4()}"

# Build the signed input message using the UNIQUE ID
msg = ra._build_input_message(json.dumps(payload), input_id=unique_id, is_direct=True)

resp = requests.post(f"{HTTP_BASE}/input", json=msg, timeout=300)

print("STATUS:", resp.status_code)
print(resp.text)