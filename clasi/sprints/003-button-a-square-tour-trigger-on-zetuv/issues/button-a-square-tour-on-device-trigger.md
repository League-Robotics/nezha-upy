---
status: in-progress
sprint: '003'
tickets:
- 003-001
---

# Button A triggers the square tour on-device (with heart feedback)

## Description

Stakeholder (2026-08-19, at the bench): pressing button A on zetuv does
nothing. They expected the square tour and want to HEAR the motors; at
minimum button A must show a heart on the LED display so the robot
visibly responds.

Diagnosis (confirmed by probe): zetuv still runs our image (MicroPython
answers on /dev/cu.usbmodem2121202), and our image has never wired any
button — the square tour so far only runs host-driven
(`mpremote run src/demo_square.py`). Button-A-triggers-tour was the
OTHER session's MakeCode deliverable, now moved to VBOV. Not a
malfunction; a missing feature in this image.

Deliverable: an on-device `main.py` for zetuv's filesystem (the
student-code slot — this port runs filesystem main.py after boot, per
src/boot.py / codal_port main.c; no firmware rebuild should be needed
since demo_square is already frozen):

- Idle: show a small prompt on the display so the user knows it's
  armed (e.g. a small arrow/dot animation or "A").
- On button A: show a HEART immediately (the "it's working" feedback),
  then run the square tour (`demo_square`), then return to idle prompt.
  Repeatable presses.
- Keep Ctrl-C → live REPL working (KeyboardInterrupt must not be
  swallowed).
- Main-context only (sleep-based waits reach microbit_hal_idle; never
  drive wheels from a callback context).
- Bench-verify on zetuv: deploy, confirm the idle prompt appears, and
  invoke the SAME handler function via REPL to prove the tour runs
  end-to-end (the physical button press itself is the stakeholder's to
  do — they are at the bench waiting; hand over promptly).

Bench facts: zetuv UID 9906360200052820312bde85515a72e6000000006e052820,
port /dev/cu.usbmodem2121202 currently; getez and zavaz are RADIOBRIDGE
relays — never flash them. /robot.json must be present (re-copy stripped
data/zetuv.json if the filesystem was wiped). Follow bench conventions
(~5 s settle; --clean build only if a reflash is actually needed —
probe first, the resident image may already be current).
