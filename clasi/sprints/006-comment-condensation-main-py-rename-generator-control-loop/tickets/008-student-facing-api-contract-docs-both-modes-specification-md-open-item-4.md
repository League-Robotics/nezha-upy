---
id: 008
title: Student-facing API contract docs (both modes) + specification.md open item
  4
status: done
use-cases:
- SUC-001
- SUC-002
depends-on:
- '007'
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Student-facing API contract docs (both modes) + specification.md open item 4

## Description

Documentation-only ticket, depends on ticket 007 (documents the
finished generator API, not a moving target). Two writes:

1. **Student-facing API contract note** (extend
   `docs/bench-acceptance-procedures.md` or add a clearly-scoped new
   section — match this repo's existing documentation location for
   student-facing contract text from sprint 001 ticket 009). Document
   **both** modes explicitly, side by side:
   - **Background (fiber) mode**: wheel control requires the Python
     program to reach `microbit_hal_idle()` (return to the scheduler)
     for the kernel fiber to be scheduled at all. A tight `while
     True:` loop that never reaches idle — including the realistic
     polling idiom `while True: p = radio.receive()` — starves the
     kernel fiber; the VM-hook starvation watchdog is the safety
     backstop (fault bit in telemetry + display indication), not a
     substitute for the contract.
   - **Generator (step-driven) mode**: wheels move only while the
     student keeps iterating the move generator (`next()`/`for`).
     Breaking out of the loop stops cleanly via the generator's
     `finally` block. An abandoned generator (stopped iterating
     without a clean `break`) decays to neutral within one short
     lease window (~3× cycle period) on its own, or via the same
     starvation watchdog if Python has stalled entirely.
   - State explicitly that the two modes are **mutually exclusive per
     boot** (first `start()`/`step()` call wins; the other raises) —
     this is a hard native-level latch (ticket 006), not a
     recommendation.
   - **Known bench-tooling defect, worth one line here**: the robot
     floods TLM telemetry over USB serial at ~19 Hz and does **not**
     stop on `TLM:OFF`. This blocks `mpremote`'s REPL handshake and
     produces a misleading "port in use by another program" error —
     it is a known defect (tracked separately,
     `tlm-stream-ignores-tlm-off.md`), not a cable or hardware fault.
     Anyone doing bench work with either mode should know this before
     losing time to it.
2. **`docs/design/specification.md` §10 open item 4**: record the
   decision at the *mechanism* level — framework-owned cadence inside
   move generators, student-owned loop body (neither `on_tick()` nor
   raw student `while True:`) — and explicitly state that which mode
   is the *primary* teaching posture is deferred until ticket 009's
   hardware evidence (the safety triple plus a generator-mode bench
   leg). Do not resolve the primary-vs-alternative question here; that
   call is ticket 009's, from bench evidence.

## Acceptance Criteria

- [x] Student-facing contract text covers both modes, side by side,
      each with its own "what makes wheels move / stop" statement.
- [x] Mutual-exclusivity (mode latch) is stated as a hard constraint,
      not a suggestion.
- [x] The TLM-flood-blocks-REPL-handshake defect gets one clearly
      marked line (defect, not hardware fault), with a pointer to
      `tlm-stream-ignores-tlm-off.md` — this ticket does not fix the
      defect, only documents it for bench operators.
- [x] `docs/design/specification.md` §10 open item 4 is updated:
      mechanism decided and recorded; primary-posture question
      explicitly deferred to ticket 009, not silently resolved either
      way.
- [x] No source code changed by this ticket (docs only).

## Testing

- **Existing tests to run**: `uv run pytest` — must stay green
  (docs-only change should have zero effect, but run the baseline to
  confirm).
- **New tests to write**: none — documentation.
- **Verification command**: `uv run pytest` (regression confirmation
  only; this ticket's real acceptance is a documentation review, not
  a test run).
