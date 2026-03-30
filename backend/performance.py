"""
performance.py — Whispr component timing tests

Usage:
    python performance.py          # run all tests including audio files
    python performance.py --save   # save results to benchmark_results.json

Audio files expected in the same directory:
    short.wav       — short clean speech
    long.wav        — long paragraph
    calender.wav    — calendar request ("check my schedule for tomorrow")
    translation.wav — non-English speech for translation test
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

BASE_DIR = Path(__file__).resolve().parent

# ── Audio files ───────────────────────────────────────────
AUDIO_SHORT       = BASE_DIR / "short.wav"
AUDIO_LONG        = BASE_DIR / "long.wav"
AUDIO_CALENDAR    = BASE_DIR / "calendar.wav"
AUDIO_TRANSLATION = BASE_DIR / "translation.wav"


# =========================================================
# Timer
# =========================================================

def run_timed(name: str, fn: Callable, *args, **kwargs) -> Dict[str, Any]:
    print(f"  {name} ...", end=" ", flush=True)
    start = time.perf_counter()
    error = None
    try:
        fn(*args, **kwargs)
        status = "PASS"
    except Exception as e:
        status = "FAIL"
        error  = str(e)
    ms = (time.perf_counter() - start) * 1000
    print(f"{ms:>8.1f} ms  {'✓' if status == 'PASS' else f'✗ ({error[:60]})'}")
    return {"component": name, "status": status, "ms": round(ms, 2), "error": error}


def skip(name: str, reason: str) -> Dict[str, Any]:
    print(f"  {name} — SKIP ({reason})")
    return {"component": name, "status": "SKIP", "ms": 0, "error": reason}


# =========================================================
# Mock data
# =========================================================

MOCK_TEXT = (
    "um so so basically I I wanted to say that uh "
    "the the meeting is scheduled for tomorrow at nine am"
)

MOCK_ITEMS = [
    {
        "ts":         int(time.time() * 1000) - i * 3600000,
        "raw_text":   f"uh so the Whispr project is coming along nicely iteration {i}",
        "final_text": f"The Whispr project is coming along nicely. Iteration {i}.",
        "app_name":   "Xcode" if i % 2 == 0 else "Mail",
    }
    for i in range(50)
]


# =========================================================
# Component tests (mock data)
# =========================================================

def test_storage() -> List[Dict[str, Any]]:
    print("\n── Storage ─────────────────────────────────────────")
    from app import load_history, load_dictionary, load_profile
    return [
        run_timed("load_history",    load_history),
        run_timed("load_dictionary", load_dictionary),
        run_timed("load_profile",    load_profile),
    ]


def test_dictionary_corrections() -> List[Dict[str, Any]]:
    print("\n── Dictionary corrections ──────────────────────────")
    from app import apply_dictionary_corrections
    return [
        run_timed("apply_corrections", apply_dictionary_corrections, MOCK_TEXT),
    ]


def test_dedup() -> List[Dict[str, Any]]:
    print("\n── Token optimisation ──────────────────────────────")
    from dictionary_agent import deduplicate_items, prepare_items_for_agent, get_optimal_sample_size
    texts = [f"The Whispr project meeting is at nine am today number {i}" for i in range(50)]
    return [
        run_timed("deduplicate_items (50)",       deduplicate_items,       texts),
        run_timed("prepare_items_for_agent (50)", prepare_items_for_agent, MOCK_ITEMS),
        run_timed("get_optimal_sample_size (50)", get_optimal_sample_size, MOCK_ITEMS),
    ]


def test_history() -> List[Dict[str, Any]]:
    print("\n── History helpers ─────────────────────────────────")
    from dictionary_agent import get_new_history_since_last_update, should_update_dictionary
    return [
        run_timed("should_update_dictionary",  should_update_dictionary),
        run_timed("get_new_since_last_update", get_new_history_since_last_update),
    ]


def test_refine() -> List[Dict[str, Any]]:
    print("\n── AI refine (network) ─────────────────────────────")
    from app import ai_refine_text
    return [
        run_timed("ai_refine (mock text)", ai_refine_text, MOCK_TEXT, "Mail"),
    ]


def test_snippets() -> List[Dict[str, Any]]:
    print("\n── Snippets (network) ──────────────────────────────")
    from snippets import apply_snippets, get_calendar, _build_agent
    return [
        run_timed("apply_snippets (no match)",   apply_snippets, "Let me write an email about the deadline"),
        run_timed("static snippet match",        lambda: _build_agent({"zoom link": "https://zoom.us/j/123"}).input("paste my zoom link")),
        run_timed("get_calendar (no token)",     get_calendar, "today", "all"),
    ]


def test_dict_agent() -> List[Dict[str, Any]]:
    print("\n── Dictionary agent update (network) ───────────────")
    from dictionary_agent import run_batched_update
    return [
        run_timed("batched update (10 items)", run_batched_update, MOCK_ITEMS[:10]),
    ]


def test_calendar_api() -> List[Dict[str, Any]]:
    print("\n── Calendar API (network) ──────────────────────────")
    from gcalendar import extract_calendar_intent, load_current_email, _token_path, get_schedule
    results = [
        run_timed("extract_calendar_intent", extract_calendar_intent, "show my work calendar for Friday"),
    ]
    email = load_current_email()
    path  = _token_path(email) if email else None
    if path and path.exists():
        results.append(run_timed("get_schedule today", get_schedule, "today", "Australia/Sydney", email, "all"))
    else:
        results.append(skip("get_schedule", "no token — run: python gcalendar.py connect"))
    return results


# =========================================================
# Audio file tests (real pipeline)
# =========================================================

def test_audio_short() -> List[Dict[str, Any]]:
    print("\n── Audio: short.wav ────────────────────────────────")
    if not AUDIO_SHORT.exists():
        return [skip("short.wav pipeline", "file not found")]
    from app import transcribe_audio, transcribe_and_enhance_impl
    return [
        run_timed("short: transcribe only",  transcribe_audio,            str(AUDIO_SHORT)),
        run_timed("short: full pipeline",    transcribe_and_enhance_impl, str(AUDIO_SHORT), "Mail"),
    ]


def test_audio_long() -> List[Dict[str, Any]]:
    print("\n── Audio: long.wav ─────────────────────────────────")
    if not AUDIO_LONG.exists():
        return [skip("long.wav pipeline", "file not found")]
    from app import transcribe_audio, transcribe_and_enhance_impl
    return [
        run_timed("long: transcribe only", transcribe_audio,            str(AUDIO_LONG)),
        run_timed("long: full pipeline",   transcribe_and_enhance_impl, str(AUDIO_LONG), "Mail"),
    ]


def test_audio_calendar() -> List[Dict[str, Any]]:
    print("\n── Audio: calender.wav ─────────────────────────────")
    if not AUDIO_CALENDAR.exists():
        return [skip("calendar.wav pipeline", "file not found")]
    from app import transcribe_audio, transcribe_and_enhance_impl
    # Run full pipeline — intent detection should route to calendar
    return [
        run_timed("calendar: transcribe only", transcribe_audio,            str(AUDIO_CALENDAR)),
        run_timed("calendar: full pipeline",   transcribe_and_enhance_impl, str(AUDIO_CALENDAR), "Mail"),
    ]


def test_audio_translation() -> List[Dict[str, Any]]:
    """Test translation pipeline — runs full pipeline with Chinese output language."""
    print("\n── Audio: translation.wav ──────────────────────────")
    if not AUDIO_TRANSLATION.exists():
        return [skip("translation.wav pipeline", "file not found")]
    from app import transcribe_audio, transcribe_and_enhance_impl
    return [
        run_timed("translation: transcribe only",          transcribe_audio,            str(AUDIO_TRANSLATION)),
        run_timed("translation: pipeline → English",       transcribe_and_enhance_impl, str(AUDIO_TRANSLATION), "Mail", "English"),
        run_timed("translation: pipeline → Chinese",       transcribe_and_enhance_impl, str(AUDIO_TRANSLATION), "Mail", "Chinese"),
        run_timed("translation: pipeline → Spanish",       transcribe_and_enhance_impl, str(AUDIO_TRANSLATION), "Mail", "Spanish"),
    ]


# =========================================================
# Runtime summary table
# =========================================================

def print_summary(results: List[Dict[str, Any]]) -> None:
    passed  = [r for r in results if r["status"] == "PASS"]
    failed  = [r for r in results if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIP"]

    network_keywords = ("refine", "snippet", "calendar", "agent", "pipeline", "schedule")
    local   = [r for r in passed if not any(k in r["component"].lower() for k in network_keywords)]
    network = [r for r in passed if     any(k in r["component"].lower() for k in network_keywords)]

    col = 46
    div = "─" * 64

    print(f"\n{'=' * 64}")
    print(f"  RUNTIME SUMMARY")
    print(f"{'=' * 64}")
    print(f"  {'Component':<{col}} {'Time':>8}")
    print(f"  {div}")

    if local:
        print(f"  Local (no network)")
        for r in local:
            print(f"    {r['component']:<{col-2}} {r['ms']:>7.1f} ms")

    if network:
        print(f"  Network / pipeline")
        for r in network:
            print(f"    {r['component']:<{col-2}} {r['ms']:>7.1f} ms")

    print(f"  {div}")

    local_total   = sum(r["ms"] for r in local)
    network_total = sum(r["ms"] for r in network)
    grand_total   = local_total + network_total

    print(f"  {'Local subtotal':<{col}} {local_total:>7.1f} ms")
    print(f"  {'Network/pipeline subtotal':<{col}} {network_total:>7.1f} ms")
    print(f"  {'TOTAL':<{col}} {grand_total:>7.1f} ms")
    print(f"  {div}")
    print(f"  Passed: {len(passed)}  Failed: {len(failed)}  Skipped: {len(skipped)}")

    if failed:
        print(f"\n  Failed:")
        for r in failed:
            print(f"    ✗ {r['component']}: {r['error']}")

    if network:
        slowest = max(network, key=lambda r: r["ms"])
        print(f"\n  Slowest: {slowest['component']} ({slowest['ms']:.1f} ms)")

    print(f"{'=' * 64}")


def save_results(results: List[Dict[str, Any]], path: str = "benchmark_results.json") -> None:
    passed   = [r for r in results if r["status"] == "PASS"]
    total_ms = sum(r["ms"] for r in passed)
    out = Path(path)
    out.write_text(json.dumps({
        "summary": {
            "total":    len(results),
            "passed":   len(passed),
            "failed":   len([r for r in results if r["status"] == "FAIL"]),
            "skipped":  len([r for r in results if r["status"] == "SKIP"]),
            "total_ms": round(total_ms, 2),
        },
        "results": results,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {out.resolve()}")


# =========================================================
# Entry point
# =========================================================

COMPONENT_MAP = {
    "storage":     test_storage,
    "dictionary":  test_dictionary_corrections,
    "dedup":       test_dedup,
    "history":     test_history,
    "refine":      test_refine,
    "snippets":    test_snippets,
    "dict_agent":  test_dict_agent,
    "calendar":    test_calendar_api,
    "short":       test_audio_short,
    "long":        test_audio_long,
    "audio_cal":   test_audio_calendar,
    "translation": test_audio_translation,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whispr benchmark")
    parser.add_argument("--component", "-c", choices=list(COMPONENT_MAP.keys()), help="Run one component only")
    parser.add_argument("--save",      "-s", action="store_true", help="Save to benchmark_results.json")
    args = parser.parse_args()

    print("=" * 64)
    print("  Whispr component benchmark")
    print("=" * 64)

    all_results: List[Dict[str, Any]] = []

    if args.component:
        all_results.extend(COMPONENT_MAP[args.component]())
    else:
        # Run all — mock tests first, then all four audio files
        for fn in COMPONENT_MAP.values():
            all_results.extend(fn())

    print_summary(all_results)

    if args.save:
        save_results(all_results)