"""
testall.py — Whispr backend test suite.
Location: backend/tests/testall.py
Run: python tests/testall.py

Shows REAL outputs from each agent — actual text, not just true/false.
Saves full input/output/timing to tests/outputs/<group>/<test>.json

Usage:
    python tests/testall.py
    python tests/testall.py --fast
    python tests/testall.py --only refiner
    python tests/testall.py --only knowledge
    python tests/testall.py --only calendar
    python tests/testall.py --only intent
    python tests/testall.py --only dictionary
    python tests/testall.py --only snippets
    python tests/testall.py --only pipeline
"""
import sys
import time
import json
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if ROOT.name == "tests":
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

OUTPUTS = Path(__file__).resolve().parent / "outputs"
OUTPUTS.mkdir(exist_ok=True)

print("=" * 60)
print("Whispr Backend Test Suite")
print(f"Root   : {ROOT}")
print(f"Outputs: {OUTPUTS}")
print("=" * 60)

_results       = []
_current_group = "misc"


def _set_group(name: str):
    global _current_group
    _current_group = name
    (OUTPUTS / name).mkdir(exist_ok=True)


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w]", "_", name)[:60]


def _save(name: str, record: dict):
    path = OUTPUTS / _current_group / f"{_safe_name(name)}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def run_test(name: str, raw_input: str, output: str, passed: bool, ms: float, note: str = ""):
    """Print one test with full visible input and output."""
    print(f"\n{'─'*60}")
    print(f"TEST   : {name}")
    print(f"INPUT  : {raw_input}")
    print(f"OUTPUT : {output}")
    if note:
        print(f"NOTE   : {note}")
    print(f"TIME   : {ms:.0f}ms")
    print(f"STATUS : {'✓ PASS' if passed else '✗ FAIL'}")
    _save(name, {"test": name, "group": _current_group, "input": raw_input,
                 "output": output, "note": note, "passed": passed, "ms": round(ms, 1)})
    _results.append({"name": name, "passed": passed, "ms": ms})


def summary():
    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    passed = sum(1 for r in _results if r["passed"])
    for r in _results:
        print(f"  {'✓' if r['passed'] else '✗'}  {r['name']:<50} {r['ms']:>6.0f}ms")
    print(f"{'─'*60}")
    print(f"  {passed}/{len(_results)} passed")
    print(f"  JSON outputs: {OUTPUTS}")
    if passed < len(_results):
        sys.exit(1)


# =========================================================
# Intent
# =========================================================

def test_intent(fast=False):
    _set_group("intent")
    print("\n[GROUP] INTENT")
    from agents.intent import _layer1, detect_intent

    cases = [
        ("what's on my calendar today",                    "calendar"),
        ("show me my schedule for tomorrow",               "calendar"),
        ("when is my COMP9417 exam",                       "calendar"),
        ("am I free on Friday afternoon",                  "calendar"),
        ("what is Newton's second law",                    "knowledge"),
        ("explain the difference between TCP and UDP",     "knowledge"),
        ("give me the formula for kinetic energy",         "knowledge"),
        ("send an email to John about the project update", None),
        ("I need to write a report on climate change",     None),
    ]

    for text, expected in cases:
        t0     = time.perf_counter()
        result = _layer1(text)
        ms     = (time.perf_counter() - t0) * 1000
        passed = (result == expected) if expected else (result is None)
        run_test(f"L1: {text[:45]}", raw_input=text,
                 output=str(result), passed=passed, ms=ms,
                 note=f"expected={expected or 'None'}")

    if not fast:
        llm_cases = [
            ("send an email to the team about the standup",  "refine"),
            ("translate this to Mandarin",                   "refine"),
            ("and also mention the deadline",                "refine"),
            ("tell me about the water cycle",                "knowledge"),
            ("what meetings do I have this afternoon",       "calendar"),
        ]
        for text, expected in llm_cases:
            t0     = time.perf_counter()
            result = detect_intent(text)
            ms     = (time.perf_counter() - t0) * 1000
            run_test(f"L2: {text[:45]}", raw_input=text,
                     output=result, passed=result == expected, ms=ms,
                     note=f"expected={expected}")


