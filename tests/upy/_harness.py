"""Minimal assert/report helper for tests run under MicroPython.

pytest does not run under MicroPython, so each test script is a plain
program: call `check()` for each assertion, then `report()` last, which
exits non-zero if anything failed. Kept dependency-free on purpose --
these scripts must run on an interpreter with no stdlib to speak of.
"""

_results = []


def check(name, cond, detail=""):
    """Record one assertion. `detail` is printed only on failure."""
    _results.append((name, bool(cond), detail))
    return bool(cond)


def check_eq(name, got, want):
    ok = got == want
    _results.append((name, ok, "got %r, want %r" % (got, want)))
    return ok


def report(suite):
    """Print a summary and exit non-zero if any check failed."""
    failed = [r for r in _results if not r[1]]
    for name, ok, detail in _results:
        if not ok:
            print("FAIL %s :: %s %s" % (suite, name, detail))
    print("%s: %d checks, %d failed" % (suite, len(_results), len(failed)))
    if failed:
        raise SystemExit(1)
    raise SystemExit(0)
