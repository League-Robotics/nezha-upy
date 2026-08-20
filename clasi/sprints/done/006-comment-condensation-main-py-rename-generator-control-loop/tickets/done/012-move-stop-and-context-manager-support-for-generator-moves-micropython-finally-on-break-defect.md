---
id: '012'
title: Move.stop() and context-manager support for generator moves (MicroPython finally-on-break
  defect)
status: done
use-cases:
- SUC-001
- SUC-002
depends-on:
- '007'
- 008
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Move.stop() and context-manager support for generator moves (MicroPython finally-on-break defect)

## Description

Defect found on real hardware during ticket 009's bench run — see
ticket 009's `exception` block for the full measured evidence. Ticket
009 is thrown and will be re-run once this ticket and 011 both land;
they are independent of each other.

**Measured**: breaking out of `for state in motion.drive(...)` does
**not** run the generator's `finally` block on MicroPython.
`gen.close()` advances `cycleCount` 5→6, runs the `finally`, lands
duty 0.0/0.0 — correct. But a bare `break` leaves `cycleCount` at 12
with duty still 17.0/17.0, and an explicit `gc.collect()` does not run
the `finally` either. MicroPython's mark-and-sweep GC does not
promptly close a suspended generator the way CPython refcounting
does, so `GeneratorExit` never fires on `break`, and the wheels keep
turning until the starvation watchdog trips (~250 ms).

**Why the offline suite stayed green while hardware was broken**: the
existing `test_generator_finally_lands_neutral_on_break` test asserts
via `gen.close()` — which is not the student idiom (`break` is) and
does not exercise the actual failure mode. This ticket's Tests section
below exists specifically to not repeat that mistake.

### Stakeholder decision — fixed, do not re-open or offer alternatives

Stopping becomes **explicit**, and it is called `stop()`, not
`close()`. Two supported forms, one mechanism:

1. Explicit: the student calls `move.stop()` when leaving the loop
   early.
2. Context manager: `with motion.drive(...) as move:` — `__exit__`
   calls `stop()`.

### Required API change

`motion.drive()` (`src/motion.py`, currently a bare generator function
at line ~525, ticket 007) returns a bare generator today, which
cannot carry a `.stop()` method. It must return a small wrapper object
instead.

**Naming — collision check performed, as required**: the ticket
description's suggested name `Move` collides with the existing
`class Move` already in `src/motion.py` (line ~132) — a plain
value/request object (`v`, `twist`, `duration_ms`, `stop_distance_mm`)
used by the background-mode `MoveQueue` path. Reusing `Move` for this
wrapper would be genuinely ambiguous in the same module (one `Move` is
an inert data record queued for later execution; the other would be a
live, iterable, stoppable handle over an in-progress generator —
different enough concepts that sharing a name invites real confusion,
not just a style nit). **Chosen name: `MoveHandle`** — it names what
the object actually is (a handle over a live resource you can iterate,
stop, or use as a context manager), and reads naturally at the call
site (`with motion.drive(...) as move:` still binds the *value* to
`move`; the *type* is `MoveHandle`). If a better-fitting name emerges
during implementation, use it and note the final choice in
Implementation Notes below — but `Move` itself must not be reused for
this.

**Required shape**:

- `__iter__` / `__next__` delegate to the inner generator, so `for
  state in motion.drive(...)` keeps working completely unchanged for
  callers who don't need explicit `stop()` (i.e. background/queued
  callers are unaffected, and even generator-mode callers who always
  let the move run to natural completion see no change).
- `stop()` closes the inner generator, which runs the **existing**
  `finally` block (`neutral()` + one landing `step()`) — do not
  duplicate that landing logic anywhere; reuse the `finally` hardware
  already proved correct via `gen.close()`. `stop()`'s whole job is
  to make sure `close()` (or equivalent) actually gets called,
  reliably, exactly when the student calls `stop()` — not to
  reimplement what happens when it is.
- `stop()` is idempotent: safe to call twice; safe to call after the
  move has completed normally; safe to call from inside the loop
  immediately before a `break`.
- `__enter__` returns `self`; `__exit__` calls `stop()` and returns
  `False` (do not suppress exceptions raised inside the `with` block).

## Docs to correct

Ticket 008 documented the invariant hardware has now disproven —
"a bare `break` lands a clean neutral" is false. Update both:

- `docs/bench-acceptance-procedures.md` §B.1.2
- `docs/design/specification.md` §10 item 4

