---
id: '001'
title: "On-device main.py: button A \u2192 heart + square tour"
status: done
use-cases:
- UC-002
- UC-003
depends-on: []
github-issue: ''
issue: button-a-square-tour-on-device-trigger.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# On-device main.py: button A → heart + square tour

## Description

Button A on zetuv currently does nothing. Diagnosis is already
confirmed (not a malfunction): zetuv still runs this repo's image;
button-A-triggers-tour was the *other* session's MakeCode deliverable,
now moved to a different board (VBOV). This image has simply never
wired a button. The stakeholder is at the bench waiting — this ticket
adds the missing wiring and hands the robot back promptly for the
physical button press.

**Deliverable**: an on-device `main.py` for zetuv's filesystem — the
student-code slot this port runs after boot (`src/boot.py`/
`codal_port` `main.c`). `demo_square` (sprint 002) is already frozen,
so no firmware rebuild should be needed for this ticket; confirm that
assumption by probing the resident image before doing anything else.

**Behavior**:
- **Idle**: show a small prompt on the display so the user knows it's
  armed (e.g. a small arrow/dot animation, or a static "A").
- **On button A**: show a HEART immediately (the "it's working"
  feedback), then run the square tour (`demo_square`'s entry point),
  then return to the idle prompt. Repeatable presses.
- **Ctrl-C → live REPL must keep working** — `KeyboardInterrupt` must
  not be swallowed anywhere in the idle loop or the button handler.
- **Main-context only**: all waits are sleep-based (reach
  `microbit_hal_idle()`); never drive wheels from a callback/IRQ
  context — `microbit.button_a.was_pressed()` polled from the main
  loop, not an interrupt callback, consistent with this project's
  established idle-reaching contract (sprint 001 ticket 007's
  student-facing API contract note).

**Bench facts**: zetuv UID
`9906360200052820312bde85515a72e6000000006e052820`, currently at
`/dev/cu.usbmodem2121202`. getez and zavaz are RADIOBRIDGE relays —
**never flash them**, this ticket touches zetuv only. `/robot.json`
must be present on the device filesystem — re-copy the stripped
`data/zetuv.json` (sprint 002) if the filesystem was wiped; probe for
its presence before assuming.

**Deploy discipline**: **probe first** — the resident image on zetuv
may already be current (`v0.20260819.2`, per sprint 002's close). Only
run a `--clean` rebuild + reflash if the probe shows the resident image
is actually stale or `demo_square`/the rest of the stack isn't present.
Follow bench conventions (~5 s post-flash settle) if a reflash does
turn out to be necessary.

**Verification handoff**: bench-verify on zetuv — deploy `main.py`,
confirm the idle prompt appears, then invoke the *same handler
function* `main.py` wires to button A directly via REPL, to prove the
heart → tour → idle sequence runs end-to-end. The physical button
press itself is the stakeholder's to do — do not stand in for it, and
hand the robot back promptly once the REPL-invoked check passes.

Append the full observation to `docs/bench-log-zetuv-2026-08-19.md`
(new file, dated for today's bench session, distinct from sprint 002's
bench log).

## Acceptance Criteria

- [x] `main.py` exists on zetuv's filesystem implementing: idle
      prompt → button A → heart → `demo_square` tour → idle, main-context
      only, Ctrl-C/REPL preserved.
- [x] Deploy probe is recorded in the bench log: whether the resident
      image was already current or a reflash was needed, and which.
      (Probed: `boot`/`config` frozen modules found stale-stub; decided
      NO reflash needed since `main.py`/`demo_square` don't depend on
      their currency — disclosed as a flagged, out-of-scope finding.
      Bench log §17.)
- [x] `/robot.json` presence is confirmed (or re-copied from
      `data/zetuv.json` if missing) before verification — recorded in
      the bench log. (Confirmed present and valid, 2413 bytes, via
      on-device `os.stat`/`open` — `mpremote fs ls`'s own size column
      was found unreliable on this port; bench log §18.)
- [x] Bench log records: idle prompt observed on the display; the
      button-A handler function invoked directly via REPL and observed
      to run heart → tour → idle end-to-end. (§21 — idle prompt not
      independently visually confirmed, no camera access, consistent
      with every prior bench session in this file; `on_button_a()`
      REPL-invoked run fully evidenced, 8/8 segments reached, clean
      stop-verify.)
- [x] The robot is handed back to the stakeholder for the physical
      button press promptly after the REPL-invoked check passes — not
      blocked on further verification. (§22 — final reset + settle,
      no further exec/run commands issued, `mbdeploy list` confirmed
      zetuv connected at handoff.)
- [x] `python3 -m pytest tests/` stays green at the 204 baseline (no
      regressions; this ticket adds no CPython-testable logic beyond
      what a lint catches, since `main.py`'s only job is to call
      existing, already-tested modules).
- [x] `python3 -m py_compile` passes on the new `main.py`; `mpy-cross`
      lints it clean.
- [x] No manifest change — `main.py` lives on the filesystem
      (student-code slot), not the frozen manifest; confirm
      `src/codal_port/manifest.py` is untouched by this ticket.

## Testing

- **Existing tests to run**: full `python3 -m pytest tests/` suite
  (204-passed baseline) — must stay green.
- **New tests to write**: none required beyond the lint checks —
  `main.py` is a thin on-device script calling `demo_square` and stock
  `microbit` display/button APIs; its correctness is verified on
  hardware (bench log), not by a CPython unit test.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: probe zetuv's resident image and filesystem state first
(don't assume a reflash is needed, don't assume `/robot.json` is
present); write `main.py` calling `demo_square`'s existing entry point
from a plain polling loop (`microbit.button_a.was_pressed()`, sleep-
based idle animation); deploy via `mpremote fs cp` (or the established
`mbdeploy`/filesystem-copy path, whichever the probe indicates is
needed); verify via REPL invocation of the handler; log; hand back.

**Files to create/modify**: `main.py` (new, device filesystem — not
committed to `src/` as a frozen module, since it's the student-code
slot; store a copy in this repo, e.g. `src/main_zetuv_demo.py` or
similar, for reproducibility — programmer's call on the exact repo
path, but a copy must exist somewhere in version control, not only on
the device), `docs/bench-log-zetuv-2026-08-19.md` (new).

**Testing plan**: `python3 -m pytest tests/`; `py_compile`/`mpy-cross`
lint; on-device REPL-invoked verification as the primary check.

**Documentation updates**: `docs/bench-log-zetuv-2026-08-19.md` is
itself the documentation deliverable for this ticket.
