"""
benchmark.py — Whispr component timing tests

Tests the running time of each component individually.
Does NOT require a real audio file for most tests — uses mock data
so the benchmark can run standalone.

Usage:
    python benchmark.py                  # run all tests
    python benchmark.py --component refine
    python benchmark.py --component dictionary
    python benchmark.py --component snippets
    python benchmark.py --component calendar
    python benchmark.py --component history
    python benchmark.py --component dedup
    python benchmark.py --audio path/to/file.wav   # include real transcription test
    python benchmark.py --save           # save results to benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# =========================================================
# Timer utility
# =========================================================

class Timer:
    """Context manager that measures elapsed time in ms."""

    def __init__(self, name: str):
        self.name    = name
        self.elapsed = 0.0
        self._start  = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed = (time.perf_counter() - self._start) * 1000  # ms


def run_timed(name: str, fn: Callable, *args, **kwargs) -> Dict[str, Any]:
    """Run fn(*args, **kwargs), measure time, catch errors."""
    print(f"  Running: {name} ...", end=" ", flush=True)
    t = Timer(name)
    error = None
    result = None

    try:
        with t:
            result = fn(*args, **kwargs)
        status = "PASS"
    except Exception as e:
        status = "FAIL"
        error  = str(e)

    ms = t.elapsed
    label = f"{ms:>8.1f} ms"

    if status == "PASS":
        print(f"{label}  ✓")
    else:
        print(f"{label}  ✗  ({error[:80]})")

    return {
        "component": name,
        "status":    status,
        "ms":        round(ms, 2),
        "error":     error,
    }


# =========================================================
# Mock data
# =========================================================

MOCK_RAW_TEXT = (
    "um so so basically I I wanted to say that uh "
    "the the meeting is scheduled for tomorrow at nine am "
    "and we should uh prepare the the slides beforehand"
)

MOCK_HISTORY_ITEMS = [
    {
        "ts":         int(time.time() * 1000) - i * 3600000,
        "raw_text":   f"uh so the Whispr project is coming along nicely iteration {i}",
        "final_text": f"The Whispr project is coming along nicely. Iteration {i}.",
        "app_name":   "Xcode" if i % 2 == 0 else "Mail",
    }
    for i in range(50)
]


# =========================================================
# Individual component tests
# =========================================================

def test_storage_read_write() -> List[Dict[str, Any]]:
    """Test JSON storage read/write speed."""
    print("\n── Storage ─────────────────────────────────────────")
    from app import load_history, load_dictionary, load_profile

    results = []
    results.append(run_timed("storage: load_history",    load_history))
    results.append(run_timed("storage: load_dictionary", load_dictionary))
    results.append(run_timed("storage: load_profile",    load_profile))
    return results


def test_dictionary_corrections() -> List[Dict[str, Any]]:
    """Test dictionary correction regex speed."""
    print("\n── Dictionary corrections ──────────────────────────")
    from app import apply_dictionary_corrections

    results = []
    results.append(run_timed(
        "dictionary: apply_corrections (short text)",
        apply_dictionary_corrections,
        MOCK_RAW_TEXT,
    ))
    results.append(run_timed(
        "dictionary: apply_corrections (long text)",
        apply_dictionary_corrections,
        MOCK_RAW_TEXT * 10,
    ))
    return results


def test_deduplication() -> List[Dict[str, Any]]:
    """Test deduplication and prepare_items_for_agent speed."""
    print("\n── Token optimisation ──────────────────────────────")
    from app import deduplicate_items, prepare_items_for_agent, get_optimal_sample_size

    texts_10  = [f"The Whispr project meeting is at nine am today number {i}" for i in range(10)]
    texts_100 = texts_10 * 10
    texts_500 = texts_10 * 50

    results = []
    results.append(run_timed("dedup: 10 items",               deduplicate_items, texts_10))
    results.append(run_timed("dedup: 100 items",              deduplicate_items, texts_100))
    results.append(run_timed("dedup: 500 items",              deduplicate_items, texts_500))
    results.append(run_timed("prepare_items_for_agent: 50",   prepare_items_for_agent, MOCK_HISTORY_ITEMS))
    results.append(run_timed("get_optimal_sample_size: 50",   get_optimal_sample_size, MOCK_HISTORY_ITEMS))
    results.append(run_timed("get_optimal_sample_size: 500",  get_optimal_sample_size, texts_500))
    return results


def test_history_helpers() -> List[Dict[str, Any]]:
    """Test history filtering (new since last update)."""
    print("\n── History helpers ─────────────────────────────────")
    from app import get_new_history_since_last_update, should_update_dictionary

    results = []
    results.append(run_timed("history: should_update_dictionary", should_update_dictionary))
    results.append(run_timed("history: get_new_since_last_update", get_new_history_since_last_update))
    return results


def test_ai_refine() -> List[Dict[str, Any]]:
    """Test AI text refinement agent latency."""
    print("\n── AI refine (network call) ────────────────────────")
    from app import ai_refine_text

    results = []
    results.append(run_timed(
        "ai_refine: short text (no app)",
        ai_refine_text,
        MOCK_RAW_TEXT,
        "",
    ))
    results.append(run_timed(
        "ai_refine: short text (with app hint)",
        ai_refine_text,
        MOCK_RAW_TEXT,
        "Mail",
    ))
    results.append(run_timed(
        "ai_refine: long text",
        ai_refine_text,
        MOCK_RAW_TEXT * 3,
        "Xcode",
    ))
    return results


def test_snippets() -> List[Dict[str, Any]]:
    """Test snippet intent detection (agent call)."""
    print("\n── Snippets ────────────────────────────────────────")
    from snippets import apply_snippets, should_expand_snippets

    results = []
    results.append(run_timed(
        "snippets: apply_snippets (no match expected)",
        apply_snippets,
        "Let me write an email about the project deadline",
    ))
    results.append(run_timed(
        "snippets: should_expand_snippets (empty triggers)",
        should_expand_snippets,
        MOCK_RAW_TEXT,
        [],
    ))
    results.append(run_timed(
        "snippets: should_expand_snippets (with triggers)",
        should_expand_snippets,
        "give me my calendar link please",
        ["calendar", "email", "zoom link"],
    ))
    return results


def test_dictionary_agent_update() -> List[Dict[str, Any]]:
    """Test dictionary agent batched update with mock items."""
    print("\n── Dictionary agent update (network call) ──────────")
    from dictionary_agent import run_batched_update

    small_batch  = MOCK_HISTORY_ITEMS[:5]
    medium_batch = MOCK_HISTORY_ITEMS[:20]

    results = []
    results.append(run_timed(
        "dict_agent: batched update (5 items)",
        run_batched_update,
        small_batch,
    ))
    results.append(run_timed(
        "dict_agent: batched update (20 items)",
        run_batched_update,
        medium_batch,
    ))
    return results


def test_calendar() -> List[Dict[str, Any]]:
    """Test calendar date extraction and schedule fetch."""
    print("\n── Calendar (network call) ─────────────────────────")
    from gcalendar import extract_date_from_text, extract_calendar_intent

    results = []
    results.append(run_timed(
        "calendar: extract_date_from_text",
        extract_date_from_text,
        "what's my schedule for tomorrow",
    ))
    results.append(run_timed(
        "calendar: extract_calendar_intent",
        extract_calendar_intent,
        "show my work calendar for Friday",
    ))

    # Only test get_schedule if token exists
    import getpass
    from gcalendar import tokens_dir, token_path
    uid  = getpass.getuser()
    path = token_path(uid)

    if path.exists():
        from gcalendar import get_schedule
        results.append(run_timed(
            "calendar: get_schedule today (all cals)",
            get_schedule,
            "today",
            "Australia/Sydney",
            uid,
            "all",
        ))
    else:
        print(f"  Skipping get_schedule — no token found for {uid}")
        results.append({
            "component": "calendar: get_schedule",
            "status":    "SKIP",
            "ms":        0,
            "error":     f"no token for {uid} — run get_token.py first",
        })

    return results


def test_transcription(audio_path: str) -> List[Dict[str, Any]]:
    """Test real transcription pipeline end-to-end."""
    print("\n── Transcription (real audio) ──────────────────────")
    from app import transcribe_audio, transcribe_and_enhance_impl

    results = []
    results.append(run_timed(
        "transcribe: raw audio → text",
        transcribe_audio,
        audio_path,
    ))
    results.append(run_timed(
        "transcribe: full pipeline (transcribe+refine+dict+snippets)",
        transcribe_and_enhance_impl,
        audio_path,
        "Mail",
    ))
    return results


# =========================================================
# Summary
# =========================================================

def print_summary(all_results: List[Dict[str, Any]]) -> None:
    passed = [r for r in all_results if r["status"] == "PASS"]
    failed = [r for r in all_results if r["status"] == "FAIL"]
    skipped = [r for r in all_results if r["status"] == "SKIP"]

    total_ms = sum(r["ms"] for r in passed)
    slowest  = sorted(passed, key=lambda r: r["ms"], reverse=True)[:3]

    print("\n" + "=" * 60)
    print(f"BENCHMARK SUMMARY — {len(all_results)} components")
    print("=" * 60)
    print(f"  Passed:   {len(passed)}")
    print(f"  Failed:   {len(failed)}")
    print(f"  Skipped:  {len(skipped)}")
    print(f"  Total:    {total_ms:,.1f} ms")
    print()

    if slowest:
        print("  Slowest components:")
        for r in slowest:
            print(f"    {r['ms']:>8.1f} ms  {r['component']}")

    if failed:
        print()
        print("  Failed components:")
        for r in failed:
            print(f"    ✗ {r['component']}: {r['error']}")

    print("=" * 60)


def save_results(all_results: List[Dict[str, Any]], path: str = "benchmark_results.json") -> None:
    passed   = [r for r in all_results if r["status"] == "PASS"]
    total_ms = sum(r["ms"] for r in passed)

    output = {
        "summary": {
            "total_components": len(all_results),
            "passed":           len(passed),
            "failed":           len([r for r in all_results if r["status"] == "FAIL"]),
            "skipped":          len([r for r in all_results if r["status"] == "SKIP"]),
            "total_ms":         round(total_ms, 2),
        },
        "results": all_results,
    }

    out = Path(path)
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to {out.resolve()}")


# =========================================================
# Entry point
# =========================================================

COMPONENT_MAP = {
    "storage":    test_storage_read_write,
    "dictionary": test_dictionary_corrections,
    "dedup":      test_deduplication,
    "history":    test_history_helpers,
    "refine":     test_ai_refine,
    "snippets":   test_snippets,
    "dict_agent": test_dictionary_agent_update,
    "calendar":   test_calendar,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whispr component benchmark")
    parser.add_argument(
        "--component", "-c",
        choices=list(COMPONENT_MAP.keys()),
        help="Run only a specific component (default: all)",
    )
    parser.add_argument(
        "--audio", "-a",
        help="Path to a real audio file for transcription tests",
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save results to benchmark_results.json",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Whispr component benchmark")
    print("=" * 60)

    all_results: List[Dict[str, Any]] = []

    if args.component:
        # Run only the requested component
        fn = COMPONENT_MAP[args.component]
        all_results.extend(fn())
    else:
        # Run all components in order
        # Fast local tests first
        all_results.extend(test_storage_read_write())
        all_results.extend(test_dictionary_corrections())
        all_results.extend(test_deduplication())
        all_results.extend(test_history_helpers())

        # Network calls
        all_results.extend(test_ai_refine())
        all_results.extend(test_snippets())
        all_results.extend(test_dictionary_agent_update())
        all_results.extend(test_calendar())

    # Real audio test if path provided
    if args.audio:
        if Path(args.audio).exists():
            all_results.extend(test_transcription(args.audio))
        else:
            print(f"\n  Warning: audio file not found: {args.audio}")

    print_summary(all_results)

    if args.save:
        save_results(all_results)