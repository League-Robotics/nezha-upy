---
status: in-progress
sprint: '002'
tickets:
- 002-001
- 002-002
---

# Flash zetuv and demonstrate wheels with a square tour

## Description

Stakeholder directive (2026-08-19): flash the micro:bit named
**zetuv** with the v0.20260819.1 image, run bench tests on it, and get
a **square tour** running to demonstrate that the wheels move. Unlike
sprint 001, hardware work is explicitly IN scope for the executing
agents this session.

Facts from recon:

- zetuv is connected now (`mbdeploy list`: /dev/cu.usbmodem2121202,
  UID 9906360200052820312bde85515a72e6000000006e052820). getez and
  zavaz are also connected — deploy by UID/name to zetuv ONLY; getez
  may be a relay-class board (mbdeploy refuses relays without
  --force-relay; never pass it).
- No zetuv robot config exists (not in data/ nor radio-robot-elite's
  data/robots). One must be derived (tovez_nocal.json is the natural
  template); zetuv's motor port wiring and signs are unknown and must
  be verified on the bench (smallest-visible-pulse, encoder-sign check)
  before any tour.
- The reference square tour is radio-robot-elite
  `src/host/robot_radio/planner/tour.py` `TOUR_SQUARE`: 4 × 500 mm
  legs + 4 × 90° left pivots, rest-to-rest, settle 1.2 s,
  omega_max 2.4 rad/s. The HOST-driven tour cannot run against this
  image yet (msgs.py has no binary field tables), so the demo is an
  ON-DEVICE square tour mirroring those numbers, driven through this
  repo's motion/diffdrive stack via USB (`mpremote`).
- Bench conventions bind: `--clean` build before hardware verify,
  deploy by UID, ~5 s post-flash settle, WiFi module power-cycle
  (WiFi not needed for this USB demo). Boot is fail-closed without
  `/robot.json` on the device filesystem (REPL stays live; native
  diffdrive API still reachable) — put zetuv's JSON on the device or
  configure from the REPL.
- Safety: 5000 ms lease ceiling, boot zero-write, starvation watchdog
  are in the image; use short leases and smallest visible pulses when
  probing wiring.

Deliverables: `data/zetuv.json` (with honest provenance notes for
derived/unverified values), a runnable on-device square-tour demo
(repeatable via a single documented command), and a bench log of what
was verified on zetuv (flash OK, REPL answers, wheel signs, square tour
observed).
