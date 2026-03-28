from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List

from connectonion.address import load
from connectonion import Agent, host

BASE_DIR = Path(__file__).resolve().parent
CO_DIR = BASE_DIR / ".co"
APP_NAME = "Whispr"

DICTIONARY_FILE = "dictionary.json"
HISTORY_FILE = "history.json"


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


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_dictionary() -> Dict[str, Any]:
    return read_json(storage_path(DICTIONARY_FILE), {"terms": []})


def save_dictionary(data: Dict[str, Any]) -> None:
    write_json(storage_path(DICTIONARY_FILE), data)


def load_history() -> Dict[str, Any]:
    return read_json(storage_path(HISTORY_FILE), {"items": []})


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
# Tool functions
# =========================================================

def get_recent_transcripts(limit: int = 20) -> Dict[str, Any]:
    """Return the most recent transcript texts from history for analysis."""
    items = load_history().get("items", [])
    texts = [
        str(item.get("final_text", "")).strip()
        for item in items[-limit:]
        if str(item.get("final_text", "")).strip()
    ]
    return {"ok": True, "texts": texts, "count": len(texts)}


def get_dictionary() -> Dict[str, Any]:
    """Return the current personal dictionary."""
    return {"ok": True, "dictionary": load_dictionary()}


def add_or_update_term(
    phrase: str,
    aliases: List[str] | None = None,
    entry_type: str = "custom",
    confidence: float = 1.0,
) -> Dict[str, Any]:
    """Add a new term or update an existing one in the personal dictionary."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    clean_aliases = sorted({
        str(a).strip()
        for a in (aliases or [])
        if str(a).strip() and str(a).strip().lower() != phrase.lower()
    })

    data = load_dictionary()
    terms = data.get("terms", [])

    for item in terms:
        if str(item.get("phrase", "")).lower() == phrase.lower():
            merged = set(str(x).strip() for x in item.get("aliases", []) if str(x).strip())
            merged.update(clean_aliases)
            item["aliases"] = sorted(merged)
            item["type"] = entry_type or item.get("type", "custom")
            item["confidence"] = max(float(item.get("confidence", 0.0)), float(confidence))
            item["source"] = "agent"
            item["approved"] = True
            save_dictionary(data)
            return {"ok": True, "updated": True, "entry": item}

    entry = {
        "phrase": phrase,
        "aliases": clean_aliases,
        "type": entry_type or "custom",
        "source": "agent",
        "confidence": float(confidence),
        "approved": True,
    }
    terms.append(entry)
    data["terms"] = terms
    save_dictionary(data)
    return {"ok": True, "updated": False, "entry": entry}


def remove_term(phrase: str) -> Dict[str, Any]:
    """Remove a term from the personal dictionary."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    data = load_dictionary()
    terms = data.get("terms", [])
    filtered = [t for t in terms if str(t.get("phrase", "")).lower() != phrase.lower()]

    if len(filtered) == len(terms):
        return {"ok": False, "error": f"term not found: {phrase}"}

    data["terms"] = filtered
    save_dictionary(data)
    return {"ok": True, "removed": phrase, "total_terms": len(filtered)}


def approve_term(phrase: str, approved: bool = True) -> Dict[str, Any]:
    """Approve or disable a term in the personal dictionary."""
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "error": "phrase is required"}

    data = load_dictionary()
    for item in data.get("terms", []):
        if str(item.get("phrase", "")).lower() == phrase.lower():
            item["approved"] = bool(approved)
            save_dictionary(data)
            return {"ok": True, "phrase": phrase, "approved": item["approved"]}

    return {"ok": False, "error": f"term not found: {phrase}"}


# =========================================================
# Token-efficient batched update
# =========================================================

