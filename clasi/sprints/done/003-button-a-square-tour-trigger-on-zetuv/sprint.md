---
id: '003'
title: Button A square tour trigger on zetuv
status: closed
branch: sprint/003-button-a-square-tour-trigger-on-zetuv
worktree: false
use-cases:
- UC-002
- UC-003
issues:
- button-a-square-tour-on-device-trigger.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 003: Button A square tour trigger on zetuv

## Goals

Give zetuv a physical, audible response to button A: show a heart on
the display and run the square tour, so the stakeholder — currently at
the bench — sees and hears the wheels move from a button press.

## Problem

Button A currently does nothing. Diagnosis (already confirmed):
zetuv still runs this repo's image; button-A-triggers-tour was the
*other* session's MakeCode deliverable, now moved to a different board
(VBOV). This image has never wired any button — not a malfunction, a
missing feature.

## Solution

Add one on-device `main.py` to zetuv's filesystem (this port's
student-code slot — runs after boot per `src/boot.py`/`codal_port`
`main.c`; `demo_square` is already frozen from sprint 002, so no
firmware rebuild should be needed). Idle state shows an armed prompt;
button A shows a heart immediately, then runs the square tour, then
returns to idle. Bench-verified on zetuv; the physical button press
itself is handed to the stakeholder.

## Success Criteria

- zetuv shows an idle prompt on the display after boot.
- Pressing A shows a heart immediately, then runs the square tour,
  then returns to idle — repeatable.
- Ctrl-C still reaches a live REPL (KeyboardInterrupt not swallowed).
- The same handler function is invoked via REPL and confirmed to run
  the tour end-to-end, before handing the robot to the stakeholder for
  the physical button press.
- `docs/bench-log-zetuv-2026-08-19.md` records the bench verification.
- `python3 -m pytest tests/` stays green at the 204 baseline;
  `py_compile` + `mpy-cross` lint the new file clean.

## Scope

### In Scope

- One on-device `main.py` for zetuv's filesystem: idle prompt, button-A
  handler (heart → `demo_square` tour → idle), main-context only.
- Bench deploy to zetuv (probe first; reflash only if the resident
  image isn't already current) and REPL-invoked verification.

### Out of Scope

- Any firmware/module change — `demo_square` and the rest of the
  sprint 001/002 stack are consumed as-is.
- Any board other than zetuv — getez and zavaz are RADIOBRIDGE relays,
  never flashed.
- Calibration, additional buttons, or any behavior beyond A → heart →
  tour → idle.

## Test Strategy

Offline: `python3 -m pytest tests/` (204 baseline) stays green;
`py_compile` and `mpy-cross` lint the new `main.py`. On hardware: probe
zetuv's resident image first (reflash only if stale), confirm the idle
prompt, and invoke the button-A handler function directly from the
REPL to prove the heart-then-tour sequence runs end-to-end — this
substitutes for the physical press, which is the stakeholder's to do.

## Architecture

**Sizing: Trivial.** One on-device `main.py` dropped into the existing
filesystem student-code slot, calling the already-frozen `demo_square`
entry point and stock `microbit.display`/`microbit.button_a` APIs.
Zero framework or module changes — no new module, no changed
interface, no data-model impact. No diagrams; no Design Rationale or
Migration Concerns beyond "none" — there is nothing to a single
filesystem script that either section would add.

## Use Cases

This sprint exercises existing use cases (`docs/design/usecases.md`)
on zetuv, adding no new ones: UC-002 (flash and boot to a live REPL —
the bench-verification precondition) and UC-003 (student/operator
drives wheels — here, triggered by a button press instead of the REPL
directly, running the same `demo_square` sequence sprint 002 already
built).

## GitHub Issues

(None — this sprint's issue is a CLASI-local `clasi/issues/` file.)

## Definition of Ready

- [x] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [x] Architecture review passed (skipped — trivial, no architectural
      impact)
- [x] Stakeholder has approved the sprint plan (direct directive
      2026-08-19, at the bench: "make the A button show me a heart...
      I want to hear the motors move")

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | On-device main.py: button A → heart + square tour | — |

Tickets execute serially in the order listed.
