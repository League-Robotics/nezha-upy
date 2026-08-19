---
id: '002'
title: 'Zetuv bench: square tour wheels demo'
status: closed
branch: sprint/002-zetuv-bench-square-tour-wheels-demo
worktree: false
use-cases:
- UC-002
- UC-003
- UC-014
issues:
- zetuv-square-tour-wheels-demo.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 002: Zetuv bench: square tour wheels demo

## Goals

- Flash the micro:bit named **zetuv** with the current image and prove
  it boots to a live REPL with the native `diffdrive` module present.
- Derive `data/zetuv.json` (from `data/tovez_nocal.json`, the
  no-calibration template) and verify zetuv's actual motor port wiring
  and forward signs on the bench — zetuv has never been configured
  before, so these are unknown until measured.
- Drive a square tour on zetuv through this repo's own
  `motion`/`diffdrive` stack (not the host-driven planner, which
  cannot talk to this image yet) as a visible demonstration that the
  wheels move, mirroring radio-robot-elite's `TOUR_SQUARE` shape.
- Record everything verified on the bench (flash, REPL, wiring, tour)
  in a bench log so the result is reproducible evidence, not a claim.

## Problem

Sprint 001 built and verified the entire firmware stack offline; no
image has ever been flashed to real hardware and no wheel has ever
turned under this repo's code. zetuv is a micro:bit connected to the
bench right now, but it has no robot configuration anywhere (not in
this repo's `data/`, not in radio-robot-elite's) — its motor port
wiring and forward-sign convention are unknown. The host-driven tour
planner (`radio-robot-elite src/host/robot_radio/planner/tour.py`)
cannot run against this image yet because `src/msgs.py` has no binary
field tables (a known, accepted gap from sprint 001 — out of scope
here). The stakeholder wants direct, hands-on proof the wheels move,
via an on-device demo, before investing further in host-side tooling.

## Solution

Two tickets, strictly sequential: first establish a known-good config
and verified wiring on zetuv (bench work, hardware in scope per direct
stakeholder directive), then build a small on-device square-tour demo
on top of the now-trustworthy config and run it on zetuv. Both tickets
produce a bench-log entry recording what was actually observed on
hardware, alongside the offline checks (pytest suite, lint) that must
keep passing throughout.

## Success Criteria

- `data/zetuv.json` exists, derived from `tovez_nocal.json`, with
  every derived/unverified value honestly annotated as such in
  provenance notes, and validates against `data/robot_config.schema.json`
  like every other file in `data/`.
- zetuv is flashed (by UID only, `mbdeploy`, `--clean` build,
  `--with-diffdrive --with-wifi`, ~5 s settle) and answers on the USB
  REPL with the native `diffdrive` module importable.
- Bench wiring verification determines zetuv's actual
  `left_port`/`right_port`/`fwd_sign_left`/`fwd_sign_right` from
  encoder-delta observation under short (≤1000 ms), smallest-visible
  leases, and those measured values are written into
  `data/zetuv.json`, replacing the templated placeholders.
- A lease-expiry safety spot-check is recorded (wheels stop at lease
  expiry).
- A small, repeatable (single documented command) on-device demo
  drives zetuv through 4 × 500 mm legs + 4 × 90° left pivots
  (`TOUR_SQUARE`'s shape: rest-to-rest, ~1.2 s settle between
  segments, omega_max 2.4 rad/s), run through this repo's `motion`/
  `diffdrive` stack.
- The demo is actually run on zetuv and the observation (wheels moved,
  path was square-ish) is recorded in a bench log.
- `python3 -m pytest tests/` stays green throughout (193 baseline:
  187 from sprint 001 plus whatever this sprint's own offline tests
  add); `mpy-cross` lints the new demo module.

## Scope

### In Scope

- Deriving and bench-verifying `data/zetuv.json`.
- Flashing zetuv and confirming REPL/`diffdrive` availability.
- An on-device square-tour demo script driven through the existing
  `motion`/`diffdrive` stack.
- A bench log recording what was observed on hardware.
- Hardware execution — explicitly in scope for this sprint per direct
  stakeholder directive (2026-08-19), unlike sprint 001.

### Out of Scope

- The host-driven tour planner (`tour.py`/`TOUR_SQUARE` running
  against this image via the wire protocol) — blocked on `msgs.py`
  binary field tables, a separate, not-yet-ticketed gap.
- Any change to `vendor/`, the native module, the wire codec, the
  protocol engine, the WiFi transport, or config/telemetry/motion
  logic themselves — this sprint consumes sprint 001's stack as-is.
- getez, zavaz, or any robot other than zetuv — deploy by UID to zetuv
  only; `mbdeploy`'s relay refusal (`--force-relay`) is never
  overridden.
- Calibration beyond wiring/sign verification (travel calibration,
  OTOS/line tuning) — `zetuv.json` stays a no-calibration profile this
  sprint, same tier as its `tovez_nocal.json` template.

## Test Strategy

Bench observations (flash success, REPL answer, wiring signs, lease
safety, tour execution) are recorded in a bench log as this sprint's
primary evidence — they are hardware facts, not something a test
suite asserts. Alongside that, the existing offline suite
(`python3 -m pytest tests/`) must stay green throughout both tickets,
and the new demo module gets its own `mpy-cross` lint pass, consistent
with sprint 001's offline-verification discipline. No existing test is
expected to change; `data/zetuv.json` is validated against the schema
the same way `tests/test_robot_config_data.py` already validates every
other `data/*.json` file.

