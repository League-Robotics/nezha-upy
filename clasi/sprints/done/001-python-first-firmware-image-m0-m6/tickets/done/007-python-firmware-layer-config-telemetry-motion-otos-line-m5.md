---
id: '007'
title: 'Python firmware layer: config/telemetry/motion/otos/line (M5)'
status: done
use-cases:
- UC-011
- UC-012
- UC-013
depends-on:
- '002'
- '004'
- '005'
- '006'
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Python firmware layer: config/telemetry/motion/otos/line (M5)

## Description

The largest integration ticket: it wires together every prior
ticket's output into the robot's actual runtime behavior.

- `src/config.py` — loads per-robot JSON from `data/` (ticket 002) on
  the device, fail-closed on any missing/invalid required key (per
  `robot_config.schema.json`); maps `wheel_control` →
  `DiffDrive::Config` via `travel_calib`×10; wires CONFIG/SET_FIELD/
  GET_CONFIG live through `src/comms.py`'s dispatch interface (ticket
  005). No on-flash tuning store — baked JSON rules at boot (spec §8).
- `src/otos.py`, `src/line.py` — sensor drivers, bus facts as
  captured: 0x17 init/scales/20 ms, 0x1A ×4/50 ms. All bus traffic
  goes through the moddiffdrive I2C broker (`robotio.i2c_xfer()`,
  ticket 004) — never a direct bus access, so the shared ledger stays
  intact.
- `src/telemetry.py` — the full 22-field frame, including the watchdog
  fault bit and `cycleOverrunCount_` (wired from ticket 004, now
  integrated into the real frame rather than the raw accessor).
- `src/motion.py` — 5-deep move queue, stop conditions, timeout fault,
  replace semantics, GO_TO, SEED/POSE, CALIBRATE. **Every duration is
  milliseconds** — this is a landmine-ledger regression risk (a
  sec/ms slip once ran wheels 8+ minutes); treat it as load-bearing,
  not a detail.

**Resolve the sprint's flagged open question before finalizing
`motion.py`'s public API**: teaching-framework loop ownership
(`on_tick()` callbacks vs. student `while True:`, spec open item 4,
explicitly "decide before M5"). If it cannot be resolved from PLAN.md,
the specification, or the review, escalate to the stakeholder rather
than guessing — do not silently pick one.

**Perform the `manifest.py` freeze-point switch here, not earlier**:
per review §4 (spec §7.4), this port cannot load `.mpy` from the
filesystem, so real module shipping is `manifest.py` freezing
(`FROZEN_MANIFEST` is already wired to `manifest.py` in
`src/codal_port/Makefile`). Add every `src/*.py` module built so far —
including `wifi_at.py` from ticket 006 — to the freeze list. This is a
one-way switch within the sprint (see sprint.md Migration Concerns):
once frozen, further Python changes need a full rebuild+reflash.

## Acceptance Criteria

All criteria are offline. `move_protocol_bench.py`'s full pass over
the radio path and OTOS-pose-sane-in-TLM verification move to ticket
009's documented stakeholder procedure.