# =========================================================
# Refiner
# =========================================================

def test_refiner(fast=False):
    _set_group("refiner")
    print("\n[GROUP] REFINER")
    from agents.refiner import _quick_clean, run as refine

    clean_cases = [
        "uh so basically I need to send this to the team by Friday",
        "I I want to write write the the report today",
        "um like basically the meeting is at 3pm tomorrow okay so",
    ]
    for raw in clean_cases:
        t0     = time.perf_counter()
        result = _quick_clean(raw)
        ms     = (time.perf_counter() - t0) * 1000
        run_test(f"quick_clean: {raw[:40]}", raw_input=raw, output=result,
                 passed=len(result) > 0 and result != raw, ms=ms)

    if not fast:
        agent_cases = [
            ("uh so I need to write an email to Professor Smith about missing tomorrow's lecture because I'm sick", "Mail",   "clean professional email"),
            ("first the project deadline is Friday second submit on WebCMS third attach the report",               "Notes",  "numbered list 1. 2. 3."),
            ("hey team just a quick heads up the standup is moved to 3pm today",                                  "Slack",  "short chat message"),
            ("def fibonacci n if n less than or equal to one return n return fibonacci n minus one plus fibonacci n minus two", "Xcode", "code comment style"),
        ]
        for raw, app, note in agent_cases:
            t0     = time.perf_counter()
            result = refine(raw, app)
            ms     = (time.perf_counter() - t0) * 1000
            run_test(f"refine [{app}]: {raw[:40]}", raw_input=raw, output=result,
                     passed=len(result.strip()) > 0, ms=ms, note=note)


# =========================================================
# Knowledge
# =========================================================

def test_knowledge(fast=False):
    _set_group("knowledge")
    print("\n[GROUP] KNOWLEDGE")
    if fast:
        print("  skipped in fast mode")
        return

    from agents.knowledge import run as ask

    questions = [
        ("what is Newton's second law of motion",                       "should contain F=ma or force=mass×acceleration"),
        ("give me the formula for kinetic energy explain each variable", "should contain ½mv² and explain m and v"),
        ("explain the difference between TCP and UDP",                  "should contrast reliability vs speed"),
        ("what are the steps to implement binary search",               "should be a numbered list"),
        ("define photosynthesis",                                       "should be concise domain-specific definition"),
    ]

    for q, note in questions:
        t0     = time.perf_counter()
        result = ask(q)
        ms     = (time.perf_counter() - t0) * 1000
        passed = (
            len(result.strip()) > 0
            and not result.strip().lower().startswith(("here is", "sure", "of course", "great"))
        )
        run_test(f"ask: {q[:45]}", raw_input=q, output=result,
                 passed=passed, ms=ms, note=note)

    # Followup — asks first then expects context-aware followup
    ask("what is the Pythagorean theorem")
    t0     = time.perf_counter()
    result = ask("what does each variable represent")
    ms     = (time.perf_counter() - t0) * 1000
    run_test("followup: what does each variable represent",
             raw_input="what does each variable represent (after Pythagorean theorem)",
             output=result, passed=len(result.strip()) > 0, ms=ms,
             note="should reference a, b, c without re-asking the theorem")


# =========================================================
# Calendar
# =========================================================