def run_batched_update(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Single agent call for all new items to minimise token usage.

    Instead of one agent call per item, sends all new final_text
    values in one batched prompt. Strips all other fields first.
    """
    from app import prepare_items_for_agent

    texts = prepare_items_for_agent(items)

    if not texts:
        return {"added": [], "updated": [], "total_terms": len(load_dictionary().get("terms", []))}

    # Join all texts into one prompt — one call instead of N calls
    combined = "\n---\n".join(texts)

    agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_batch_updater",
        system_prompt=(
            "You are a dictionary term extractor for a voice transcription app. "
            "Given a batch of transcribed texts separated by '---', identify "
            "domain-specific terms, proper nouns, technical words, product names, "
            "or project names that would benefit from being in a correction dictionary. "
            "Skip common everyday words. "
            "Return ONLY a JSON array of objects with keys: "
            "'phrase' (canonical correct form) and 'aliases' (list of common mishearings). "
            "Be concise. No explanation, no markdown, just the raw JSON array."
        )
    )

    result = agent.input(
        f"Batch of {len(texts)} transcribed texts:\n\n{combined}\n\n"
        f"Return JSON array of dictionary terms only."
    )

    try:
        new_terms = json.loads(str(result).strip())
        if not isinstance(new_terms, list):
            new_terms = []
    except Exception:
        new_terms = []

    # Merge into existing dictionary
    dictionary = load_dictionary()
    existing = {
        str(t.get("phrase", "")).lower(): t
        for t in dictionary.get("terms", [])
    }

    added = []
    updated = []

    for term in new_terms:
        phrase = str(term.get("phrase", "")).strip()
        if not phrase:
            continue

        aliases = [str(a).strip() for a in term.get("aliases", []) if str(a).strip()]

        if phrase.lower() in existing:
            existing_entry = existing[phrase.lower()]
            merged = set(existing_entry.get("aliases", [])) | set(aliases)
            existing_entry["aliases"] = sorted(merged)
            existing_entry["approved"] = True
            updated.append(existing_entry)
        else:
            entry = {
                "phrase": phrase,
                "aliases": sorted(aliases),
                "type": "custom",
                "source": "agent",
                "confidence": 1.0,
                "approved": True,
            }
            existing[phrase.lower()] = entry
            added.append(entry)

    dictionary["terms"] = list(existing.values())
    save_dictionary(dictionary)

    return {
        "added": added,
        "updated": updated,
        "total_terms": len(dictionary["terms"]),
    }


# =========================================================
# Agent factory
# =========================================================

def create_agent() -> Agent:
    agent = Agent(
        model="gpt-5",
        name="whispr_dictionary_agent",
        system_prompt=(
            "You are Whispr's personal dictionary agent.\n"
            "When asked to update the dictionary, use get_recent_transcripts to fetch recent "
            "transcript history, then analyse the texts for recurring names, technical terms, "
            "domain-specific phrases, and proper nouns that would benefit from being in the "
            "personal dictionary.\n"
            "Prioritise terms that:\n"
            "- Appear repeatedly across multiple transcripts\n"
            "- Are proper nouns, product names, project names, or organisation names\n"
            "- Are technical or domain-specific and unlikely to be transcribed correctly without a hint\n"
            "- Are not common everyday English words\n"
            "Use add_or_update_term to save each candidate. Set confidence based on how strongly "
            "the evidence supports the term. Include aliases for common mishearings or alternate "
            "spellings if evident from the transcripts.\n"
            "You can also add, remove, or approve individual terms when the user asks directly."
        ),
    )

    for fn in (
        get_recent_transcripts,
        get_dictionary,
        add_or_update_term,
        remove_term,
        approve_term,
    ):
        register_tool(agent, fn)

    return agent


# =========================================================
# CLI / host
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        command = sys.argv[2] if len(sys.argv) > 2 else "update"

        print(f"DICTIONARY AGENT CLI COMMAND: {command}", file=sys.stderr)

        try:
            if command == "update":
                from app import (
                    should_update_dictionary,
                    mark_dictionary_updated,
                    get_new_history_since_last_update,
                    get_optimal_sample_size,
                )

                # Time-based guard — skip if updated recently
                if not should_update_dictionary():
                    print(json.dumps({
                        "ok": True,
                        "skipped": True,
                        "reason": "updated recently",
                        "added": [],
                        "updated": [],
                        "total_terms": len(load_dictionary().get("terms", [])),
                    }, ensure_ascii=False))
                    sys.exit(0)

                # Get only new records since last update
                new_items = get_new_history_since_last_update()
                limit = get_optimal_sample_size(new_items)

                print(
                    f"New records since last update: {len(new_items)}, "
                    f"sampling: {limit}",
                    file=sys.stderr
                )

                if limit == 0:
                    print(json.dumps({
                        "ok": True,
                        "skipped": True,
                        "reason": "no new history since last update",
                        "added": [],
                        "updated": [],
                        "total_terms": len(load_dictionary().get("terms", [])),
                    }, ensure_ascii=False))
                    sys.exit(0)

                # Sample from new items only
                items_to_process = new_items[-limit:]

                # Run token-efficient batched update
                result = run_batched_update(items_to_process)

                # Mark update timestamp
                mark_dictionary_updated()

                print(json.dumps({
                    "ok": True,
                    "skipped": False,
                    "new_records_found": len(new_items),
                    "records_processed": len(items_to_process),
                    "added": result["added"],
                    "updated": result["updated"],
                    "total_terms": result["total_terms"],
                }, ensure_ascii=False))

            elif command == "list":
                result = get_dictionary()
                print(json.dumps({"output": result}, ensure_ascii=False))

            elif command == "add":
                phrase     = sys.argv[3] if len(sys.argv) > 3 else ""
                aliases    = sys.argv[4].split(",") if len(sys.argv) > 4 else []
                entry_type = sys.argv[5] if len(sys.argv) > 5 else "custom"
                result = add_or_update_term(phrase=phrase, aliases=aliases, entry_type=entry_type)
                print(json.dumps({"output": result}, ensure_ascii=False))

            elif command == "remove":
                phrase = sys.argv[3] if len(sys.argv) > 3 else ""
                result = remove_term(phrase=phrase)
                print(json.dumps({"output": result}, ensure_ascii=False))

            else:
                print(json.dumps({
                    "output": "",
                    "error": f"unknown command: {command}"
                }, ensure_ascii=False))

            sys.exit(0)

        except Exception as e:
            print(json.dumps({"output": "", "error": str(e)}, ensure_ascii=False))
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