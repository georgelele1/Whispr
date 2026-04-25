"""
storage.py — Shared storage helpers for Whispr backend.

Supports:
- Profile storage
- Dictionary storage
- History storage
- Output language
- Multi-provider model registry
- API key storage for OpenAI / Anthropic / other providers
- Atomic JSON writes
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

APP_NAME = "Whispr"

PROFILE_FILE = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"
ENV_FILE = ".env"

SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]

DEFAULT_LANGUAGE = "English"

DEBUG_EVAL = os.environ.get("WHISPR_DEBUG_EVAL") == "1"
DEBUG_LOGS = os.environ.get("WHISPR_DEBUG_LOGS") == "1"


# =========================================================
# Provider / Model registry
# Keep this aligned with frontend Config.providers
# =========================================================

PROVIDER_OPTIONS: List[Dict[str, Any]] = [
    {
        "id": "google",
        "label": "Google",
        "free": True,
        "env_key": "",
        "key_prefixes": ["AIza"],
        "models": [
            {
                "id": "co/gemini-3-flash-preview",
                "label": "Gemini 3 Flash",
            },
            {
                "id": "co/gemini-3-pro-preview",
                "label": "Gemini 3 Pro",
            },
            {
                "id": "co/gemini-2.5-flash",
                "label": "Gemini 2.5 Flash",
            },
        ],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "free": False,
        "env_key": "OPENAI_API_KEY",
        "key_prefixes": ["sk-"],
        "models": [
            {
                "id": "gpt-5.4",
                "label": "GPT-5.4 Fast",
            },
            {
                "id": "gpt-5",
                "label": "GPT-5 Powerful",
            },
            {
                "id": "gpt-4o",
                "label": "GPT-4o Efficient",
            },
        ],
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "free": False,
        "env_key": "ANTHROPIC_API_KEY",
        "key_prefixes": ["sk-ant-"],
        "models": [
            {
                "id": "claude-sonnet-4-5",
                "label": "Claude Sonnet 4.5",
            },
            {
                "id": "claude-opus-4-1",
                "label": "Claude Opus 4.1",
            },
            {
                "id": "claude-haiku-4-5",
                "label": "Claude Haiku 4.5",
            },
        ],
    },
]

MODEL_OPTIONS: List[Dict[str, str]] = []

for provider in PROVIDER_OPTIONS:
    for model in provider["models"]:
        MODEL_OPTIONS.append({
            "id": model["id"],
            "label": model["label"],
            "provider": provider["id"],
            "provider_label": provider["label"],
        })

SUPPORTED_MODELS: List[str] = [m["id"] for m in MODEL_OPTIONS]

DEFAULT_MODEL = "co/gemini-3-flash-preview"


def get_provider_config(provider_id: str) -> Dict[str, Any] | None:
    for provider in PROVIDER_OPTIONS:
        if provider["id"] == provider_id:
            return provider
    return None


def get_provider_for_model(model: str) -> str:
    for item in MODEL_OPTIONS:
        if item["id"] == model:
            return item["provider"]
    return "google"


def get_model_options() -> List[Dict[str, str]]:
    return MODEL_OPTIONS


def get_provider_options() -> List[Dict[str, Any]]:
    return PROVIDER_OPTIONS


def get_model() -> str:
    model = load_profile().get("preferences", {}).get("model", DEFAULT_MODEL)
    return model if model in SUPPORTED_MODELS else DEFAULT_MODEL


def set_model(model: str) -> bool:
    if model not in SUPPORTED_MODELS:
        return False

    profile = load_profile()
    profile.setdefault("preferences", {})["model"] = model
    save_profile(profile)
    return True


def get_agent_model() -> str:
    return get_model()


def requires_api_key(model: str | None = None) -> bool:
    model = model or get_model()
    provider_id = get_provider_for_model(model)
    provider = get_provider_config(provider_id)

    if not provider:
        return False

    return not bool(provider.get("free", False))


def required_api_key_name(model: str | None = None) -> str:
    model = model or get_model()
    provider_id = get_provider_for_model(model)
    provider = get_provider_config(provider_id)

    if not provider:
        return ""

    return str(provider.get("env_key", ""))


def detect_provider_for_key(key: str) -> str | None:
    key = str(key or "").strip()

    for provider in PROVIDER_OPTIONS:
        for prefix in provider.get("key_prefixes", []):
            if key.startswith(prefix):
                return provider["id"]

    return None


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
    """
    Atomic JSON write.
    Prevents corrupted JSON if app exits during write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def load_store(filename: str, default: Any) -> Any:
    return _read_json(storage_path(filename), default)


def save_store(filename: str, data: Any) -> None:
    _write_json(storage_path(filename), data)


# =========================================================
# Env / API keys
# =========================================================

def _env_path() -> Path:
    return app_support_dir() / ENV_FILE


def _bundled_env_path() -> Path:
    return Path(__file__).resolve().parent / ENV_FILE


def _load_env() -> Dict[str, str]:
    path = _env_path()

    if not path.exists():
        return {}

    result: Dict[str, str] = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()

    return result


def _save_env(data: Dict[str, str]) -> None:
    path = _env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclude empty keys and values that could corrupt the .env file
    lines = [f"{k}={v}" for k, v in data.items() if k and v]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_env_into_os() -> None:
    """
    Priority:
    1. Bundled .env
    2. App Support .env
    3. Existing os.environ wins
    """
    merged: Dict[str, str] = {}

    bundled = _bundled_env_path()

    if bundled.exists():
        for line in bundled.read_text(encoding="utf-8").splitlines():
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, _, value = line.partition("=")
            merged[key.strip()] = value.strip()

    for key, value in _load_env().items():
        merged[key] = value

    for key, value in merged.items():
        if key not in os.environ:
            os.environ[key] = value