- [x] `./build.sh --clean` (now with the manifest freeze applied) exits
      0, still flash end < `_fs_start`; note the RAM/flash delta from
      freezing (compare against ticket 006's last pre-freeze build) for
      ticket 009's M6 checkpoint procedure to reference.
- [x] `src/config.py`'s fail-closed key validation is unit-tested
      offline (`tests/test_config.py`) against `data/tovez.json`,
      `data/gopiv.json`, and a deliberately-malformed fixture (missing
      a required key), asserting refusal on the malformed case.
- [x] The same test asserts `wheel_control` → `DiffDrive::Config`
      mapping (`travel_calib`×10) against known input/output pairs.
- [x] `src/motion.py`'s queue/stop-condition/timeout-fault/replace
      logic is unit-tested offline (`tests/test_motion.py`) against a
      stub diffdrive backend, with an explicit regression assertion
      that durations are treated as milliseconds, not seconds.
- [x] `src/telemetry.py`'s 22-field frame assembly is unit-tested
      offline (`tests/test_telemetry.py`) against a synthetic
      sensor/kernel-state fixture, asserting the watchdog fault bit and
      `cycleOverrunCount_` are present and populated.
- [x] `python3 -m py_compile` passes on every `src/*.py`; `mpy-cross`
      lints every `src/*.py` clean.
- [x] `manifest.py` lists every `src/*.py` module — a diff/grep check
      against the actual `src/` directory listing confirms nothing is
      silently left on the filesystem-only path.
- [x] The teaching-framework loop-ownership question is either resolved
      (with the decision documented in `motion.py`'s module docstring)
      or explicitly escalated in this ticket's notes — not left
      ambiguous.

## Implementation Notes (added on completion)

- **RAM/flash delta**: the pre-freeze baseline hex from ticket 006 was
  not independently captured before this ticket's `--clean` run
  overwrote it (flagged, not fabricated) — ticket 009's M6 checkpoint
  should treat THIS ticket's post-freeze numbers as the new baseline
  going forward. Post-freeze (`./build.sh --clean --with-diffdrive
  --with-wifi`): `arm-none-eabi-size` reports `text=333212 data=8
  bss=126992`; `addlayouttable.py`'s layout: MicroPython
  `0x00000..0x5159c`, layout table `0x51fd0..0x52000`, filesystem
  `0x6d000..0x73000` — flash end (`0x5159c`) well under `_fs_start`
  (`0x6D000`).
- **Loop-ownership decision**: documented in full in `src/motion.py`'s
  module docstring — no `on_tick()` callback framework; plain function
  calls, framework-owned `MoveQueue.tick()` pumping via `comms.py`'s
  existing scheduled pump. Also records a known, deliberately deferred
  gap: `clasi/issues/generator-driven-control-loop-mode-addition-not-
  replacement.md` (status `pending`) proposes a second, additive
  generator-driven mode, but its prerequisite native bindings
  (`diffdrive.step()` etc.) have not landed as a follow-on ticket to
  004 — not built here, flagged for a future ticket.
- **Native binding scope**: `wheel_control_to_diffdrive_config()`
  (`src/config.py`) produces the full 15-field `DiffDrive::Config`
  mapping (tested against known input/output pairs), but
  `native/moddiffdrive.cpp`'s `configure()` binding still only accepts
  the 7 params it did after ticket 004 — pushing the 15 `wheel_control`
  fields into the real kernel needs a new native call
  (`native/README.md`'s own "ticket 007" pointer), deliberately not
  built in this pass (a `native/` C++ change with its own qstr/glue
  wiring, not required by this ticket's acceptance criteria). Flagged
  for a follow-on ticket.
- **GET_CONFIG wire delivery**: `config.ConfigDispatch` acks
  CONFIG/SET_FIELD/GET_CONFIG via the existing ack ring and additionally
  broadcasts a `CFG` reply frame to its own registered transports for
  GET_CONFIG (`comms.py`'s dispatch interface has no per-request
  transport/reply-frame channel to extend without modifying that
  ticket-005 module) — see `config.py`'s own docstring for the full
  reasoning.
- **GO_TO/CALIBRATE scope**: `MoveQueue.go_to()` is a simple, documented
  turn-then-drive decomposition (open-loop within each leg), not
  radio-robot-elite's evolved continuously-corrected `Motion::
  Navigator` (no equivalent exists in the vendored `DiffDrive` kernel).
  `CALIBRATE` is scoped to line-sensor `cal_min`/`cal_max` capture (the
  one calibration concept with a concrete reference,
  `line_sensor.h`'s own `captureCalibMin/Max`).

## Testing

- **Existing tests to run**: `tests/unit/test_wire_golden_vectors.py`,
  `tests/test_comms_loopback.py`, `tests/test_radio_shim_fragments.py`,
  `tests/test_wifi_at.py`, `tests/test_robot_config_data.py` — all
  should still pass unmodified.
- **New tests to write**: `tests/test_config.py`,
  `tests/test_motion.py`, `tests/test_telemetry.py`.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: build the five firmware-layer modules against the
dispatch interface ticket 005 defined and the native API ticket 004
exposed, consuming ticket 002's config data. Perform the manifest
freeze last, once all modules are stable, and re-run the full offline
suite plus `./build.sh --clean` to confirm the freeze didn't regress
anything.

**Files to create/modify**: `src/config.py`, `src/otos.py`,
`src/line.py`, `src/telemetry.py`, `src/motion.py`,
`src/codal_port/manifest.py` (or wherever this repo's manifest lives),
`tests/test_config.py`, `tests/test_motion.py`,
`tests/test_telemetry.py`.

**Testing plan**: as listed in Acceptance Criteria; full `python3 -m
pytest tests/` run before and after the manifest freeze.

**Documentation updates**: `motion.py`'s module docstring records the
loop-ownership decision; note the RAM/flash freeze delta somewhere
ticket 009 can reference it (e.g. a short note in this ticket or
`docs/`).
