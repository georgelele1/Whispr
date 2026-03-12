from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host, transcribe

APP_NAME = "Whispr"

# =========================================================
# Local storage
# =========================================================

PROFILE_FILE = "profile.json"
DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"
ALLOWED_MODES = {"off", "clean", "formal", "chat", "concise", "meeting", "email", "code"}
ALLOWED_CONTEXTS = {"generic", "email", "chat", "code"}

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


def profile_path() -> Path:
    return app_support_dir() / PROFILE_FILE


def dictionary_path() -> Path:
    return app_support_dir() / DICTIONARY_FILE


def history_path() -> Path:
    return app_support_dir() / HISTORY_FILE


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


# =========================================================
# Default data
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
    return {
        "terms": []
    }


def default_history() -> Dict[str, Any]:
    return {
        "items": []
    }


# =========================================================
# Load / Save helpers
# =========================================================

def load_profile() -> Dict[str, Any]:
    return read_json(profile_path(), default_profile())


def save_profile(profile: Dict[str, Any]) -> None:
    write_json(profile_path(), profile)


def load_dictionary() -> Dict[str, Any]:
    return read_json(dictionary_path(), default_dictionary())


def save_dictionary(data: Dict[str, Any]) -> None:
    write_json(dictionary_path(), data)


def load_history() -> Dict[str, Any]:
    return read_json(history_path(), default_history())


def append_history(item: Dict[str, Any], max_items: int = 200) -> None:
    data = load_history()
    items = data.get("items", [])
    items.append(item)
    data["items"] = items[-max_items:]
    write_json(history_path(), data)


# =========================================================
# Tool registration helper
# =========================================================

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
# Dictionary utilities
# =========================================================

STOPWORDS = {
    "the", "and", "for", "are", "this", "that", "with", "have", "from",
    "you", "your", "was", "were", "will", "can", "not", "but", "they",
    "about", "just", "into", "then", "than", "when", "what", "where",
    "how", "why", "our", "their", "his", "her", "she", "him", "them",
    "hello", "okay", "yeah", "like", "um", "uh", "so", "well", "i",
    "we", "he", "it", "is", "am", "be", "to", "of", "in", "on", "at",
    "a", "an", "or", "if", "as", "by", "do", "did", "does", "done",
    "me", "my", "mine", "ours", "yours", "theirs", "please", "thanks",
    "thank", "today", "tomorrow", "yesterday", "also", "really", "very"
}


def add_or_update_dictionary_entry(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
    source: str = "user",
    confidence: float = 1.0,
    approved: bool = True,
) -> Dict[str, Any]:
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases: List[str] = []
    for a in aliases or []:
        a = str(a).strip()
        if a and a.lower() != phrase.lower():
            clean_aliases.append(a)

    data = load_dictionary()
    terms = data.get("terms", [])

    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            old_aliases = set(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
            old_aliases.update(clean_aliases)
            item["aliases"] = sorted(old_aliases)
            item["type"] = entry_type or item.get("type", "custom")
            item["source"] = source or item.get("source", "user")
            item["confidence"] = max(float(item.get("confidence", 0.0)), float(confidence))
            item["approved"] = bool(approved)
            save_dictionary(data)
            return {"ok": True, "updated": True, "entry": item}

    entry = {
        "phrase": phrase,
        "aliases": sorted(set(clean_aliases)),
        "type": entry_type or "custom",
        "source": source or "user",
        "confidence": float(confidence),
        "approved": bool(approved),
    }
    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)
    return {"ok": True, "updated": False, "entry": entry}


def apply_dictionary_corrections(text: str) -> str:
    if not text.strip():
        return text

    data = load_dictionary()
    result = text

    for item in data.get("terms", []):
        if not item.get("approved", True):
            continue

        phrase = str(item.get("phrase", "")).strip()
        aliases = item.get("aliases", [])

        if not phrase:
            continue

        for alias in aliases:
            alias = str(alias).strip()
            if not alias:
                continue

            pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
            result = pattern.sub(phrase, result)

    return result