def test_calendar(fast=False):
    _set_group("calendar")
    print("\n[GROUP] CALENDAR")
    from agents.calendar import _inject_date, _SEARCH

    class _Fake:
        current_session = {"messages": []}
    fake = _Fake()
    _inject_date(fake)
    injected = fake.current_session["messages"][0]["content"]
    run_test("inject_date: injects current date", raw_input="(system)",
             output=injected, passed="Current date" in injected, ms=0)

    search_cases = [
        ("when is my dentist appointment",       True),
        ("search my calendar for COMP9417 exam", True),
        ("find my tutorial for Thursday",        True),
        ("what's on my calendar today",          False),
    ]
    for text, should_match in search_cases:
        matched = bool(_SEARCH.search(text))
        run_test(f"_SEARCH: {text[:45]}", raw_input=text,
                 output=f"matched={matched}", passed=matched == should_match,
                 ms=0, note=f"expected match={should_match}")

    if not fast:
        from gcalendar import load_current_email
        from agents.calendar import run as cal_run
        if load_current_email():
            fetch_cases = [
                ("what's on my calendar today",       "today's full schedule"),
                ("show me my schedule for tomorrow",  "tomorrow's events"),
                ("search my calendar for COMP9417",   "any COMP9417 events"),
            ]
            for text, note in fetch_cases:
                t0     = time.perf_counter()
                result = cal_run(text, text)
                ms     = (time.perf_counter() - t0) * 1000
                run_test(f"calendar: {text[:45]}", raw_input=text, output=result,
                         passed=len(result.strip()) > 0, ms=ms, note=note)
        else:
            print("  skipping live calendar — no Google account connected")


# =========================================================
# Dictionary
# =========================================================

def test_dictionary(fast=False):
    _set_group("dictionary")
    print("\n[GROUP] DICTIONARY")
    from agents.dictionary_agent import (
        add_or_update_term, remove_term, approve_term,
        _count_frequency, inject_dictionary,
    )

    r  = add_or_update_term("COMP9417", ["comp 9417", "comp nine four one seven"], "course_code")
    run_test("add_or_update_term: COMP9417",
             raw_input="COMP9417 + aliases", output=json.dumps(r),
             passed=r.get("ok", False), ms=0)

    r = approve_term("COMP9417", True)
    run_test("approve_term: COMP9417",
             raw_input="COMP9417", output=json.dumps(r),
             passed=r.get("ok", False), ms=0)

    texts = [
        "COMP9417 machine learning lecture was really good today",
        "I need to submit COMP9417 assignment on WebCMS by Friday",
        "PyTorch tutorial for COMP9417 project is due next week",
        "my COMP9900 capstone project team meeting is tomorrow",
        "COMP9900 project sprint review on Thursday afternoon",
    ]
    t0       = time.perf_counter()
    freq     = _count_frequency(texts)
    ms       = (time.perf_counter() - t0) * 1000
    freq_str = ", ".join(f"{k}({v})" for k, v in freq[:10])
    run_test("_count_frequency: from real transcripts",
             raw_input=f"{len(texts)} real transcription samples",
             output=freq_str, passed=len(freq) > 0, ms=ms,
             note="top recurring non-common tokens with counts")

    class _Fake:
        current_session = {"messages": []}
    inject_dictionary(_Fake())
    msg = _Fake.current_session["messages"][0]["content"] if _Fake.current_session["messages"] else "no terms injected"
    run_test("inject_dictionary: terms injected to session",
             raw_input="(agent session before LLM call)",
             output=msg[:300], passed=True, ms=0)

    r = remove_term("COMP9417")
    run_test("remove_term: COMP9417",
             raw_input="COMP9417", output=json.dumps(r),
             passed=r.get("ok", False), ms=0)

    if not fast:
        from agents.dictionary_agent import run_batched_update
        items = [
            {"final_text": "COMP9417 machine learning assignment due Friday"},
            {"final_text": "COMP9417 PyTorch model training for the project"},
            {"final_text": "COMP9900 capstone meeting with team on WebCMS"},
            {"final_text": "COMP9900 sprint demo submission next Thursday"},
            {"final_text": "kubectl deploy the docker container to the cluster"},
        ]
        t0     = time.perf_counter()
        result = run_batched_update(items)
        ms     = (time.perf_counter() - t0) * 1000
        added   = [t["phrase"] for t in result.get("added", [])]
        updated = [t["phrase"] for t in result.get("updated", [])]
        run_test("run_batched_update: from 5 transcripts",
                 raw_input="\n".join(i["final_text"] for i in items),
                 output=f"added={added}\nupdated={updated}\ntotal_terms={result.get('total_terms')}",
                 passed=True, ms=ms, note="profile-aware term extraction")


