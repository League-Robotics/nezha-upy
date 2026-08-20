---
id: '005'
title: 'Condense comments: tests/ and patches/*.py'
status: done
use-cases:
- UC-001
depends-on:
- '001'
github-issue: ''
issue: condense-comments-across-the-codebase.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Condense comments: tests/ and patches/*.py

## Description

All `tests/*.py` (including `tests/unit/`) and the two plain-Python
files under `patches/` (`apply_overlay.py`, `apply_yield.py`).
Depends on ticket 001 because it updated
`tests/test_manifest_freeze.py`'s docstring and
`_BENCH_ONLY_MODULES` entry — land that rename first so this ticket
condenses the already-renamed version, not an unsequenced rewrite of
the same lines. Must land **before ticket 007** (which adds new tests
to `tests/test_motion.py` for the generator-mode logic) for the same
reason — condense `test_motion.py`'s existing comments first, then
add new test functions with their own right-sized comments on top of
a stable base.

**Explicitly excluded from this ticket: `patches/modrobot_wire.patch`
and `patches/yield.patch`.** These are raw diffs applied against
vendored MicroPython source. A comment inside a diff hunk is content
that gets *applied elsewhere* when the patch runs — editing it is a
correctness-relevant content change to a downstream file, not a
same-repo prose simplification, and is out of this issue's own
stated intent (comments-only, no behavior change, applied to *this*
repo's own source). Leave both `.patch` files untouched.

Apply the same condensation discipline as ticket 002. Per the issue's
own carve-out for `tests/`: "test docstrings that state what a test
assumes assert are the useful kind — trim the narrative, keep the
assertion statement." Do not weaken any test's documentation of *what
it asserts and why* (e.g. `test_motion.py`'s explicit ms-vs-seconds
regression-assertion docstring, `test_manifest_freeze.py`'s own
docstring explaining why `_BENCH_ONLY_MODULES` exists) — only cut the
narrative *around* that statement.

**Comments-only. No behavior change.** No assertion, fixture, or test
body logic may change — including no renaming of test functions,
since that would change `pytest` collection/reporting even if
behavior is identical.

## Acceptance Criteria

- [x] Every `tests/*.py` file (including `tests/unit/`) keeps: a short
      module docstring; per-test docstrings/comments stating what is
      asserted and why (trimmed, not removed); any landmine or
      regression-risk marker (e.g. `test_motion.py`'s ms-vs-seconds
      note).
- [x] `patches/apply_overlay.py` and `patches/apply_yield.py` get the
      same condensation treatment as any other Python file.
- [x] `patches/modrobot_wire.patch` and `patches/yield.patch` are
      **untouched** (byte-identical — verify with `git diff
      --exit-code -- patches/*.patch` showing no change).
- [x] No executable/assertion line changes in any file; no test
      function renamed.
- [x] `uv run pytest` stays green at the 223-passed / 518-subtests
      baseline, unchanged — this is the direct self-check, since this
      ticket edits the test suite itself. (Actual measured baseline
      was 228 passed / 518 subtests; confirmed unchanged before and
      after this ticket's edits.)
- [x] `python3 -m py_compile` lints all changed `.py` files clean.

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline) — the full suite, run twice if useful (before and
  after) to positively confirm identical pass/fail/count, not just
  "green."
- **New tests to write**: none — comments-only.
- **Verification command**: `uv run pytest`
