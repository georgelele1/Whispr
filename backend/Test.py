"""
test_whispr.py — Manual test runner for all Whispr backend functions

Usage:
    python test_whispr.py              # run all tests
    python test_whispr.py profile      # run only profile tests
    python test_whispr.py refine       # run only refine tests
    python test_whispr.py calendar     # run only calendar tests
    python test_whispr.py snippets     # run only snippet tests
    python test_whispr.py dictionary   # run only dictionary tests
    python test_whispr.py context      # run only context/memory tests
    python test_whispr.py intent       # run only intent detection tests
"""
from __future__ import annotations

import json
import sys
import time

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
SKIP = "\033[93m○\033[0m"
SEP  = "─" * 60

results = {"pass": 0, "fail": 0, "skip": 0}


def check(name: str, condition: bool, got: str = "", expected: str = "") -> None:
    if condition:
        print(f"  {PASS} {name}")
        results["pass"] += 1
    else:
        print(f"  {FAIL} {name}")
        if got:      print(f"       got:      {got[:120]}")
        if expected: print(f"       expected: {expected[:120]}")
        results["fail"] += 1


def skip(name: str, reason: str = "") -> None:
    print(f"  {SKIP} {name}{' — ' + reason if reason else ''}")
    results["skip"] += 1


def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


# =========================================================
# 1. Profile tests
# =========================================================

def test_profile():
    section("Profile")
    from app import load_profile, save_profile, get_target_language, set_target_language

    profile = load_profile()
    check("load_profile returns dict",        isinstance(profile, dict))
    check("profile has preferences key",      "preferences" in profile)
    check("profile has learned key",          "learned" in profile)
    check("learned has description field",    "description" in profile.get("learned", {}))

    lang = get_target_language()
    check("get_target_language returns string", isinstance(lang, str) and len(lang) > 0)

    ok = set_target_language("Chinese")
    check("set_target_language Chinese",     ok)
    check("language saved correctly",         get_target_language() == "Chinese")

    # Reset
    set_target_language("English")
    check("reset language to English",        get_target_language() == "English")


# =========================================================
# 2. User context / memory tests
# =========================================================

def test_context():
    section("User context & memory")
    from app import _build_user_context, get_user_context, update_profile_from_history

    ctx = _build_user_context()
    check("_build_user_context returns string",  isinstance(ctx, str))
    print(f"       context preview: {ctx[:120]!r}")

    ctx2 = get_user_context()
    check("get_user_context returns cached",     isinstance(ctx2, str))
    check("cache consistent",                    ctx2 == get_user_context())  # same object

    # Test profile update
    print("  → Running update_profile_from_history (may take ~8s)...")
    t0 = time.perf_counter()
    update_profile_from_history()
    ms = (time.perf_counter() - t0) * 1000

    from app import load_profile
    profile     = load_profile()
    description = profile.get("learned", {}).get("description", "")
    check("profile description generated",   bool(description), got=description[:80])
    print(f"       description: {description[:120]!r}")
    print(f"       update took: {ms:.0f}ms")


# =========================================================
# 3. Intent detection tests
# =========================================================

def test_intent():
    section("Intent detection")
    from app import detect_intent, _CALENDAR_ALLOW, _CALENDAR_DENY, _CALENDAR_SEARCH

    cases = [
        # (text, expected_intent, description)
        ("check my schedule for today",                    "calendar", "basic calendar fetch"),
        ("what's on my calendar tomorrow",                 "calendar", "calendar tomorrow"),
        ("show my calendar for Friday",                    "calendar", "calendar Friday"),
        ("when is my exam",                                "search",   "calendar search"),
        ("find my dentist appointment",                    "search",   "calendar search 2"),
        ("my calendar is full today",                      "text",     "deny — not a request"),
        ("I already scheduled the meeting",                "text",     "deny — past tense"),
        ("send an email to John about the project",        "text",     "normal text"),
        ("uh so the meeting is at nine tomorrow",          "text",     "text with fillers"),
    ]

    for text, expected, desc in cases:
        result = detect_intent(text, [])
        got    = result.get("type", "?")
        check(f"{desc}: '{text[:40]}'", got == expected,
              got=got, expected=expected)

    # Snippet intent
    from app import detect_intent
    result = detect_intent("give me my zoom link", ["zoom link"])
    check("snippet intent: give me zoom link",
          result.get("type") == "snippet", got=str(result))