def build_dictionary_prompt(user_prompt: str = "", max_terms: int = 50) -> str:
    profile = load_profile()
    dictionary = load_dictionary()

    hints: List[str] = []

    for key in ("name", "organization", "role"):
        v = str(profile.get(key, "")).strip()
        if v:
            hints.append(v)

    for item in dictionary.get("terms", []):
        if not item.get("approved", True):
            continue
        phrase = str(item.get("phrase", "")).strip()
        if phrase:
            hints.append(phrase)

    deduped = list(dict.fromkeys(hints))[:max_terms]

    parts: List[str] = []
    if deduped:
        parts.append("Please pay attention to these names and domain-specific terms:")
        parts.append(", ".join(deduped))

    if str(user_prompt).strip():
        parts.append(str(user_prompt).strip())

    return "\n".join(parts).strip()


def build_dictionary_context(max_terms: int = 50) -> str:
    data = load_dictionary()
    terms = data.get("terms", [])

    lines: List[str] = []
    for item in terms[:max_terms]:
        if not item.get("approved", True):
            continue

        phrase = str(item.get("phrase", "")).strip()
        aliases = [str(a).strip() for a in item.get("aliases", []) if str(a).strip()]
        entry_type = str(item.get("type", "custom")).strip()

        if not phrase:
            continue

        if aliases:
            lines.append(f"- {phrase} (type: {entry_type}; aliases: {', '.join(aliases)})")
        else:
            lines.append(f"- {phrase} (type: {entry_type})")

    if not lines:
        return "Personal dictionary: none"

    return "Personal dictionary:\n" + "\n".join(lines)


# =========================================================
# Candidate extraction from recent 10 texts
# =========================================================

def get_recent_texts(limit: int = 10) -> List[str]:
    history = load_history()
    items = history.get("items", [])
    texts: List[str] = []

    for item in items[-limit:]:
        txt = str(item.get("final_text", "")).strip()
        if txt:
            texts.append(txt)

    return texts


def get_candidate_source_texts(current_raw_text: str, limit: int = 10) -> List[str]:
    texts = get_recent_texts(limit=max(0, limit - 1))
    current_raw_text = str(current_raw_text or "").strip()
    if current_raw_text:
        texts.append(current_raw_text)
    return texts[-limit:]


def tokenize_candidate_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9\-_]{2,}", text)


def looks_like_domain_term(word: str) -> bool:
    if any(c.isdigit() for c in word):
        return True
    if "-" in word or "_" in word:
        return True
    if word[:1].isupper():
        return True
    if sum(1 for c in word if c.isupper()) >= 2:
        return True
    return False


def collect_candidate_terms_from_recent_texts(
    texts: List[str],
    min_count: int = 2,
) -> List[Dict[str, Any]]:
    dictionary = load_dictionary()

    existing_phrases = {
        str(item.get("phrase", "")).lower()
        for item in dictionary.get("terms", [])
    }
    existing_aliases = {
        str(alias).lower()
        for item in dictionary.get("terms", [])
        for alias in item.get("aliases", [])
    }

    counter = Counter()
    original_forms: Dict[str, str] = {}
    support_score: Dict[str, int] = {}

    for text in texts:
        seen_in_this_text = set()
        words = tokenize_candidate_words(text)
        for w in words:
            lw = w.lower()

            if lw in STOPWORDS:
                continue
            if lw in existing_phrases or lw in existing_aliases:
                continue
            if len(w) < 3:
                continue
            if w.isdigit():
                continue

            counter[lw] += 1
            original_forms.setdefault(lw, w)

            if lw not in seen_in_this_text:
                support_score[lw] = support_score.get(lw, 0) + 1
                seen_in_this_text.add(lw)

    candidates: List[Dict[str, Any]] = []
    for lw, count in counter.items():
        if count < min_count:
            continue

        phrase = original_forms[lw]
        candidates.append({
            "phrase": phrase,
            "count": count,
            "support_texts": support_score.get(lw, 1),
            "domain_like": looks_like_domain_term(phrase),
        })

    candidates.sort(
        key=lambda x: (
            not x["domain_like"],
            -x["support_texts"],
            -x["count"],
            x["phrase"].lower(),
        )
    )
    return candidates


