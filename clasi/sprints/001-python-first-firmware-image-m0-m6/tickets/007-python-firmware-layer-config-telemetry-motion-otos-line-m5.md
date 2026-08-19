---
id: '007'
title: 'Python firmware layer: config/telemetry/motion/otos/line (M5)'
status: open
use-cases: [UC-011, UC-012, UC-013]
depends-on: ['002', '004', '005', '006']
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

- [ ] `./build.sh --clean` (now with the manifest freeze applied) exits
      0, still flash end < `_fs_start`; note the RAM/flash delta from
      freezing (compare against ticket 006's last pre-freeze build) for
      ticket 009's M6 checkpoint procedure to reference.
- [ ] `src/config.py`'s fail-closed key validation is unit-tested
      offline (`tests/test_config.py`) against `data/tovez.json`,
      `data/gopiv.json`, and a deliberately-malformed fixture (missing
      a required key), asserting refusal on the malformed case.
- [ ] The same test asserts `wheel_control` → `DiffDrive::Config`
      mapping (`travel_calib`×10) against known input/output pairs.
- [ ] `src/motion.py`'s queue/stop-condition/timeout-fault/replace
      logic is unit-tested offline (`tests/test_motion.py`) against a
      stub diffdrive backend, with an explicit regression assertion
      that durations are treated as milliseconds, not seconds.
- [ ] `src/telemetry.py`'s 22-field frame assembly is unit-tested
      offline (`tests/test_telemetry.py`) against a synthetic
      sensor/kernel-state fixture, asserting the watchdog fault bit and
      `cycleOverrunCount_` are present and populated.
- [ ] `python3 -m py_compile` passes on every `src/*.py`; `mpy-cross`
      lints every `src/*.py` clean.
- [ ] `manifest.py` lists every `src/*.py` module — a diff/grep check
      against the actual `src/` directory listing confirms nothing is
      silently left on the filesystem-only path.
- [ ] The teaching-framework loop-ownership question is either resolved
      (with the decision documented in `motion.py`'s module docstring)
      or explicitly escalated in this ticket's notes — not left
      ambiguous.

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