Replace with the real contract: call `stop()`, or use `with`, and the
wheels stop immediately (one landing cycle, ≤~24 ms). Document the
starvation watchdog explicitly as a **failsafe** for the
forgot-to-stop case (~250 ms coast to zero) — not as the contract
itself; a student relying on the watchdog instead of `stop()`/`with`
is relying on a safety net, not the documented behavior. Update the
student-facing examples to the `with` form as the **primary** idiom
(`with motion.drive(...) as move: ...`), with the explicit `stop()`
form shown as the alternative for cases that don't fit a `with`
block.

## Tests

This is the part that failed us last time — be specific, not general:

- The existing `test_generator_finally_lands_neutral_on_break` (or
  whatever it is now named post-ticket-004/007) asserts via
  `gen.close()`, which is **not** the student idiom, and that gap is
  exactly why the suite stayed green while hardware was broken.
  Replace it — or supplement it and mark the `close()`-based version
  as documenting the underlying mechanism only, not the contract —
  with tests that exercise the actual documented paths: calling
  `move.stop()` directly, and using `with motion.drive(...) as
  move:`. Both must assert the `finally` ran (fake-stub records
  `neutral()` + a landing `step()` call).
- Add a test that a **bare `break` without `stop()`** leaves duty
  commanded (against the fake stub — assert `neutral()`/landing
  `step()` were *not* called) — this documents the known-and-accepted
  behavior explicitly, so nobody later "fixes" this test into a false
  green by making it assert the opposite. The watchdog, not this
  generator, is what protects a student who does this on hardware.
- Add idempotency coverage: `stop()` called twice does not raise or
  double-run the `finally`; `stop()` called after natural completion
  is a no-op, not an error.
- **Explicit caveat, state it in this ticket and in a code comment
  near the new tests**: CPython generator/GC finalization semantics
  do **not** match MicroPython's, so no CPython-only test may ever be
  treated as proof that `break`-without-`stop()` behaves identically
  on-device — the fake-stub tests above prove `MoveHandle.stop()`'s
  *own* logic (explicit method call, not implicit GC-triggered
  finalization), which is legitimately portable since it no longer
  depends on when-or-whether a runtime finalizes a generator.
  Finalization-timing claims specifically remain hardware-only proof;
  ticket 009's re-run is what verifies those, not this ticket's
  offline suite.

## Acceptance Criteria

- [x] `motion.drive()` returns a `MoveHandle` (or the implementer's
      better-fitting, non-`Move`-colliding name, reported in
      Implementation Notes) wrapping the existing generator.
- [x] `for state in motion.drive(...)` still works unchanged
      (`__iter__`/`__next__` delegate correctly).
- [x] `move.stop()` closes the inner generator and runs the existing
      `finally` (`neutral()` + landing `step()`) — verified via the
      fake diffdrive stub, not a new landing-logic implementation.
- [x] `stop()` is idempotent (double-call, post-completion-call both
      safe, covered by tests).
- [x] `with motion.drive(...) as move:` supported;
      `__exit__`/`__exit__`-triggered `stop()` verified by test;
      exceptions raised inside the `with` block are not suppressed.
- [x] The existing `close()`-based test is either replaced or
      explicitly reframed as mechanism-only, and new tests cover
      `stop()` and `with` as the documented paths.
- [x] A test explicitly documents bare-`break`-without-`stop()`
      leaving duty commanded (fake stub) — a known, accepted gap
      covered by the hardware watchdog, not by this code.
- [x] `docs/bench-acceptance-procedures.md` §B.1.2 and
      `docs/design/specification.md` §10 item 4 both state the real
      contract (`stop()`/`with` stops immediately; watchdog is a
      failsafe, not the contract) and show the `with` form as the
      primary student-facing idiom.
- [x] `uv run pytest tests/` — 237 passed / 518 subtests plus the new
      tests added here, zero regressions among the existing 237/518.
- [x] `python3 -m py_compile` clean on all changed files.
- [x] `git diff --exit-code -- vendor/` clean — no vendored file
      touched.
- [x] No native/C++ change expected or required for this ticket; if
      the implementer finds one is genuinely necessary, justify why in
      Implementation Notes before making it (this ticket's default
      scope is `src/motion.py`, its tests, and the two docs above).

## Testing

- **Existing tests to run**: `uv run pytest tests/` (237 / 518
  baseline before this ticket's own new tests are added).
- **New tests to write**: `stop()`-based finally verification,
  `with`-based finally verification, `stop()` idempotency (twice;
  post-completion), and the bare-break-leaves-duty-commanded
  documentation test — all listed in Tests above, all against the
  fake diffdrive stub (extends the same stub `test_motion.py` and
  ticket 007 already use).
- **Verification command**: `uv run pytest tests/`

## Implementation Notes

Wrapper class name: **`MoveHandle`**, as proposed in the ticket
description — kept as-is; no better-fitting name emerged during
implementation. `src/motion.py`'s `class Move` (the queued
v/twist/duration_ms value object used by background-mode
`MoveQueue`) was left untouched and not reused.

