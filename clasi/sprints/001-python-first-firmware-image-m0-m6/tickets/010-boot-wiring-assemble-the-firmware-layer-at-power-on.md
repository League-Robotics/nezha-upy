---
id: '010'
title: 'Boot wiring: assemble the firmware layer at power-on'
status: done
use-cases:
- UC-002
- UC-011
- UC-007
depends-on:
- '007'
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Boot wiring: assemble the firmware layer at power-on

## Description

**Gap found during ticket 009's grounding pass**: nothing on-device
assembles the firmware layer at power-on. Every module from tickets
004-007 exists and passes its own offline gate, but no boot module
wires `config.load_robot_config()` → `diffdrive.configure/begin/
start` → `comms.Comms` → transports (`radio_shim`; `wifi_at` only when
`wifi_secrets.json` is present) → `comms.PumpTimer` into a running
image. `comms.PumpTimer`'s timer source is unwired — nothing schedules
the pump. As a direct consequence, `docs/bench-acceptance-procedures.md`
§A.3 currently documents that steps 3-6 (relay ping, WiFi bench gate,
move-protocol bench, the M6 sweep) require **manual REPL assembly each
session** — the stakeholder has to hand-wire the engine from the REPL
every bench run instead of it just being there at boot.

This is spec-implied, not new scope: `docs/design/specification.md`
§5 says the image *boots into* the v5 engine (banner/boot/READY,
scheduled pump off a timer) — that's a description of runtime
behavior at power-on, not of something a human assembles manually.
§6's M3 milestone gate names the "banner/boot/READY sequence" as part
of what M3 delivers. §6's M5 gate names a "fail-closed boot test": bad
config → motion refused, REPL still available — a boot-time behavior
that has no boot-time code to test yet. Tickets 004-007 each built the
piece their own milestone owns; none of them owned assembling the
pieces together at boot, and the sprint's original ticket breakdown
missed that seam.

**Deliverable**: a frozen boot module — `src/main.py` in the manifest,
or whatever hook `micropython-microbit-v2`'s port actually uses to run
frozen code at boot (confirm which by reading the port's boot sequence
rather than assuming `main.py` is correct by convention; ticket 007
already established the manifest-freeze mechanism this hooks into) —
performing, at power-on:

1. Load the robot's JSON config, **fail-closed** (bad/missing required
   key → motion refused, matching the M5 gate's fail-closed boot
   test).
2. `diffdrive.configure(...)`, `.begin()`, `.start()` against that
   config (only if config load succeeded — a fail-closed config must
   not proceed to arm the kernel).
3. Bring up `comms.Comms` and the radio transport (`radio_shim`)
   unconditionally; bring up the WiFi transport (`wifi_at`) **only
   when `wifi_secrets.json` is present** — its absence is not a boot
   failure, WiFi is simply not started (matches this project's
   no-secrets-in-repo convention: secrets are provided locally at
   bench time, never committed).
4. Start the scheduled pump (`comms.PumpTimer`), wiring its actual
   timer source — this is the concrete unwired piece named in the gap
   report.
5. Emit the banner/boot/READY sequence.
6. **Boot must not block.** The USB REPL stays fully interactive
   throughout and immediately after — a student can `Ctrl-C` into a
   live REPL at any point, matching UC-002's postcondition and the
   scheduled-pump design already established in ticket 005 (bounded
   work per pump call, between-bytecodes).

Update `docs/bench-acceptance-procedures.md` §A.3 as part of this
ticket to reflect that boot wiring now exists — remove or rewrite the
manual-REPL-assembly instructions steps 3-6 currently depend on, since
the stakeholder's hardware runs no longer need to hand-assemble the
engine each session.

## Acceptance Criteria

All criteria are offline, consistent with the sprint's
offline-verifiable-acceptance constraint; boot behavior on real
hardware is exercised by the stakeholder via the now-updated bench
procedures, not asserted here.

- [x] A boot module exists in the frozen manifest (`src/main.py` or
      the correct port-specific hook — confirmed by reading
      `micropython-microbit-v2`'s actual boot sequence, not assumed)
      performing the six steps above in order.
- [x] CPython boot-sequence unit tests
      (`tests/test_boot_sequence.py`, `python3 -m pytest`) cover:
  - [x] **Happy path**: valid config → diffdrive configured/begun/
        started, comms + radio transport up, pump started, banner/
        READY emitted.
  - [x] **Fail-closed path**: invalid/missing-required-key config →
        motion refused (diffdrive never armed), comms/REPL still
        available (banner still emits or an equivalent fail-closed
        diagnostic state is reachable), matching the M5 gate's
        fail-closed boot test.
  - [x] **No-secrets path**: `wifi_secrets.json` absent → WiFi
        transport is not started, everything else (config, diffdrive,
        radio, pump, banner) proceeds normally — absence of secrets is
        not a boot failure.
- [x] `./build.sh --clean --with-diffdrive --with-wifi` exits 0 with
      the boot module frozen into the manifest; flash end still <
      `_fs_start` (0x6D000).
- [x] `python3 -m pytest tests/` is green at the full-suite baseline
      (187 passed prior to this ticket) plus the new boot-sequence
      tests — no regressions in any ticket 001-009 suite.
- [x] `python3 -m py_compile` passes on the boot module; `mpy-cross`
      lints it clean (labelled as a lint, consistent with tickets
      003/005/006/007's mpy-cross-is-lint framing).
- [x] `docs/bench-acceptance-procedures.md` §A.3 is updated to reflect
      that boot wiring now exists — the manual-REPL-assembly steps it
      currently documents for steps 3-6 are removed or rewritten to
      describe power-on-and-verify instead of assemble-then-verify.

## Testing

- **Existing tests to run**: the full existing suite —
  `tests/unit/test_wire_golden_vectors.py`,
  `tests/test_comms_loopback.py`, `tests/test_radio_shim_fragments.py`,
  `tests/test_wifi_at.py`, `tests/test_robot_config_data.py`,
  `tests/test_config.py`, `tests/test_motion.py`,
  `tests/test_telemetry.py`, plus whatever ticket 009 added — all
  must remain green (187-passed baseline).
- **New tests to write**: `tests/test_boot_sequence.py` (happy path,
  fail-closed path, no-secrets path, as listed above).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: read how `micropython-microbit-v2` actually runs frozen
code at boot (confirm the real hook — `main.py` convention vs.
whatever this port specifically uses) before writing the module, since
getting this wrong would silently produce a boot module that never
runs. Wire the six steps in order, using the interfaces tickets
004-007 already established (`config.load_robot_config()`,
`diffdrive.configure/begin/start`, `comms.Comms`, `radio_shim`,
`wifi_at`, `comms.PumpTimer`) rather than reaching around them. Keep
the boot module itself thin — it assembles, it does not reimplement
any of the logic those modules already own.

**Files to create/modify**: the boot module (`src/main.py` or
port-correct equivalent), `src/codal_port/manifest.py` (add it to the
freeze list, alongside what ticket 007 already froze),
`tests/test_boot_sequence.py`, `docs/bench-acceptance-procedures.md`
(§A.3).

**Testing plan**: `python3 -m pytest tests/` (full suite);
`./build.sh --clean --with-diffdrive --with-wifi`.

**Documentation updates**: `docs/bench-acceptance-procedures.md` §A.3,
as described above — this is part of the ticket's own acceptance
criteria, not an optional follow-up.
