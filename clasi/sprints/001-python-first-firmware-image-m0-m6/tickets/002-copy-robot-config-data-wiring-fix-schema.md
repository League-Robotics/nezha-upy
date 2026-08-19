---
id: '002'
title: Copy robot config data + wiring fix + schema
status: open
use-cases: [UC-011, UC-002]
depends-on: []
github-issue: ''
issue:
- copy-robot-configurations-from-radio-robot-elite.md
- complete-gates-3-7-full-firmware-in-micropython-image.md
- test-on-microbit-tovez-radio-channel-3.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Copy robot config data + wiring fix + schema

## Description

Copy `robot_config.schema.json`, `tovez.json`, `tovez_nocal.json`,
`gopiv.json`, `togov.json`, and `active_robot.json` from
`/Volumes/Proj/proj/RobotProjects/radio-robot-elite/data/robots` into
this repo's `data/`.

Per the sprint's Architecture Design Rationale, this is a **one-time
copy, not a synced/vendored directory**: radio-robot-elite has no
export tooling for this purpose, building one is out of scope
(radio-robot-side work), and this repo's `config.py` (ticket 007) is
expected to evolve the schema/validation independently, which conflicts
with a never-edit vendor convention. Record the copy's provenance
(source path, copy date, "not synced — see sprint 001 Architecture
Design Rationale") in `data/README.md` so a future maintainer doesn't
assume it auto-updates.

Verify — do not assume — that `gopiv.json` already carries the true
wiring fix (`left_port: 2, right_port: 1, fwd_sign_left: +1,
fwd_sign_right: -1`, per `gopiv.json`'s own `_port_note` referenced in
`docs/design/specification.md` §8); if the source file lacks it, apply
it as part of this copy and note the deviation from the source.
Similarly verify `tovez.json` designates radio channel 3 (the bench
convention fixed by issue
`test-on-microbit-tovez-radio-channel-3.md`); set it explicitly if the
source file doesn't already, and note why in `data/README.md`.

## Acceptance Criteria

- [ ] `data/robot_config.schema.json`, `data/tovez.json`,
      `data/tovez_nocal.json`, `data/gopiv.json`, `data/togov.json`,
      `data/active_robot.json` exist, copied from
      `radio-robot-elite/data/robots`.
- [ ] Every copied JSON file parses cleanly (`python3 -m json.tool
      data/<file>.json` for each, or an equivalent batch check).
- [ ] Every per-robot JSON file (`tovez.json`, `tovez_nocal.json`,
      `gopiv.json`, `togov.json`) validates against
      `data/robot_config.schema.json` (an offline validator test using
      `jsonschema` if available, or a hand-rolled required-key check if
      not).
- [ ] `data/gopiv.json` contains `left_port: 2, right_port: 1,
      fwd_sign_left: 1, fwd_sign_right: -1` (asserted, not just
      eyeballed).
- [ ] `data/tovez.json` specifies radio channel 3.
- [ ] `data/README.md` documents the one-time-copy provenance and any
      deviations applied (wiring fix, channel designation) from the
      radio-robot-elite source.
- [ ] `git diff --exit-code -- vendor/` remains empty (this ticket
      touches only `data/`).

## Testing

- **Existing tests to run**: none yet in this repo.
- **New tests to write**: `tests/test_robot_config_data.py` (CPython,
  `python3 -m pytest`) asserting: all files parse; all per-robot files
  validate against the schema; the gopiv wiring-fix values; the tovez
  channel-3 value.
- **Verification command**: `python3 -m pytest
  tests/test_robot_config_data.py`

## Implementation Plan

**Approach**: straightforward file copy from
`/Volumes/Proj/proj/RobotProjects/radio-robot-elite/data/robots` into
this repo's `data/`, followed by the verification/correction pass
described above and a small offline validation test. No dependency on
the build (ticket 001) or any other ticket — can run first or in
parallel.

**Files to create/modify**: `data/robot_config.schema.json`,
`data/tovez.json`, `data/tovez_nocal.json`, `data/gopiv.json`,
`data/togov.json`, `data/active_robot.json`, `data/README.md`,
`tests/test_robot_config_data.py`.

**Testing plan**: `python3 -m pytest tests/test_robot_config_data.py`.

**Documentation updates**: `data/README.md` (provenance note).