## Architecture

**Sizing: Compact.** This sprint adds one new module (an on-device
demo script) and one new config-data instance
(`data/zetuv.json`, conforming to the existing
`robot_config.schema.json` — the same schema `tovez.json`/`gopiv.json`/
`togov.json` already use, not a new data model). No new cross-module
dependency is introduced (the demo consumes `motion`/`diffdrive`
exactly as `comms.py`'s existing dispatch already does), no dependency
direction changes, and no data model changes. Sprint 001's module
architecture (Build Machinery, moddiffdrive Native Module, Wire Codec,
v5 Protocol Engine, WiFi Transport, Python Firmware Layer, Robot
Configuration Data, Boot Wiring, Acceptance & Process Docs) is
unchanged by this sprint — additive only, per direct instruction. No
diagrams: a single-module addition with no new cross-module dependency
has nothing a diagram would clarify beyond the purpose statement
below.

### Architecture Overview

**What changed**: one new module, **Demo Script** (e.g.
`src/demo_square.py`), plus one new instance of the existing Robot
Configuration Data module (`data/zetuv.json`).

**Purpose (one sentence, no "and")**: the Demo Script drives a
pre-programmed square path through the existing `motion`/`diffdrive`
stack as a runnable, repeatable demonstration.

**Boundary**: inside — the fixed sequence of legs/pivots and the
single entry point that runs it; outside — everything it drives
(`motion.MoveQueue` if it can express the tour's shape, `diffdrive`
directly for timed legs otherwise; the programmer implementing ticket
002 grounds this choice in what `motion.py` actually supports rather
than assuming). It owns no protocol, drive-law, or config logic itself
— it is a caller, not an owner, of the modules sprint 001 already
built.

**Use cases**: UC-002 (boots to a live REPL — zetuv must reach one
before either ticket can proceed), UC-003 (student/operator drives
wheels — the demo is exactly this, scripted), UC-014 (a bench
acceptance-style verification, scoped to this sprint's own hardware
rather than the full M6 sweep).

### Design Rationale

**Decision: derive `zetuv.json` from `tovez_nocal.json`, not
`tovez.json`.** *Context*: zetuv has no prior configuration, and two
templates exist — `tovez.json` (fully calibrated) and
`tovez_nocal.json` (the explicit no-calibration baseline profile).
*Why*: zetuv's hardware has never been measured; carrying over
`tovez.json`'s camera-fitted calibration values (rotation gain/offset,
duty-per-speed, etc.) onto unverified hardware would silently present
fitted numbers as if they applied to a different physical robot. The
no-calibration template's vanilla gains are honest about what is and
isn't known. *Consequences*: `zetuv.json`'s motion will be
uncalibrated (fine for a square-ish demo; not appropriate for anything
requiring calibrated position control) — flagged explicitly in
`zetuv.json`'s own provenance notes and in the bench log, not silently
implied.

**Decision: the demo is on-device, not host-driven.** *Context*: the
issue's recon already established `tour.py`/`TOUR_SQUARE` cannot run
against this image (`msgs.py` lacks binary field tables). *Why not
build that now*: it is materially larger scope (protobuf-style field
tables for every binary verb) than "demonstrate the wheels move," and
is better sized as its own sprint once there's a concrete driver for
it. *Consequences*: the demo mirrors `TOUR_SQUARE`'s numbers (leg
length, pivot angle, settle time, omega_max) without being driven by
the same code — an intentional, documented divergence, not an
oversight.

### Migration Concerns

None. This sprint adds a config instance and a demo script; it changes
no existing module's behavior, interface, or data model. The one
sequencing concern is soft, not a migration: ticket 002 depends on
ticket 001's bench-verified wiring signs being correct, since a wrong
sign would make the "square" tour visibly wrong on hardware (a bench
observation, not a code risk).

## Use Cases

This sprint does not introduce new functional behavior beyond what
`docs/design/usecases.md` already defines — it exercises existing use
cases on a specific, previously-unconfigured robot. Rather than
duplicate their text, this section maps them to this sprint's tickets:

| UC | Title | Actor | Delivered by | Notes |
|---|---|---|---|---|
| UC-002 | Flash and boot to a live REPL | Developer/Stakeholder | 001 | Executed on zetuv specifically, by UID, per bench conventions |
| UC-003 | Student drives wheels from the REPL | Student | 001, 002 | 001 exercises it directly (wiring-verification pulses); 002 exercises it via the scripted demo |
| UC-014 | Stakeholder acceptance sweep (M6) | Stakeholder | 001, 002 | Scoped down to this sprint's own bench log, not the full M6 sweep (WiFi/telemetry/soak are out of scope here) |

## GitHub Issues

(None — this sprint's issue is a CLASI-local `clasi/issues/` file, not
a GitHub issue.)

## Definition of Ready

Before tickets can be created, all of the following must be true:

- [x] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [x] Architecture review passed (or skipped, for changes with no
      architectural impact)
- [x] Stakeholder has approved the sprint plan (direct directive
      2026-08-19: "flash zetuv... get the square tour running so that
      we can demonstrate that the wheels move")

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | zetuv config + flash + REPL wiring verification | — |
| 002 | On-device square tour demo | 001 |

Tickets execute serially in the order listed.