Implementation shape (`src/motion.py`):
- The original generator function body (validation, absolute-deadline
  pacing loop, the `finally` landing block) was renamed to a private
  `_drive_gen(...)` — byte-for-byte unchanged logic, just renamed and
  no longer directly public.
- The public `drive(...)` function now just returns
  `MoveHandle(_drive_gen(...))`.
- `MoveHandle.__iter__`/`__next__` delegate to the wrapped generator.
  `stop()` guards on a `self._stopped` flag (idempotent) and calls
  `self._gen.close()` — this is the ONLY call site that closes the
  generator; no landing logic was duplicated. `__enter__` returns
  `self`; `__exit__` calls `stop()` and returns `False`.
- No `contextlib` import — `__enter__`/`__exit__` hand-rolled per
  CLAUDE.md (MicroPython may not have `contextlib`).
- Added `MoveHandle` to `__all__`.

Tests (`tests/test_motion.py`):
- The three pre-existing generator tests that called `gen.close()`
  purely as end-of-test cleanup (not asserting the break-defect path)
  were switched to `gen.stop()`:
  `test_generator_each_next_runs_exactly_one_kernel_step`,
  `test_generator_pacing_uses_absolute_deadlines_not_drifting_sleep`,
  `test_generator_lease_renewed_each_cycle_is_short`.
- `test_generator_finally_lands_neutral_on_break` (the misleading
  `gen.close()`-as-break test) was replaced by
  `test_drive_gen_finally_lands_neutral_on_generator_close`, which
  calls the private `motion._drive_gen(...)` directly and is
  explicitly documented as mechanism-only, not the contract.
- New tests added, all against `_StubDiffDrive`/`_FakeClock`:
  `test_movehandle_stop_lands_neutral`,
  `test_movehandle_stop_twice_is_idempotent`,
  `test_movehandle_stop_after_natural_completion_is_a_noop`,
  `test_movehandle_with_stops_on_normal_exit`,
  `test_movehandle_with_stops_on_break`,
  `test_movehandle_with_stops_on_exception_and_does_not_suppress_it`,
  `test_bare_break_without_stop_leaves_duty_commanded`.
- `test_bare_break_without_stop_leaves_duty_commanded` is a portable
  proof, not a GC-timing test: the `move` handle stays referenced by
  the test function across the `break`, so nothing closes the
  generator on ANY Python implementation — it proves that `break`
  alone triggers no implicit stop, independent of finalization timing.
  A section comment ahead of this test block carries the required
  CPython-timing-is-not-proof caveat.
- Net test count: 237 baseline − 1 replaced + 8 new = 244 top-level
  tests, 518 subtests unchanged (`uv run pytest tests/`: 244 passed,
  518 subtests passed).

Docs:
- `docs/bench-acceptance-procedures.md` §B.1.2 rewritten: `with
  motion.drive(...) as move:` is now shown as the primary idiom,
  explicit `move.stop()` as the alternative; the "bare break lands a
  clean neutral" claim was removed and replaced with the measured
  defect plus the corrected contract; a new paragraph frames the
  ~250 ms starvation watchdog explicitly as a failsafe for the
  forgot-to-stop case, not the contract, and cites
  `test_bare_break_without_stop_leaves_duty_commanded`. The
  pre-existing "abandoned generator" lease-decay paragraph (a
  different, still-accurate mechanism — kernel-side lease timeout, not
  the generator's Python-level `finally`) was left as written; only
  its lead-in clause was adjusted from "without a clean `break`" to
  "without calling `stop()`" for consistency with the corrected
  contract.
- `docs/design/specification.md` §10 item 4 updated: the
  loop-ownership resolution now names `MoveHandle`/`stop()`/`with`
  (ticket 012) instead of describing `drive()` as a bare generator,
  states the measured `break`-alone defect and the watchdog-failsafe
  framing, and corrects the "generator-mode drive/break/abandoned-
  generator leg" phrase (which implied `break` was itself a tested,
  sanctioned path) to "drive/`stop()`-or-`with`/abandoned-generator
  leg" for ticket 009's pending re-run.

Verification run:
- `uv run pytest tests/` → 244 passed, 518 subtests passed (baseline
  237/518, zero regressions).
- `python3 -m py_compile src/motion.py tests/test_motion.py` → clean.
- `micropython-microbit-v2/lib/micropython/mpy-cross/mpy-cross
  src/motion.py` → compiled clean, no MicroPython-incompatible syntax
  (temporary `.mpy` output removed after the check).
- `git diff --exit-code -- vendor/` → clean, exit 0.
