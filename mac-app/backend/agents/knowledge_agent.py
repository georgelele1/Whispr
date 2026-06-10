"""
Local knowledge retrieval and grounded answer generation.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from connectonion import Agent

from storage import app_support_dir, get_agent_model, get_target_language


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".pdf"}
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180
DEFAULT_TOP_K = 3
MAX_CONTEXT_CHARS = 4200

_INDEX_CACHE: Dict[str, Dict[str, Any]] = {}


def knowledge_dir() -> Path:
    override = str(os.environ.get("WHISPR_KNOWLEDGE_DIR", "")).strip()
    path = Path(override).expanduser() if override else app_support_dir() / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def knowledge_roots() -> List[Path]:
    roots = [knowledge_dir()]
    bundled = Path(__file__).resolve().parent.parent / "knowledge"
    if bundled.exists() and bundled.resolve() != roots[0].resolve():
        roots.append(bundled)
    return roots


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        return "\n".join(
            str(page.extract_text() or "")
            for page in PdfReader(str(path)).pages
        )
    except Exception:
        return ""


def _read_document(path: Path) -> str:
    try:
        if path.suffix.lower() == ".pdf":
            return _read_pdf(path)

        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(data, ensure_ascii=False, indent=2)

        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return "\n".join(
                    " | ".join(str(cell) for cell in row)
                    for row in csv.reader(handle)
                )

        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _chunks(text: str) -> Iterable[str]:
    text = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not text:
        return

    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        if end < len(text):
            boundary = max(
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
                text.rfind("。", start, end),
            )
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1

        yield text[start:end].strip()
        if end >= len(text):
            break
        start = max(start + 1, end - CHUNK_OVERLAP)


def _tokens(text: str) -> List[str]:
    lowered = str(text or "").lower()
    words = re.findall(r"[a-z0-9][a-z0-9_\-]{1,}|[\u4e00-\u9fff]", lowered)
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
    for phrase in chinese:
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return words


def _indexed_chunks(path: Path, root: Path) -> List[Dict[str, Any]]:
    cache_key = str(path.resolve())
    modified = path.stat().st_mtime_ns
    cached = _INDEX_CACHE.get(cache_key)

    if cached and cached.get("modified") == modified:
        return cached["chunks"]

    text = _read_document(path)
    chunks = [
        {
            "source": str(path.relative_to(root)),
            "chunk": index,
            "content": chunk,
            "tokens": Counter(_tokens(chunk)),
        }
        for index, chunk in enumerate(_chunks(text))
    ] if text else []

    _INDEX_CACHE[cache_key] = {
        "modified": modified,
        "chunks": chunks,
    }
    return chunks


def _score_tokens(query_tokens: Counter, document_tokens: Counter) -> float:
    if not query_tokens or not document_tokens:
        return 0.0

    overlap = sum(
        min(count, document_tokens.get(token, 0))
        for token, count in query_tokens.items()
    )
    norm = math.sqrt(sum(query_tokens.values()) * sum(document_tokens.values()))
    return overlap / norm if norm else 0.0


def search_knowledge(query: str, limit: int = DEFAULT_TOP_K) -> Dict[str, Any]:
    """Search files in Application Support/Whispr/knowledge."""
    query_tokens = Counter(_tokens(query))
    matches: List[Dict[str, Any]] = []
    scanned = 0

    roots = knowledge_roots()
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if path.name.lower() == "readme.md":
                continue

            scanned += 1
            for item in _indexed_chunks(path, root):
                score = _score_tokens(query_tokens, item["tokens"])
                if score <= 0:
                    continue
                matches.append({
                    "source": item["source"],
                    "chunk": item["chunk"],
                    "score": round(score, 6),
                    "content": item["content"],
                })

    matches.sort(key=lambda item: item["score"], reverse=True)
    selected = matches[:max(1, min(int(limit or 5), 10))]

    return {
        "ok": True,
        "query": query,
        "documents_scanned": scanned,
        "matches": selected,
        "count": len(selected),
        "knowledge_dir": str(knowledge_dir()),
        "knowledge_roots": [str(root) for root in roots],
    }


def run(user_text: str, query: str = "") -> str:
    retrieval = search_knowledge(query or user_text)

    if not retrieval["matches"]:
        return (
            "No relevant local knowledge was found. Add TXT, Markdown, JSON, CSV, "
            f"or PDF files to: {retrieval['knowledge_dir']}"
        )

    context_parts = []
    context_size = 0
    for item in retrieval["matches"]:
        part = f"[Source: {item['source']}]\n{item['content']}"
        remaining = MAX_CONTEXT_CHARS - context_size
        if remaining <= 0:
            break
        context_parts.append(part[:remaining])
        context_size += len(context_parts[-1])

    context = "\n\n".join(context_parts)

    agent = Agent(
        model=get_agent_model(),
        name="whispr_knowledge_agent",
        system_prompt=(
            "Answer the user's question using only the retrieved local knowledge. "
            "Do not invent facts that are absent from the sources. If the evidence is "
            "insufficient, state that limitation. Mention source filenames naturally "
            "when useful. "
            f"Respond in {get_target_language()}."
        ),
    )

    return str(agent.input(
        f"User question:\n{user_text}\n\nRetrieved knowledge:\n{context}"
    )).strip()
