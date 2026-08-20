---
id: '007'
title: motion.py generator-driven move logic (offline, fake-diffdrive stub)
status: done
use-cases:
- SUC-001
- SUC-002
depends-on:
- '003'
- '005'
- '006'
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# motion.py generator-driven move logic (offline, fake-diffdrive stub)

## Description

Add generator-based move functions to `src/motion.py`, alongside —
not replacing — the existing `MoveQueue`/`RobotDispatch` background-
mode classes, which stay unchanged. Depends on ticket 003 (this
sprint's `src/` comment-condensation pass already touched
`motion.py`; land that first so this ticket edits a stable,
already-condensed file) and ticket 005 (comment-condensation of
`tests/`, which touched `test_motion.py`; same reasoning — this
ticket adds new tests to that file next). Depends on ticket 006 for
the native binding surface (`diffdrive.step()`, `cyclePeriod`) this
code is written against.

`motion.py`'s own module docstring already documents this exact
addition as a "KNOWN GAP, not yet ticketed" from sprint 001 — this
ticket is that follow-on.

Illustrative shape (from the issue; adapt as needed to match the
ticket-006 binding's actual signatures):

```python
def drive(v, twist, duration_ms):
    end = ticks_add(ticks_ms(), duration_ms)
    cycle = ticks_ms()
    try:
        while ticks_diff(end, ticks_ms()) > 0:
            wait = ticks_diff(cycle, ticks_ms())
            if wait > 0: sleep_ms(wait)          # generator owns pacing
            cycle = ticks_add(cycle, PERIOD_MS)   # absolute deadlines
            diffdrive.drive(v, twist, LEASE_MS)   # short lease, renewed
            diffdrive.step()
            yield diffdrive.output()              # student reads progress
    finally:
        diffdrive.neutral()
        diffdrive.step()   # one landing cycle so the staged zero reaches the bus
```

Key properties to implement and test:

- Pacing against `diffdrive.cyclePeriod` (from ticket 006), via
  absolute deadlines — not a hardcoded period constant.
- Lease renewed every cycle, short (~3× period), so an abandoned
  generator decays to neutral on its own before the watchdog would
  need to act (SUC-002).
- `break` out of the driving loop → `GeneratorExit` → the `finally`
  block → `neutral()` + one landing `step()` (SUC-001's postcondition:
  wheels stop cleanly at generator exit).
- **No change to `MoveQueue`/`RobotDispatch`** — background mode's
  wire-driven dispatch path is untouched; the generator surface is a
  new, separate entry point for direct/REPL/student use.

Offline-testable in plain CPython against a fake `diffdrive` stub
(step/output/drive/neutral recording stub) — the same interface-seam
pattern `tests/test_motion.py`'s existing `_StubDiffDrive` already
uses for the background-mode tests, and the same pattern sprint 001
ticket 005 established for `comms.py`. No hardware, no build, needed
for this ticket's own gate.

## Acceptance Criteria

- [x] New generator-based move function(s) in `motion.py`, callable
      directly (not through `RobotDispatch`'s wire-verb dispatch).
- [x] First `next()` call is the point at which mode latches natively
      (via `diffdrive.step()`'s own latch, ticket 006) — no
      motion.py-side mode tracking duplicates what the binding already
      enforces.
- [x] Pacing test: cycle timing follows absolute deadlines against
      `cyclePeriod`, not a fixed sleep — verified against the fake
      stub with a controllable clock.
- [x] Lease-renewal test: each `next()` renews a short lease; the fake
      stub records lease values passed to `drive()`.
- [x] `finally`-block test, two paths: (a) normal completion (duration
      elapses) → `neutral()` + landing `step()` called; (b) `break` by
      the caller mid-iteration → `GeneratorExit` → same `finally`
      behavior.
- [x] Existing `MoveQueue`/`RobotDispatch` tests in `test_motion.py`
      pass **unmodified** — confirms background mode is untouched.
- [x] `uv run pytest` stays green; the baseline count increases by
      exactly the new generator tests added (no existing test's
      pass/fail status changes).
- [x] `python3 -m py_compile` and `mpy-cross` lint `motion.py` clean.

## Testing

- **Existing tests to run**: `uv run pytest`, specifically
  `tests/test_motion.py`'s existing `MoveQueue`/`RobotDispatch`
  coverage, confirming zero regression.
- **New tests to write**: generator pacing (fake clock, assert cycle
  timing against `cyclePeriod`), lease renewal (assert lease value per
  `next()`), `finally`-block stop on normal completion, `finally`-
  block stop on `break`, and a no-op/degenerate case (zero-duration or
  immediately-stopped generator still lands a clean neutral). All
  against a fake `diffdrive` stub extending `test_motion.py`'s
  existing `_StubDiffDrive` pattern with `step()`/`cyclePeriod`.
- **Verification command**: `uv run pytest tests/test_motion.py` then
  full `uv run pytest`.