def _provider_env_key(provider: str) -> str:
    config = get_provider_config(provider)

    if config and config.get("env_key"):
        return str(config["env_key"])

    return f"{provider.upper()}_API_KEY"


def get_api_key(provider: str = "openai") -> str:
    env_key = _provider_env_key(provider)
    return os.environ.get(env_key) or _load_env().get(env_key, "")


def set_api_key(key: str, provider: str = "openai") -> bool:
    key = str(key or "").strip()
    if not key:
        return False
    try:
        env_key = _provider_env_key(provider)
        if not env_key:
            return False
        data = _load_env()
        data[env_key] = key
        _save_env(data)
        os.environ[env_key] = key
        return True
    except Exception:
        return False


def remove_api_key(provider: str = "openai") -> bool:
    env_key = _provider_env_key(provider)
    data = _load_env()

    if env_key not in data:
        os.environ.pop(env_key, None)
        return False

    del data[env_key]
    _save_env(data)
    os.environ.pop(env_key, None)

    return True


def has_api_key(provider: str = "openai") -> bool:
    return bool(get_api_key(provider))


def list_stored_providers() -> List[str]:
    found: List[str] = []

    for provider in PROVIDER_OPTIONS:
        provider_id = provider["id"]

        if provider.get("free", False):
            found.append(provider_id)
        elif has_api_key(provider_id):
            found.append(provider_id)

    return found


# =========================================================
# Profile
# =========================================================

def _default_profile() -> Dict[str, Any]:
    return {
        "name": "",
        "email": "",
        "organization": "",
        "role": "",
        "career_area": "",
        "usage_type": [],
        "writing_style": "",
        "onboarding_done": False,
        "text_insertions": [],
        "preferences": {
            "target_language": DEFAULT_LANGUAGE,
            "model": DEFAULT_MODEL,
        },
        "learned": {
            "description": "",
            "habits": [],
            "frequent_apps": [],
            "last_updated": 0,
        },
    }


def load_profile() -> Dict[str, Any]:
    stored = load_store(PROFILE_FILE, _default_profile())
    defaults = _default_profile()
    changed = False

    for key, value in defaults.items():
        if key not in stored:
            stored[key] = value
            changed = True

    stored.setdefault("preferences", {})
    stored.setdefault("learned", {})

    if "target_language" not in stored["preferences"]:
        stored["preferences"]["target_language"] = DEFAULT_LANGUAGE
        changed = True

    if "model" not in stored["preferences"]:
        stored["preferences"]["model"] = DEFAULT_MODEL
        changed = True

    if stored["preferences"].get("model") not in SUPPORTED_MODELS:
        stored["preferences"]["model"] = DEFAULT_MODEL
        changed = True

    if stored["preferences"].get("target_language") not in SUPPORTED_LANGUAGES:
        stored["preferences"]["target_language"] = DEFAULT_LANGUAGE
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


def save_dictionary(data: Dict[str, Any]) -> None:
    save_store(DICTIONARY_FILE, data)


def apply_dictionary_corrections(text: str) -> str:
    if not str(text or "").strip():
        return text

    result = text

    for item in load_dictionary().get("terms", []):
        if not item.get("approved", True):
            continue

        phrase = str(item.get("phrase", "")).strip()

        if not phrase:
            continue

        aliases = item.get("aliases", [])

        for alias in aliases:
            alias = str(alias).strip()

            if not alias:
                continue

            result = re.sub(
                rf"\b{re.escape(alias)}\b",
                phrase,
                result,
                flags=re.IGNORECASE,
            )

    return result


# =========================================================
# History
# =========================================================

def load_history() -> Dict[str, Any]:
    return load_store(HISTORY_FILE, {"items": []})


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data = load_history()
    items = data.get("items", [])

    items.append(item)
    data["items"] = items[-max_items:]

    save_store(HISTORY_FILE, data)


def clear_history() -> None:
    save_store(HISTORY_FILE, {"items": []})


# =========================================================
# Text insertions
# =========================================================

def load_text_insertions() -> List[Dict[str, str]]:
    return load_profile().get("text_insertions", [])


def save_text_insertion(label: str, value: str) -> bool:
    label = str(label or "").strip()
    value = str(value or "").strip()

    if not label or not value:
        return False

    profile = load_profile()
    insertions = profile.setdefault("text_insertions", [])

    for item in insertions:
        if str(item.get("label", "")).lower() == label.lower():
            item["value"] = value
            save_profile(profile)
            return True

    insertions.append({
        "label": label,
        "value": value,
    })

    save_profile(profile)
    return True


def remove_text_insertion(label: str) -> bool:
    label = str(label or "").strip()

    if not label:
        return False

    profile = load_profile()
    before = len(profile.get("text_insertions", []))

    profile["text_insertions"] = [
        item for item in profile.get("text_insertions", [])
        if str(item.get("label", "")).lower() != label.lower()
    ]

    if len(profile["text_insertions"]) < before:
        save_profile(profile)
        return True

    return False


# =========================================================
# Reset helpers
# =========================================================

def reset_profile() -> None:
    save_profile(_default_profile())


def clear_dictionary() -> None:
    save_dictionary({"terms": []})


def reset_all_user_data() -> None:
    reset_profile()
    clear_dictionary()
    clear_history()