from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from connectonion.address import load
from connectonion import Agent, host, transcribe

BASE_DIR = Path(__file__).resolve().parent
CO_DIR   = BASE_DIR / ".co"
APP_NAME = "Whispr"

PROFILE_FILE    = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE    = "history.json"

# ── Self-correction ───────────────────────────────────────
SCORE_THRESHOLD = 70
MAX_RETRIES     = 3

# ── Dictionary auto-update ────────────────────────────────
DICTIONARY_UPDATE_INTERVAL = 60 * 60 * 24  # 24 hours

# ── Supported output languages ────────────────────────────
SUPPORTED_LANGUAGES = [
    "English", "Chinese", "Spanish", "French",
    "Japanese", "Korean", "Arabic", "German", "Portuguese",
]
DEFAULT_LANGUAGE = "English"


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
        "name": "",
        "email": "",
        "organization": "",
        "role": "",
        "preferences": {
            "target_language": DEFAULT_LANGUAGE,
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
    data  = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    save_store(HISTORY_FILE, data)


def get_target_language() -> str:
    """Read the user's preferred output language from their profile."""
    profile = load_profile()
    lang = profile.get("preferences", {}).get("target_language", DEFAULT_LANGUAGE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_target_language(language: str) -> bool:
    """Save the user's preferred output language to their profile."""
    if language not in SUPPORTED_LANGUAGES:
        return False
    profile = load_profile()
    profile.setdefault("preferences", {})["target_language"] = language
    save_profile(profile)
    return True


# =========================================================
# Common helpers
# =========================================================

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

    raise RuntimeError("Cannot register tool: unknown connectonion tool API.")


# =========================================================
# Dictionary corrections
# =========================================================

def apply_dictionary_corrections(text: str) -> str:
    """Apply approved dictionary aliases as regex replacements."""
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
                    rf"\b{re.escape(alias)}\b",
                    phrase,
                    result,
                    flags=re.IGNORECASE,
                )
    return result


# =========================================================
# Dictionary auto-update helpers
# =========================================================

def should_update_dictionary() -> bool:
    """True if 24h have passed since the last dictionary update."""
    path = storage_path("dictionary_last_update.json")
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (time.time() - data.get("last_update", 0)) > DICTIONARY_UPDATE_INTERVAL
    except Exception:
        return True


def mark_dictionary_updated() -> None:
    storage_path("dictionary_last_update.json").write_text(
        json.dumps({"last_update": time.time()}), encoding="utf-8"
    )


def get_new_history_since_last_update() -> List[Dict[str, Any]]:
    """Return only history items recorded after the last dictionary update."""
    path = storage_path("dictionary_last_update.json")
    last_ts = 0.0
    if path.exists():
        try:
            last_ts = json.loads(path.read_text(encoding="utf-8")).get("last_update", 0.0)
        except Exception:
            pass

    return [
        item for item in load_history().get("items", [])
        if item.get("ts", 0) / 1000 > last_ts   # ts stored in ms
    ]


def get_optimal_sample_size(items: List[Any]) -> int:
    """Scale sample size relative to number of new items."""
    total = len(items)
    if total == 0:   return 0
    if total < 20:   return total
    if total < 100:  return max(20, total // 3)
    return max(40, total // 5)


def deduplicate_items(texts: List[str], threshold: int = 10) -> List[str]:
    """Remove near-duplicates using a word-count fingerprint."""
    seen, unique = set(), []
    for text in texts:
        fp = " ".join(text.lower().split()[:threshold])
        if fp not in seen:
            seen.add(fp)
            unique.append(text)
    return unique


def prepare_items_for_agent(items: List[Dict[str, Any]]) -> List[str]:
    """Strip all fields except final_text and deduplicate — saves ~60% tokens."""
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items
        if str(item.get("final_text", "")).strip()
    ]
    return deduplicate_items(texts)


# =========================================================
# AI refine  (includes translation)
# =========================================================

def ai_refine_text(
    text: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    """Refine transcribed text with optional translation.

    - Detects the language automatically.
    - Translates to target_language if the input differs.
    - Removes disfluencies, fixes punctuation/grammar.
    - Adapts tone to the active application.

    Always passing app_name (even as "unknown") halves latency
    compared to omitting it entirely.
    """
    if not text.strip():
        return text

    # Resolve language: argument > profile preference > default
    lang = target_language.strip()
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = get_target_language()

    app_hint = (
        f"The user is currently using {app_name.strip()}."
        if app_name.strip()
        else "The active application is unknown."
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_text_refiner",
        system_prompt=(
            "You are Whispr's text refinement agent.\n"
            f"{app_hint} "
            "Use that to infer appropriate tone, formality, and context "
            "(e.g. code-safe for an IDE, professional for email, casual for chat).\n\n"
            "Your job — in order:\n"
            "1. Detect the language of the input.\n"
            f"2. If it is NOT {lang}, translate it to {lang}.\n"
            "3. Remove false starts, repeated fragments, stutters, and disfluencies.\n"
            "4. Fix punctuation, capitalisation, grammar, and readability.\n"
            "5. Match tone to the application context.\n\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT change meaning.\n"
            "- Output ONLY the final refined text — nothing else."
        ),
    )

    return clean_agent_output(agent.input(
        f"Input text:\n{text}\n\n"
        f"Output only the final refined {lang} text."
    ))


# =========================================================
# Self-correction
# =========================================================

def self_correct_text(
    raw_text: str,
    initial_refined: str,
    app_name: str = "",
    target_language: str = "",
) -> str:
    """Evaluate and iteratively correct refined text.

    If eval score < SCORE_THRESHOLD, feeds the failure reason back into
    a correction agent and retries up to MAX_RETRIES times.
    Always returns the highest-scoring attempt.
    """
    try:
        from Eval_run import run_refinement_eval
    except ImportError:
        return initial_refined   # eval not available — skip silently

    current    = initial_refined
    best_text  = initial_refined
    best_score = 0

    for attempt in range(MAX_RETRIES):
        results = run_refinement_eval([{
            "raw_text":  raw_text,
            "final_text": current,
            "app_name":  app_name,
        }], verbose=False)

        if not results:
            break

        score  = results[0]["score"]
        reason = results[0]["reason"]

        if score > best_score:
            best_score = score
            best_text  = current

        print(f"[self-correct] attempt {attempt + 1}  score={score}/100", file=sys.stderr)

        if score >= SCORE_THRESHOLD:
            break

        print(f"[self-correct] below threshold — retrying", file=sys.stderr)

        lang = target_language.strip() or get_target_language()

        agent = Agent(
            model="gpt-5",
            name="whispr_self_corrector",
            system_prompt=(
                "You are Whispr's self-correction agent. "
                "You receive a previous refinement attempt and the reason it failed. "
                f"Fix the identified issues and output ONLY the corrected {lang} text. "
                "Do NOT add facts or change meaning."
            ),
        )
        current = clean_agent_output(agent.input(
            f"App context: {app_name or 'unknown'}\n\n"
            f"Original raw text:\n{raw_text}\n\n"
            f"Previous attempt:\n{current}\n\n"
            f"Evaluation feedback:\n{reason}\n\n"
            f"Output only the corrected text."
        ))

    return best_text


# =========================================================
# Transcribe helper
# =========================================================

def transcribe_audio(audio_path: str) -> str:
    return str(transcribe(audio_path)).strip()


# =========================================================
# Core pipeline
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    """Full pipeline: transcribe → refine+translate → self-correct → dict → snippets."""
    audio_path = str(Path(audio_path).expanduser())

    if not Path(audio_path).exists():
        return {"ok": False, "error": f"audio file not found: {audio_path}", "ts": now_ms()}

    raw_text = transcribe_audio(audio_path)

    # Always pass app_name (even "unknown") — halves refine latency
    effective_app = app_name.strip() or "unknown"

    try:
        # 1. Refine + translate
        initial_refined = ai_refine_text(
            text=raw_text,
            app_name=effective_app,
            target_language=target_language,
        )

        # 2. Self-correct if eval available
        corrected = self_correct_text(
            raw_text=raw_text,
            initial_refined=initial_refined,
            app_name=effective_app,
            target_language=target_language,
        )

        # 3. Dictionary corrections
        dict_corrected = apply_dictionary_corrections(corrected)

        # 4. Snippet expansion
        from snippets import apply_snippets
        final_text = apply_snippets(dict_corrected)

    except Exception as exc:
        print(f"[pipeline] error — falling back to raw: {exc}", file=sys.stderr)
        final_text = apply_dictionary_corrections(raw_text)

    append_history({
        "ts":              now_ms(),
        "audio_path":      audio_path,
        "raw_text":        raw_text,
        "final_text":      final_text,
        "app_name":        effective_app,
        "target_language": target_language or get_target_language(),
    })

    return {"ok": True, "raw_text": raw_text, "final_text": final_text, "ts": now_ms()}


# =========================================================
# Tool functions
# =========================================================

def create_or_update_profile(
    name: str = "",
    email: str = "",
    organization: str = "",
    role: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    """Update user profile fields. Pass target_language to change output language."""
    profile = load_profile()

    for key, value in {
        "name": name, "email": email,
        "organization": organization, "role": role,
    }.items():
        if str(value).strip():
            profile[key] = str(value).strip()

    if target_language.strip() in SUPPORTED_LANGUAGES:
        profile.setdefault("preferences", {})["target_language"] = target_language.strip()

    save_profile(profile)
    return {"ok": True, "profile": profile}


def get_profile() -> Dict[str, Any]:
    return {"ok": True, "profile": load_profile()}


def transcribe_and_enhance(
    audio_path: str,
    app_name: str = "",
    target_language: str = "",
) -> Dict[str, Any]:
    return transcribe_and_enhance_impl(
        audio_path=audio_path,
        app_name=app_name,
        target_language=target_language,
    )


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription, text refinement, "
            "and translation. You can update the user profile to change preferences "
            "such as the output language."
        ),
    )
    for fn in (create_or_update_profile, get_profile, transcribe_and_enhance):
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

        command = sys.argv[2]

        # ── transcribe ───────────────────────────────────
        if command == "transcribe":
            audio_path      = sys.argv[3] if len(sys.argv) > 3 else ""
            app_name        = sys.argv[4] if len(sys.argv) > 4 else "unknown"
            target_language = sys.argv[5] if len(sys.argv) > 5 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)
            print(f"TARGET LANGUAGE: {target_language or get_target_language()}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── calendar ─────────────────────────────────────
        elif command == "calendar":
            import getpass
            text    = sys.argv[3] if len(sys.argv) > 3 else "today"
            user_id = sys.argv[4] if len(sys.argv) > 4 else getpass.getuser()

            try:
                from gcalendar import get_schedule, extract_calendar_intent
                intent   = extract_calendar_intent(text)
                date     = intent.get("date", "today")
                cal_filt = intent.get("calendar", "all")
                schedule = get_schedule(date=date, user_id=user_id, calendar_filter=cal_filt)
                print(json.dumps({"output": schedule}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # ── set-language ──────────────────────────────────
        elif command == "set-language":
            language = sys.argv[3] if len(sys.argv) > 3 else ""
            ok = set_target_language(language)
            print(json.dumps({
                "ok": ok,
                "language": language,
                "error": f"unsupported language: {language}" if not ok else None,
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0 if ok else 1)

        # ── get-language ──────────────────────────────────
        elif command == "get-language":
            print(json.dumps({
                "ok": True,
                "language": get_target_language(),
                "supported": SUPPORTED_LANGUAGES,
            }, ensure_ascii=False))
            sys.exit(0)

        # ── legacy: direct audio path as argv[2] ─────────
        else:
            audio_path      = sys.argv[2]
            app_name        = sys.argv[3] if len(sys.argv) > 3 else "unknown"
            target_language = sys.argv[4] if len(sys.argv) > 4 else ""

            print(f"PYTHON RECEIVED PATH: {audio_path}", file=sys.stderr)
            print(f"FILE EXISTS: {os.path.exists(audio_path)}", file=sys.stderr)

            try:
                result = transcribe_and_enhance_impl(
                    audio_path=audio_path,
                    app_name=app_name,
                    target_language=target_language,
                )
                print(json.dumps({"output": result.get("final_text", "")}, ensure_ascii=False))
                sys.exit(0)
            except Exception as e:
                print(json.dumps({"output": ""}))
                print(f"ERROR: {str(e)}", file=sys.stderr)
                sys.exit(1)

    else:
        addr = load(CO_DIR)
        host(
            create_agent,
            relay_url=None,
            whitelist=[addr["address"]],
            blacklist=[],
        )