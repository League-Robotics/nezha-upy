---
id: '001'
title: 'zetuv config + flash + REPL wiring verification'
status: open
use-cases: [UC-002, UC-003]
depends-on: []
github-issue: ''
issue: zetuv-square-tour-wheels-demo.md
completes_issue: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# zetuv config + flash + REPL wiring verification

## Description

zetuv is a micro:bit connected to the bench right now (`mbdeploy list`
→ `/dev/cu.usbmodem2121202`, UID
`9906360200052820312bde85515a72e6000000006e052820`) but has never been
configured or flashed with this repo's image. Its motor port wiring
and forward-sign convention are unknown. **Hardware execution is
explicitly in scope for this ticket**, per direct stakeholder
directive — unlike sprint 001, where every hardware step was deferred
to a stakeholder-run procedure.

**Deploy target discipline (safety-critical, not a style note)**:
getez and zavaz are also connected to the bench. Deploy by **UID**
(never board name alone) to zetuv **only**. getez may be a relay-class
board — `mbdeploy` refuses relays without `--force-relay`; **never
pass that flag**. If `mbdeploy` refuses a target for any reason, stop
and investigate rather than working around the refusal.

**Steps**:

1. Derive `data/zetuv.json` from `data/tovez_nocal.json` (the
   no-calibration template — see sprint.md's Design Rationale for why
   not `tovez.json`). Update `identity`/`connection` fields for zetuv;
   leave calibration-dependent fields (`geometry`, `drive` gains,
   `wheel_control`) at the template's vanilla no-cal values. Annotate
   every derived-not-measured value with a provenance note (matching
   `data/README.md`'s existing one-time-copy provenance convention
   from sprint 001 ticket 002) so nothing reads as verified when it
   isn't.
2. `./build.sh --clean --with-diffdrive --with-wifi` — a fresh build
   before hardware verify, per bench convention.
3. Deploy to zetuv **by UID only** via `mbdeploy`. Wait ~5 s
   post-flash settle. (WiFi module power-cycle is not needed for this
   USB-only ticket — no WiFi work happens here.)
4. Boot is fail-closed without `/robot.json` on the device filesystem
   (REPL stays live; the native `diffdrive` API is still reachable
   even with no config loaded — this is sprint 001 ticket 010's
   documented fail-closed contract, not new behavior). Put zetuv's
   derived config on the device filesystem as `/robot.json` (`mpremote
   fs cp`) or configure it interactively from the REPL — either is
   acceptable; record which was used in the bench log.
5. REPL smoke test: connect, confirm the banner/prompt answers, and
   confirm `import diffdrive` (or the equivalent native-module probe)
   succeeds.
6. **Wiring verification**, smallest-visible-pulse first, every lease
   ≤1000 ms:
   - Command a short, low-duty pulse on one wheel at a time (e.g. via
     `diffdrive.driveDuty(...)` with a short lease) and observe which
     physical wheel moves and which direction, to determine the actual
     `left_port`/`right_port` mapping and `fwd_sign_left`/
     `fwd_sign_right` values — encoder deltas are the ground truth, not
     which wheel *looks* like it should be left.
   - Update `data/zetuv.json`'s `motors` block with the measured
     values, replacing the templated placeholders inherited from
     `tovez_nocal.json`.
7. **Safety spot-check**: command a short lease, let it expire without
   renewal, and confirm the kernel zeroes duty at expiry (mirrors
   sprint 001's M1 safety-triple concept, scoped to a single
   observation here — the full triple, including the starvation
   watchdog and reset-mid-drive cases, was already verified on tovez
   in sprint 001 and is not re-run per-robot).
8. Record every observation from steps 3-7 in a bench log (a new
   `docs/bench-log-zetuv.md`, or a dated section appended to
   `docs/bench-acceptance-procedures.md` — programmer's choice,
   documented either way): flash result, REPL/diffdrive presence,
   measured wiring/sign values, the safety spot-check result.

## Acceptance Criteria

This ticket's acceptance is a mix of hardware bench observations
(recorded, not simulated) and offline checks:

- [ ] `data/zetuv.json` exists, derived from `data/tovez_nocal.json`,
      with provenance notes on every derived/unverified value.
- [ ] `data/zetuv.json` validates against `data/robot_config.schema.json`
      the same way `tests/test_robot_config_data.py` validates every
      other `data/*.json` file (extend that test to cover zetuv.json).
- [ ] Bench log records: `./build.sh --clean --with-diffdrive
      --with-wifi` succeeded; `mbdeploy` deploy to zetuv by UID
      succeeded (UID recorded); ~5 s settle observed; REPL answered;
      `diffdrive` importable.
- [ ] Bench log records the measured `left_port`/`right_port`/
      `fwd_sign_left`/`fwd_sign_right` values and how they were
      determined (which pulse produced which observed motion).
- [ ] `data/zetuv.json`'s `motors` block reflects those measured
      values (not the template's placeholders).
- [ ] Bench log records the lease-expiry safety spot-check result
      (wheels stopped at expiry).
- [ ] `python3 -m pytest tests/` stays green (187 baseline from sprint
      001 plus this ticket's own `data/zetuv.json` schema-validation
      addition).
- [ ] getez/zavaz were never targeted; `--force-relay` was never
      passed — confirmed by the bench log recording the exact
      `mbdeploy` invocation used (by UID).

## Testing

- **Existing tests to run**: full `python3 -m pytest tests/` suite
  (187-passed baseline from sprint 001) — must stay green.
- **New tests to write**: extend `tests/test_robot_config_data.py` (or
  add a parallel test) to validate `data/zetuv.json` against the
  schema, matching the existing per-robot validation pattern.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: config derivation and schema-validation test first
(fully offline, no hardware needed), then the hardware sequence
(build → flash → REPL smoke → wiring verification → safety
spot-check), each step's observation written into the bench log as it
happens rather than reconstructed afterward.

**Files to create/modify**: `data/zetuv.json` (new), a bench log file
(`docs/bench-log-zetuv.md` or an appended section — programmer's
choice), `tests/test_robot_config_data.py` (extended).

**Testing plan**: `python3 -m pytest tests/` before and after the
config addition; the hardware steps are observed and logged, not
asserted by an automated test.

**Documentation updates**: the bench log itself; a one-line note in
`data/README.md` if the zetuv-derivation provenance convention adds
anything not already covered by the existing gopiv/tovez provenance
notes.
