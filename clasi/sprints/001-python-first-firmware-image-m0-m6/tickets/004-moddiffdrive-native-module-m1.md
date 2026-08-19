---
id: '004'
title: moddiffdrive native module (M1)
status: done
use-cases:
- UC-002
- UC-003
- UC-004
- UC-005
- UC-008
- UC-012
- UC-015
depends-on:
- '001'
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# moddiffdrive native module (M1)

## Description

**Highest-risk ticket in the sprint — nothing in tickets 005-009
proceeds until this scores**, per PLAN.md's explicit sequencing.

Build `native/moddiffdrive.cpp` + a glue file + manual qstrs (the
proven two-file pattern referenced in `reference/modrobot/
{modrobot.cpp,modrobot_glue.c}`, adapted for the DiffDrive kernel API
instead of the old modrobot surface), compiling the vendored
`vendor/differential_drive.{h,cpp}` + `vendor/nezha_motor.{h,cpp}` +
`vendor/motor_armor.h` kernel **in place, never edited**.

Implement:
- Kernel leaves (Clock/Sleeper/Launcher) on a CODAL fiber
  (`FiberLauncher`→`create_fiber`), using the `microbit_hal_idle()`
  yield patch already vendored as `patches/apply_yield.py`/
  `patches/yield.patch` — verify this ticket wires it in correctly
  rather than re-deriving it; `docs/nezha-upy-review.md` §1 (spec §7.1)
  closes the question of any alternative hook point permanently — do
  not attempt one.
- One shared I2C ledger: all Python sensor traffic must route through
  the module's `robotio.i2c_xfer()` so per-device `lastEnd/readyAt`
  timers and the TWIM-errata gap are shared with the kernel's own 0x10
  traffic.
- Boot zero-write, executed before the VM starts.
- A zero-only starvation watchdog in the VM hook: never yields, raw
  zero-duty write (retry x2), latches a fault flag. Per review §2
  (spec §7.2), this must cover **both** trigger shapes as a design
  requirement from this ticket, not deferred: the busy-wait (`while
  True: pass`) and the realistic polling idiom (`while True: p =
  radio.receive()` — returns immediately, allocates every call, never
  reaches idle). The watchdog must be **visible**: surface
  `cycleOverrunCount_` in telemetry from this ticket (not M5, per
  review §7.5 — it's the only direct evidence of cadence loss during
  the riskiest milestone).
- 5000 ms lease ceiling enforced in the binding (reject, don't clamp,
  a longer lease).
- Python API: `diffdrive.configure/begin/start/drive/driveDuty/
  neutral/estop/output/lastError`.

The gopiv wiring-fix *values* live in config data (ticket 002); this
ticket's binding only needs to accept `left_port`/`right_port`/sign
parameters generically — the actual config-to-kernel wiring is ticket
007's job.

**The kernel stays on its CODAL fiber this sprint.** The `step()`
re-entrant-state-machine / pended-SWI restructure documented in review
§3 is explicitly **out of scope** here — it is a `vendor/` change that
belongs in radio-robot under `src/tests/diffdrive/`, contingent on how
the (stakeholder-run) M1 safety triple reads. Do not attempt it.

## Acceptance Criteria

All criteria are offline. The three hardware legs of PLAN.md's M1 gate
— (2) `drive()` with a 1000 ms lease produces motion with correct
encoder signs, (3) the busy-wait and polling-idiom safety cases plus
the reset-mid-drive boot-zero-write case — move to ticket 009's
documented stakeholder procedure. Leg (1)'s radio-robot-side
`pytest src/tests/diffdrive/` run is out of scope for this repo (gated
by radio-robot's own suite); this ticket owns leg (1)'s vendor
sync-diff-clean half.

- [x] `./build.sh --clean` with the native module wired in (a new
      `--with-diffdrive` flag, mirroring the existing
      `--with-modrobot` flag) exits 0 and links `moddiffdrive` into
      the hex; flash end still < `_fs_start`.
- [x] `git diff --exit-code -- vendor/` is empty — confirms no local
      kernel edits (the sync-diff-clean gate leg owned by this repo).
- [x] Source review confirms the full API surface is bound:
      `configure`, `begin`, `start`, `drive`, `driveDuty`, `neutral`,
      `estop`, `output`, `lastError`, each registered in the module's
      method table.
- [x] Source review confirms the boot zero-write executes before
      `mp_init`/VM start (trace the init ordering in `native/`).
- [x] Source review confirms the VM-hook watchdog path calls no
      yield/fiber-switch primitive (consistent with review §1's "no
      point inside VM execution where the stack is not load-bearing"
      finding), and that its design/comments explicitly cover both the
      busy-wait and the `radio.receive()`-polling trigger shapes — the
      250 ms-stall timing itself is hardware-verified (ticket 009), not
      asserted here.
- [x] Source review confirms the 5000 ms lease ceiling constant is
      present and **enforced** (rejects, doesn't clamp, a longer
      lease) in the binding.
- [x] `cycleOverrunCount_` is incrementing and readable from Python
      (at minimum via a raw accessor on the `diffdrive` module — full
      telemetry-frame integration is ticket 007's job, but the counter
      itself must exist and be exposed here).

## Testing

- **Existing tests to run**: none in this repo; radio-robot's `src/
  tests/diffdrive/` is out of scope (run by radio-robot's own gate,
  not this repo).
- **New tests to write**: no CPython unit-test framework applies to
  the native C binding itself — acceptance here is build-success plus
  source-review/grep-based verification, as listed above, consistent
  with the sprint's offline-verifiable-acceptance constraint.
- **Verification command**: `./build.sh --clean --with-diffdrive &&
  git diff --exit-code -- vendor/`

## Implementation Plan

**Approach**: port the two-file binding pattern from
`reference/modrobot/{modrobot.cpp,modrobot_glue.c}`, replacing the old
modrobot surface with calls into `vendor/differential_drive.h`'s public
API. Consult `patches/apply_yield.py`/`patches/yield.patch` for the
existing yield-patch wiring the M0 build already applies — reuse it,
don't reimplement it.

**Files to create/modify**: `native/moddiffdrive.cpp`,
`native/moddiffdrive_glue.c` (or equivalent split), qstr registration
file, a new `--with-diffdrive` flag in `build.sh` wiring `native/` +
`vendor/` into the CMake/Makefile build (mirroring `--with-modrobot`).

**Testing plan**: the offline criteria above; no unit-test framework
for the C binding, so acceptance is build-success + source-review.

**Documentation updates**: `native/README.md` — the API surface, lease
ceiling, and watchdog trigger shapes, so ticket 007 and ticket 009 can
consume/document them without re-reading the C source.