# =========================================================
# 4. Refine tests
# =========================================================

def test_refine():
    section("AI refine")
    from app import ai_refine_text

    cases = [
        # (input, check_fn, description)
        (
            "uh so the meeting is is at nine tomorrow",
            lambda o: "uh" not in o.lower() and "is is" not in o,
            "removes fillers and stutters"
        ),
        (
            "so point one fix the login point two the dashboard is broken point three add dark mode",
            lambda o: "1." in o and "2." in o and "3." in o,
            "formats numbered list"
        ),
        (
            "ah hmm yeah so basically I wanted to say the project is going well",
            lambda o: "hmm" not in o.lower() and "basically" not in o.lower(),
            "removes interjections and filler"
        ),
        (
            "send the room link to John",
            lambda o: "zoom" in o.lower() or "room" in o.lower(),  # may or may not correct
            "phonetic correction attempt"
        ),
    ]

    for text, check_fn, desc in cases:
        print(f"  → Testing: {desc} (~10s)...")
        t0  = time.perf_counter()
        out = ai_refine_text(text, "Mail", "English")
        ms  = (time.perf_counter() - t0) * 1000
        check(f"{desc} [{ms:.0f}ms]", check_fn(out),
              got=out[:80], expected=desc)


# =========================================================
# 5. Snippet tests
# =========================================================

def test_snippets():
    section("Snippets")
    from snippets import load_snippets, add_snippet, remove_snippet, list_all
    from app import apply_inline_snippets

    # List
    data = list_all()
    check("list_all returns ok",       data.get("ok") == True)
    check("snippets is a list",        isinstance(data.get("snippets"), list))
    print(f"       total snippets: {data.get('count', 0)}")

    # Add test snippet
    result = add_snippet("test trigger xyz", "TEST_EXPANSION_XYZ")
    check("add_snippet ok",            result.get("ok") == True)

    # Verify it exists
    snippets = load_snippets().get("snippets", [])
    found    = any(s["trigger"] == "test trigger xyz" for s in snippets)
    check("snippet saved to disk",     found)

    # Inline replacement
    out = apply_inline_snippets("please use test trigger xyz here")
    check("inline replacement works",  "TEST_EXPANSION_XYZ" in out, got=out)

    # Remove test snippet
    result = remove_snippet("test trigger xyz")
    check("remove_snippet ok",         result.get("ok") == True)

    # Verify existing snippets inline
    existing = load_snippets().get("snippets", [])
    url_snippets = [s for s in existing if s.get("expansion", "").startswith("http")]
    if url_snippets:
        t = url_snippets[0]["trigger"]
        out2 = apply_inline_snippets(f"send my {t} to John")
        check(f"URL snippet '{t}' inline", t.lower() not in out2.lower() or url_snippets[0]["expansion"] in out2,
              got=out2[:80])
    else:
        skip("URL snippet inline", "no URL snippets found — add one first")


# =========================================================
# 6. Calendar tests
# =========================================================