def extract_dictionary_candidates_with_agent(
    texts: List[str],
    pre_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not texts:
        return []

    joined_text = "\n".join(texts[-10:])
    candidate_hint = ", ".join(item["phrase"] for item in pre_candidates[:50])

    dictionary_agent = Agent(
        model="co/gpt-5",
        name="whispr_dictionary_builder",
        system_prompt=(
            "You extract personal dictionary candidates from recent transcripts.\n"
            "Return ONLY valid JSON in this format:\n"
            "{\"terms\": ["
            "{\"phrase\": \"...\", \"aliases\": [\"...\"], \"type\": \"technical\", \"confidence\": 0.9}"
            "]}\n"
            "Rules:\n"
            "- Do not invent facts.\n"
            "- Use only evidence from the transcript texts.\n"
            "- Prefer terms supported by repeated usage across recent texts.\n"
            "- Avoid common English words.\n"
            "- Prefer names, products, project names, organizations, and technical terms.\n"
            "- Output valid JSON only."
        )
    )

    prompt = f"""
Recent transcript texts:
{joined_text}

Pre-filtered repeated candidate words:
{candidate_hint}

Extract only useful personal dictionary terms.
""".strip()

    result = str(dictionary_agent.input(prompt)).strip()

    try:
        data = json.loads(result)
        terms = data.get("terms", [])
        return terms if isinstance(terms, list) else []
    except Exception:
        return []


def normalize_candidate_term(item: Dict[str, Any]) -> Dict[str, Any] | None:
    phrase = str(item.get("phrase", "")).strip()
    aliases = item.get("aliases", [])
    entry_type = str(item.get("type", "custom")).strip().lower()
    confidence = float(item.get("confidence", 0.0))

    if not phrase or len(phrase) < 3:
        return None
    if confidence < 0.75:
        return None
    if phrase.lower() in STOPWORDS:
        return None

    clean_aliases: List[str] = []
    if isinstance(aliases, list):
        for a in aliases:
            a = str(a).strip()
            if a and a.lower() != phrase.lower():
                clean_aliases.append(a)

    return {
        "phrase": phrase,
        "aliases": sorted(set(clean_aliases)),
        "type": entry_type or "custom",
        "source": "agent",
        "confidence": confidence,
        "approved": True,
    }


def merge_agent_terms_into_dictionary(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    data = load_dictionary()
    terms = data.get("terms", [])
    existing = {str(t.get("phrase", "")).lower(): t for t in terms}

    added: List[str] = []
    updated: List[str] = []

    for raw in candidates:
        item = normalize_candidate_term(raw)
        if not item:
            continue

        key = item["phrase"].lower()
        if key in existing:
            old = existing[key]
            merged_aliases = set(str(x).strip() for x in old.get("aliases", []) if str(x).strip())
            merged_aliases.update(item.get("aliases", []))
            old["aliases"] = sorted(merged_aliases)
            old["confidence"] = max(float(old.get("confidence", 0.0)), float(item["confidence"]))
            if old.get("type") in {"", "custom"} and item.get("type"):
                old["type"] = item["type"]
            old["approved"] = True
            updated.append(old["phrase"])
        else:
            terms.append(item)
            existing[key] = item
            added.append(item["phrase"])

    data["terms"] = terms
    save_dictionary(data)

    return {
        "ok": True,
        "added": added,
        "updated": updated,
        "total_terms": len(terms),
    }


def auto_update_dictionary_from_recent_texts(current_raw_text: str) -> Dict[str, Any]:
    texts = get_candidate_source_texts(current_raw_text=current_raw_text, limit=10)

    pre_candidates = collect_candidate_terms_from_recent_texts(
        texts=texts,
        min_count=2,
    )

    agent_candidates = extract_dictionary_candidates_with_agent(
        texts=texts,
        pre_candidates=pre_candidates,
    )

    merged = merge_agent_terms_into_dictionary(agent_candidates)

    return {
        "ok": True,
        "source_text_count": len(texts),
        "pre_candidates": pre_candidates[:20],
        "dictionary_update": merged,
    }


# =========================================================
# AI stages
# =========================================================

def ai_backtrace_correct(text: str, context: str = "generic", mode: str = "clean") -> str:
    if not text.strip():
        return text

    dictionary_context = build_dictionary_context()

    agent = Agent(
        model="co/gpt-5",
        name="whispr_backtrace_corrector",
        system_prompt=(
            "You are Whispr's backtrace correction agent.\n"
            "Your job is to correct false starts, repeated fragments, self-corrections, "
            "stutters, and broken spoken structures.\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT remove meaning.\n"
            "- Preserve the intended message.\n"
            "- Preserve personal dictionary terms exactly.\n"
            "- Output ONLY the corrected text.\n"
        )
    )

    instruction = f"""
Context: {context}
Mode: {mode}

{dictionary_context}

Input transcript:
{text}

Task:
Correct backtracking, false starts, repetitions, and self-corrections.
Keep personal dictionary terms exactly as specified.
Output only the corrected text.
""".strip()

    result = str(agent.input(instruction)).strip()
    return result.strip().strip('"').strip("'").strip()


def ai_enhance_text(text: str, context: str = "generic", mode: str = "clean") -> str:
    if not text.strip():
        return text

    dictionary_context = build_dictionary_context()

    agent = Agent(
        model="co/gpt-5",
        name="whispr_text_enhancer",
        system_prompt=(
            "You are Whispr's text enhancement agent.\n"
            "Improve punctuation, capitalization, grammar, and readability.\n"
            "Adapt style based on context.\n"
            "Rules:\n"
            "- Do NOT add new facts.\n"
            "- Do NOT change meaning.\n"
            "- Preserve personal dictionary terms exactly.\n"
            "- Output ONLY the final enhanced text.\n"
        )
    )

    instruction = f"""
Context: {context}
Enhancement level: {mode}

{dictionary_context}

Input text:
{text}

Task:
Enhance the text for clarity and readability.
Keep dictionary phrases exactly as specified.
Output only the final enhanced text.
""".strip()

    result = str(agent.input(instruction)).strip()
    return result.strip().strip('"').strip("'").strip()


# =========================================================
# Core reusable implementation
# =========================================================

def transcribe_and_enhance_impl(
    audio_path: str,
    mode: str = "clean",
    context: str = "generic",
    prompt: str = "",
) -> Dict[str, Any]:
    mode = str(mode or "clean").strip().lower()
    context = str(context or "generic").strip().lower()

    if mode not in ALLOWED_MODES:
        mode = "clean"
    if context not in ALLOWED_CONTEXTS:
        context = "generic"

    audio_path = str(Path(audio_path).expanduser())

    if not Path(audio_path).exists():
        return {
            "ok": False,
            "error": f"audio file not found: {audio_path}",
            "ts": now_ms(),
        }

    stt_prompt = build_dictionary_prompt(prompt)

    if stt_prompt:
        raw = transcribe(audio_path, prompt=stt_prompt)
    else:
        raw = transcribe(audio_path)

    raw_text = str(raw).strip()

    dict_update_result = auto_update_dictionary_from_recent_texts(raw_text)
    normalized_text = apply_dictionary_corrections(raw_text)

    if mode == "off":
        backtrace_text = normalized_text
        final_text = normalized_text
    else:
        try:
            backtrace_text = ai_backtrace_correct(
                text=normalized_text,
                context=context,
                mode=mode,
            )
        except Exception:
            backtrace_text = normalized_text

        backtrace_text = apply_dictionary_corrections(backtrace_text)

        try:
            final_text = ai_enhance_text(
                text=backtrace_text,
                context=context,
                mode=mode,
            )
        except Exception:
            final_text = backtrace_text

        final_text = apply_dictionary_corrections(final_text)

    append_history({
        "ts": now_ms(),
        "audio_path": audio_path,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "backtrace_text": backtrace_text,
        "final_text": final_text,
        "context": context,
        "mode": mode,
    })

    return {
        "ok": True,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "backtrace_text": backtrace_text,
        "final_text": final_text,
        "dictionary_update": dict_update_result,
        "ts": now_ms(),
    }


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="co/gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcription, adaptive personal dictionary "
            "updates, backtrace correction, and text enhancement."
        ),
    )

    def create_or_update_profile(
        name: str = "",
        email: str = "",
        organization: str = "",
        role: str = "",
        default_mode: str = "clean",
        default_context: str = "generic",
    ) -> Dict[str, Any]:
        profile = load_profile()

        if str(name).strip():
            profile["name"] = str(name).strip()
        if str(email).strip():
            profile["email"] = str(email).strip()
        if str(organization).strip():
            profile["organization"] = str(organization).strip()
        if str(role).strip():
            profile["role"] = str(role).strip()

        mode = str(default_mode or "clean").strip().lower()
        context = str(default_context or "generic").strip().lower()

        if mode not in {"off", "clean", "formal"}:
            mode = "clean"
        if context not in {"generic", "email", "chat", "code"}:
            context = "generic"

        profile["preferences"] = {
            "default_mode": mode,
            "default_context": context,
        }

        save_profile(profile)
        return {"ok": True, "profile": profile}

    def get_profile() -> Dict[str, Any]:
        return {"ok": True, "profile": load_profile()}

    def add_dictionary_word(
        phrase: str,
        aliases: List[str] | None = None,
        entry_type: str = "custom",
    ) -> Dict[str, Any]:
        return add_or_update_dictionary_entry(
            phrase=phrase,
            aliases=aliases,
            entry_type=entry_type,
            source="user",
            confidence=1.0,
            approved=True,
        )

    def list_dictionary_words() -> Dict[str, Any]:
        return {"ok": True, "dictionary": load_dictionary()}

    def scan_dictionary_candidates(current_text: str = "") -> Dict[str, Any]:
        return auto_update_dictionary_from_recent_texts(current_text)

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

    register_tool(agent, create_or_update_profile)
    register_tool(agent, get_profile)
    register_tool(agent, add_dictionary_word)
    register_tool(agent, list_dictionary_words)
    register_tool(agent, scan_dictionary_candidates)
    register_tool(agent, transcribe_and_enhance)

    return agent


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        if len(sys.argv) < 3:
            print(json.dumps({
                "ok": False,
                "error": "usage: python app.py cli <audio_path> [mode] [context] [prompt]"
            }, ensure_ascii=False))
            sys.exit(1)

        audio_path = sys.argv[2]
        mode = sys.argv[3] if len(sys.argv) > 3 else "clean"
        context = sys.argv[4] if len(sys.argv) > 4 else "generic"
        prompt = sys.argv[5] if len(sys.argv) > 5 else ""

        try:
            result = transcribe_and_enhance_impl(
                audio_path=audio_path,
                mode=mode,
                context=context,
                prompt=prompt,
            )
            print(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({
                "ok": False,
                "error": str(e),
                "ts": now_ms(),
            }, ensure_ascii=False))
            sys.exit(1)

    else:
        addr = load(Path(".co"))
        my_agent_address = addr["address"]

        host(
            create_agent,
            relay_url=None,
            whitelist=[my_agent_address],
            blacklist=[],
        )