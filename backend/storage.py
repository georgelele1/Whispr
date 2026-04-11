"""
storage.py — Shared storage helpers for Whispr backend.

All modules import from here instead of duplicating load/save logic.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"

SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"


# =========================================================
# Paths
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


# =========================================================
# JSON read/write
# =========================================================

def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_store(filename: str, default: Any) -> Any:
    return _read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    _write_json(storage_path(filename), data)


# =========================================================
# Profile
# =========================================================

def _default_profile() -> Dict[str, Any]:
    return {
        # ── User habits (set during onboarding) ───────────
        "career_area":   "",    # e.g. "Software / Tech", "Medicine"
        "usage_type":    [],    # e.g. ["Draft an email", "Code comments"]
        "writing_style": "",    # "casual" | "formal" | "technical"
        "onboarding_done": False,

        # ── Text insertion shortcuts ───────────────────────
        "text_insertions": [],  # [{"label": "Work email", "value": "me@co.com"}]

        # ── App preferences ────────────────────────────────
        "preferences": {"target_language": DEFAULT_LANGUAGE},

        # ── AI-learned context (auto-updated from history) ─
        "learned": {
            "description":      "",   # free-text summary written by LLM
            "habits":           [],   # recurring phrases / topics noticed
            "frequent_apps":    [],   # apps seen most often in transcriptions
            "last_updated":     0,
        },
    }


def load_profile() -> Dict[str, Any]:
    stored = load_store(PROFILE_FILE, _default_profile())
    # Back-fill any keys added after first install so old profiles stay valid
    defaults = _default_profile()
    changed  = False
    for key, val in defaults.items():
        if key not in stored:
            stored[key] = val
            changed = True
    if changed:
        save_store(PROFILE_FILE, stored)
    return stored


def save_profile(profile: Dict[str, Any]) -> None:
    save_store(PROFILE_FILE, profile)


def get_target_language() -> str:
    lang = load_profile().get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_target_language(language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["target_language"] = language
    save_profile(profile)
    return True


# =========================================================
# Dictionary
# =========================================================

def load_dictionary() -> Dict[str, Any]:
    return load_store(DICTIONARY_FILE, {"terms": []})


def apply_dictionary_corrections(text: str) -> str:
    """Regex-based dictionary correction — 0ms, no LLM."""
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
                result = re.sub(
                    rf"\b{re.escape(alias)}\b", phrase, result, flags=re.IGNORECASE
                )
    return result


# =========================================================
# History
# =========================================================

def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, {"items": []})


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data  = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)

# =========================================================
# Text insertions — saved auto-fill values
# =========================================================

def load_text_insertions() -> list:
    return load_profile().get("text_insertions", [])


def save_text_insertion(label: str, value: str) -> bool:
    label = str(label or "").strip()
    value = str(value or "").strip()
    if not label or not value:
        return False
    profile = load_profile()
    insertions = profile.setdefault("text_insertions", [])
    for item in insertions:
        if item.get("label", "").lower() == label.lower():
            item["value"] = value
            save_profile(profile)
            return True
    insertions.append({"label": label, "value": value})
    save_profile(profile)
    return True


def remove_text_insertion(label: str) -> bool:
    label = str(label or "").strip()
    profile = load_profile()
    before = len(profile.get("text_insertions", []))
    profile["text_insertions"] = [
        i for i in profile.get("text_insertions", [])
        if i.get("label", "").lower() != label.lower()
    ]
    if len(profile["text_insertions"]) < before:
        save_profile(profile)
        return True
    return False