def test_calendar():
    section("Calendar")
    from gcalendar import load_current_email, _token_path

    email = load_current_email()
    if not email:
        skip("all calendar tests", "no account connected — run: python gcalendar.py connect")
        return

    check("email loaded", bool(email), got=email)

    path = _token_path(email)
    check("token file exists", path.exists(), got=str(path))

    from gcalendar import get_credentials
    try:
        creds, em = get_credentials(email)
        check("credentials valid", creds.valid, got=f"valid={creds.valid}")
    except Exception as e:
        check("credentials valid", False, got=str(e))
        return

    # Intent extraction
    from gcalendar import extract_calendar_intent, extract_search_intent
    cal = extract_calendar_intent("show my schedule for tomorrow")
    check("extract_calendar_intent", cal.get("date") in ("tomorrow", None),
          got=str(cal))

    si = extract_search_intent("when is my COMP9900 exam")
    check("extract_search_intent",  bool(si.get("query")),
          got=str(si))

    # Fetch schedule
    from gcalendar import get_schedule
    print("  → Fetching today's schedule...")
    result = get_schedule("today", user_id=email)
    check("get_schedule today returns text", isinstance(result, str) and len(result) > 0,
          got=result[:80])
    print(f"       schedule: {result[:120]!r}")


# =========================================================
# 7. Dictionary tests
# =========================================================

def test_dictionary():
    section("Dictionary")
    from dictionary_agent import (
        load_dictionary, add_or_update_term, remove_term,
        get_dictionary, deduplicate_dictionary
    )

    data = load_dictionary()
    check("load_dictionary returns dict",  isinstance(data, dict))
    check("has terms list",                isinstance(data.get("terms"), list))
    print(f"       total terms: {len(data.get('terms', []))}")

    # Add test term
    result = add_or_update_term("TestTermXYZ", ["test alias one", "test alias two"])
    check("add_or_update_term ok",  result.get("ok") == True, got=str(result))

    # Verify
    data2 = load_dictionary()
    found = any(t["phrase"] == "TestTermXYZ" for t in data2.get("terms", []))
    check("term saved to disk",     found)

    # Deduplication
    result2 = deduplicate_dictionary()
    check("deduplicate_dictionary runs", "total_terms" in result2, got=str(result2))
    print(f"       after dedup: {result2.get('total_terms')} terms, {result2.get('merged', 0)} merged")

    # Remove test term
    result3 = remove_term("TestTermXYZ")
    check("remove_term ok",         result3.get("ok") == True, got=str(result3))


# =========================================================
# 8. History tests
# =========================================================

def test_history():
    section("History")
    from app import load_history, append_history, now_ms

    data = load_history()
    check("load_history returns dict",  isinstance(data, dict))
    check("has items list",             isinstance(data.get("items"), list))
    count = len(data.get("items", []))
    print(f"       total items: {count}")

    if count > 0:
        last = data["items"][-1]
        check("last item has final_text",  "final_text" in last)
        check("last item has timestamp",   "ts" in last)
        print(f"       last item: {str(last.get('final_text',''))[:80]!r}")
    else:
        skip("history item checks", "no history yet")

    # Append test item
    append_history({"ts": now_ms(), "raw_text": "test", "final_text": "Test.", "app_name": "test"})
    data2 = load_history()
    check("append_history works",  len(data2.get("items", [])) == count + 1)

    # Clean up test item
    data2["items"] = data2["items"][:-1]
    from app import save_store
    save_store("history.json", data2)
    check("history cleanup ok",    len(load_history().get("items", [])) == count)


# =========================================================
# Entry point
# =========================================================

SUITES = {
    "profile":    test_profile,
    "context":    test_context,
    "intent":     test_intent,
    "refine":     test_refine,
    "snippets":   test_snippets,
    "calendar":   test_calendar,
    "dictionary": test_dictionary,
    "history":    test_history,
}

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 60)
    print("  Whispr backend test runner")
    print("=" * 60)

    if target and target in SUITES:
        SUITES[target]()
    elif target:
        print(f"Unknown suite: {target}")
        print(f"Available: {', '.join(SUITES.keys())}")
        sys.exit(1)
    else:
        for fn in SUITES.values():
            fn()

    print(f"\n{'=' * 60}")
    total = results['pass'] + results['fail'] + results['skip']
    print(f"  Results: {results['pass']} passed  {results['fail']} failed  {results['skip']} skipped  ({total} total)")
    print(f"{'=' * 60}")

    sys.exit(0 if results["fail"] == 0 else 1)