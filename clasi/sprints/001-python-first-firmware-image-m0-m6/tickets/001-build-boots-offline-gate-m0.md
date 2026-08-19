---
id: '001'
title: Build boots offline gate (M0)
status: open
use-cases: [UC-001, UC-002]
depends-on: []
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Build boots offline gate (M0)

## Description

Repair/verify the forked build machinery so `./build.sh --clean`
produces a flashable hex in this repo. At sprint-planning time,
`micropython-microbit-v2/` — the upstream checkout `build.sh` expects
via `git -C micropython-microbit-v2 submodule update --init
--depth=1` — was confirmed **not present** locally: it's gitignored
(`.gitignore`: "vendored upstream MicroPython checkout (fetched by
build.sh)") and has never been fetched, so `build.sh`'s first real step
has nothing to operate on. `python3 -c "import intelhex"` also failed
in the planning environment (`intelhex` is a documented prerequisite in
`build.sh`'s header for `addlayouttable.py`).

PLAN.md and `docs/design/specification.md` pin the upstream source to
`micropython-microbit-v2` @ `0697c6d` (the same commit the prior
MicroPython exploration worktree built against — Gate 2 closed there:
no-SoftDevice link works, 132 KB flash headroom, GC heap 40 KB). This
ticket establishes that checkout, confirms `build.sh`'s patch engine
(`patches/apply_overlay.py`, `patches/apply_yield.py`,
`patches/modrobot_wire.patch`, `patches/yield.patch`) applies cleanly
on top of it, and produces a working hex — the M0 gate every later
milestone (especially M1, ticket 004) depends on.

This is the first ticket in the sprint; 002, 003, and 008 have no
dependency on it and may proceed in parallel, but everything from
ticket 004 onward needs a proven build.

## Acceptance Criteria

All criteria are offline. Flashing / USB REPL / `mbdeploy` verification
(the hardware leg of UC-002) is explicitly **not** part of this
ticket — it moves to ticket 009's documented stakeholder procedure.

- [ ] `micropython-microbit-v2/` exists locally, checked out at commit
      `0697c6d` (or a newer commit if `0697c6d` is unreachable/removed
      upstream — document the substitution and why if so), and stays
      gitignored (untracked by this repo, per `.gitignore`).
- [ ] `bash -n build.sh` passes.
- [ ] `python3 -c "import intelhex"` succeeds (install via `pip3
      install intelhex` if missing; document the requirement in
      README.md if `build.sh` doesn't self-bootstrap it).
- [ ] `./build.sh --clean` exits 0 and produces
      `micropython-microbit-v2/src/MICROBIT.hex`.
- [ ] The build's flash-end address (from the generated `.map`) is <
      `_fs_start` (0x6D000) — verified by a small offline check
      (script or documented grep/awk against the map output).
- [ ] `MICROPY_NLR_SETJMP` is `1` in the patched
      `micropython-microbit-v2/src/codal_port/mpconfigport.h` (grep
      check) — the non-negotiable landmine-ledger item; a HardFault on
      any exception without it.
- [ ] `codal_overlay.json`'s merged keys (`DEVICE_BLE=0`,
      `MICROBIT_BLE_ENABLED=0`, `MICROBIT_BLE_PARTIAL_FLASHING=0`,
      `MICROBIT_BLE_SECURITY_MODE=0`, `MICROBIT_RADIO_MAX_PACKET_SIZE=250`,
      `DEVICE_STACK_SIZE=8192`) are present in the resulting
      `codal_app/codal.json` after `patches/apply_overlay.py` runs.
- [ ] Re-running `./build.sh` (no `--clean`) exits 0 — sanity check
      that the incremental path works, no hard timing assertion.

## Testing

- **Existing tests to run**: none exist yet in this repo (greenfield
  ticket).
- **New tests to write**: an offline check script (or a small
  `tests/test_build_gate.py` invoked via `python3 -m pytest`, or a
  shell script under `tests/`) that runs the grep/map checks above
  after a `./build.sh --clean` so the gate is a single repeatable
  command, not a set of manual greps.
- **Verification command**: `./build.sh --clean && python3 -m pytest
  tests/test_build_gate.py` (or the equivalent shell-script gate,
  programmer's choice — must be a single named command per the
  sprint's offline-verifiable-acceptance-criteria constraint).

## Implementation Plan

**Approach**: Investigate why `build.sh`'s `git -C "$MP_DIR" submodule
update --init --depth=1` has nothing to act on (`MP_DIR` doesn't exist
as a git repo yet in a fresh checkout of this repo). Add a one-time
clone step — either inside `build.sh` itself (checked for idempotency:
skip if `micropython-microbit-v2/.git` already exists) or as a
documented pre-step in README.md — that clones the upstream
`micropython-microbit-v2` project and checks out `0697c6d` before
`build.sh`'s existing submodule-update and patch-application logic
runs. This matches `build.sh`'s own header comment about a fresh clone
reproducing the same upgraded state. Confirm `arm-none-eabi-gcc`
(already present, 15.2.1) and `cmake` are on `PATH`; install `intelhex`
if missing.

**Files to create/modify**:
- `build.sh` — add or document the initial clone step.
- `README.md` — note the clone step and `intelhex` prerequisite if not
  self-bootstrapped.
- `tests/test_build_gate.py` (or shell equivalent) — the offline gate
  script.

**Testing plan**: `bash -n build.sh`; `./build.sh --clean`; the new
offline gate check against the produced `.map` / `mpconfigport.h` /
`codal.json`.

**Documentation updates**: README.md's prerequisites section, if the
clone step isn't fully automated by `build.sh`.