# =========================================================
# Snippets
# =========================================================

def test_snippets(fast=False):
    _set_group("snippets")
    print("\n[GROUP] SNIPPETS")
    from snippets import load_snippets, add_snippet, remove_snippet, toggle_snippet

    r = add_snippet("my zoom link", "https://zoom.us/j/test123456")
    run_test("add_snippet: my zoom link",
             raw_input="trigger=my zoom link, expansion=https://zoom.us/j/test123456",
             output=json.dumps(r), passed=r.get("ok", False), ms=0)

    found = next((s for s in load_snippets().get("snippets", []) if s["trigger"] == "my zoom link"), None)
    run_test("load_snippets: verify stored value",
             raw_input="my zoom link",
             output=json.dumps(found) if found else "not found",
             passed=found is not None, ms=0)

    r = toggle_snippet("my zoom link", False)
    run_test("toggle_snippet: disable",
             raw_input="my zoom link → enabled=False",
             output=json.dumps(r), passed=r.get("ok", False), ms=0)

    r = toggle_snippet("my zoom link", True)
    run_test("toggle_snippet: enable",
             raw_input="my zoom link → enabled=True",
             output=json.dumps(r), passed=r.get("ok", False), ms=0)

    r = remove_snippet("my zoom link")
    run_test("remove_snippet: my zoom link",
             raw_input="my zoom link",
             output=json.dumps(r), passed=r.get("ok", False), ms=0)


# =========================================================
# Pipeline — end to end
# =========================================================

def test_pipeline(fast=False):
    _set_group("pipeline")
    print("\n[GROUP] PIPELINE")
    if fast:
        print("  skipped in fast mode")
        return

    from app import transcribe_and_enhance_impl

    cases = [
        (
            "uh so basically I need to write an email to Professor Smith about missing tomorrow's lecture because I have a doctor's appointment",
            "Mail",
            "should be clean professional email with greeting and sign-off"
        ),
        (
            "what is Newton's second law of motion and give me the formula",
            "unknown",
            "should return F=ma with explanation, no preamble"
        ),
        (
            "what's on my calendar today",
            "unknown",
            "should return today's schedule or 'calendar clear' message"
        ),
        (
            "first the deadline is Friday second submit on WebCMS third attach the PDF report",
            "Notes",
            "should be formatted as 1. 2. 3. numbered list"
        ),
        (
            "hey team the standup is moved to 3pm today please update your calendars",
            "Slack",
            "should be short conversational chat message"
        ),
    ]

    for raw, app, note in cases:
        t0     = time.perf_counter()
        result = transcribe_and_enhance_impl("", app, "", _raw_text_override=raw)
        ms     = (time.perf_counter() - t0) * 1000
        output = result.get("final_text", "ERROR: no final_text")
        run_test(
            f"pipeline [{app}]: {raw[:40]}",
            raw_input=raw, output=output,
            passed=len(output.strip()) > 0, ms=ms, note=note
        )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="Skip LLM calls")
    parser.add_argument("--only", type=str, default="",
                        help="intent|refiner|knowledge|calendar|dictionary|snippets|pipeline")
    args = parser.parse_args()

    groups = {
        "intent":     test_intent,
        "refiner":    test_refiner,
        "knowledge":  test_knowledge,
        "calendar":   test_calendar,
        "dictionary": test_dictionary,
        "snippets":   test_snippets,
        "pipeline":   test_pipeline,
    }

    only = args.only.lower().strip()
    if only:
        if only not in groups:
            print(f"Unknown: '{only}'. Options: {', '.join(groups)}")
            sys.exit(1)
        groups[only](fast=args.fast)
    else:
        for fn in groups.values():
            fn(fast=args.fast)

    summary()