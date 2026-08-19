---
id: 009
title: Bench acceptance procedures + student-facing API contract (M6)
status: done
use-cases:
- UC-002
- UC-003
- UC-004
- UC-005
- UC-007
- UC-008
- UC-009
- UC-010
- UC-012
- UC-013
- UC-014
depends-on:
- '004'
- '006'
- '007'
github-issue: ''
issue:
- complete-gates-3-7-full-firmware-in-micropython-image.md
- test-on-microbit-tovez-radio-channel-3.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Bench acceptance procedures + student-facing API contract (M6)

## Description

This ticket's own output is documentation — it does not itself run any
hardware step. It writes down the procedures the **stakeholder**
executes on hardware, per the sprint's constraint that no hardware step
is a ticket acceptance criterion the programmer performs.

Write a bench acceptance procedures document (e.g.
`docs/bench-acceptance-procedures.md`) covering the full hardware
ladder in order, each step naming its exact command and the bench
fixture:

1. REPL wheel spin (smallest-visible-pulse first).
2. Watchdog/lease/reset safety triple: busy-wait stall → watchdog
   zeroes ≤300 ms; the polling-idiom stall (`while True: p =
   radio.receive()`) → same; reset mid-drive → boot zero-write
   silences. Encoder delta read from the other plane; explicit
   stop-verify (Δenc = 0 over 2 s).
3. `rogo repl <robot> ping` through the relay, with completely
   unchanged host tooling.
4. `wifi_bench_gate.py --port wifi: --skip-drive` 9/9, with a live `nc`
   REPL session held open throughout; power-cycle the WiFi module
   first (state persists across nRF reflashes).
5. `move_protocol_bench.py` full pass over the radio path; OTOS pose
   sane in telemetry.
6. The M6 sweep itself: quiet-host kill test (lease stops wheels),
   power-cycle boot-zero test, 10-minute dual-plane soak, RAM/flash
   checkpoint (comparing the pre-freeze and post-freeze heap from
   ticket 007's manifest-freeze switch), and radio-robot's own `git
   diff master -- src/firm` = diffdrive-only check — note explicitly
   that this last check runs in radio-robot, not this repo, and is out
   of this repo's own gate.

Every step names: bench = micro:bit **tovez**, radio **channel 3**,
deploy with **`mbdeploy`** (by UID only), ~5 s post-flash settle,
WiFi module power-cycled before WiFi work — the fixed bench convention
from issue `test-on-microbit-tovez-radio-channel-3.md`.

Also write the student-facing API contract note (spec §7.2 / open item
4): wheel control requires the Python program to reach
`microbit_hal_idle()` (return to the scheduler) — state this
explicitly, and document how the watchdog fault surfaces (telemetry
fault bit + display indication, from ticket 004) so a silent stop at
250 ms doesn't read as a hardware fault to a student debugging a drive
routine. If ticket 007 escalated the on_tick()-vs-`while True:`
open question rather than resolving it, this ticket documents whatever
was ultimately decided.

## Acceptance Criteria

- [x] A bench acceptance procedures doc exists, listing all six
      hardware-ladder steps above in order, each naming the exact
      command and the bench fixture (tovez, channel 3, `mbdeploy`,
      deploy-by-UID, ~5 s settle, WiFi power-cycle).
- [x] The doc explicitly separates "stakeholder executes this on
      hardware" from what tickets 001-008 already verified offline —
      it is a procedure to run, not a restatement of already-passing
      offline tests.
- [x] A student-facing API contract note exists (in the doc, or as
      `src/motion.py`/`src/comms.py` docstrings cross-referenced from
      the doc) stating the idle-reaching requirement and the watchdog
      visibility contract.
- [x] The doc references the RAM/flash checkpoint method (pre-freeze
      vs. post-freeze heap, from ticket 007).
- [x] The doc states that the `git diff master -- src/firm` =
      diffdrive-only check runs in radio-robot, not this repo.

## Testing

- **Existing tests to run**: none (doc-only ticket; its dependencies —
  tickets 004, 006, 007 — carry their own offline suites, unaffected
  here).
- **New tests to write**: none.
- **Verification command**: none applicable — documentation ticket;
  the acceptance criteria above are the gate.

## Implementation Plan

**Approach**: synthesize outputs/decisions from tickets 004
(watchdog/lease/API surface), 006 (WiFi bench-gate command and
power-cycle discipline), and 007 (freeze-point RAM/flash delta,
loop-ownership decision) together with PLAN.md's Verification section
and `docs/design/specification.md` §9 into a single ordered procedures
document. No code changes.

**Files to create/modify**: `docs/bench-acceptance-procedures.md` (new)
and/or docstring additions in `src/motion.py`/`src/comms.py` for the
student-facing contract note.

**Testing plan**: none — doc-only; acceptance is the criteria above.

**Documentation updates**: this ticket *is* the documentation update.

## Implementation Notes (added on completion)

- **Doc delivered**: `docs/bench-acceptance-procedures.md` — Part A is
  the six-step hardware ladder (§A.4–§A.9, each mapping 1:1 to the
  ticket description's numbered list); §A.0/§A.1 carry the offline/
  hardware separation (a table pointing each already-green offline gate
  back to its ticket/test file); §A.9 item 4 carries the RAM/flash
  checkpoint method and item 5 states the `git diff master -- src/firm`
  check runs in radio-robot. Part B is the student-facing API contract
  (§B.1 idle-reaching contract, §B.2 watchdog visibility, §B.3 lease
  semantics, §B.4 the API surface as built) — written as a
  cross-reference/summary of `src/motion.py`'s own module docstring
  (already fully resolved there, per ticket 007) rather than a fork of
  it, per the acceptance criterion's own "in the doc, or as ...
  docstrings cross-referenced from the doc" wording; no docstring edits
  were needed since ticket 007 already wrote the authoritative text.
- **Every command/API name was verified against the actual repo state**
  before being written down: `diffdrive`/`robotio`'s registered method
  tables (`native/moddiffdrive_glue.c`), `output()`'s exact dict keys
  (`native/moddiffdrive.cpp`), the lease/duration constants
  (`native/moddiffdrive.cpp`'s `kBindingLeaseMaxMs`, `native/watchdog.h`'s
  `kStallThresholdUs`, `src/motion.py`'s `MAX_MOVE_DURATION_MS`/
  `DEFAULT_LEASE_MS`/`TIMEOUT_GRACE_MS`), the telemetry field/flag names
  (`src/telemetry.py`'s `__all__`/`FLAG_WATCHDOG_FAULT`), the `build.sh`
  flags and hex output path, and tovez's own wiring values
  (`data/tovez.json`'s `motors`/`connection` groups) — no invented verb,
  flag, or field name.
- **Flagged gap, not fixed here (doc-only ticket)**: this repo has no
  on-device `main.py`/`boot.py` yet that assembles
  `config.load_robot_config()` + `diffdrive.configure/begin/start` +
  `comms.Comms` + a transport + `PumpTimer` into a running image at
  power-on — confirmed by grep (no `main.py`/`boot.py` in the repo; no
  call site anywhere outside `tests/` that constructs `comms.Comms(...)`
  or `radio_shim.RadioLink(...)`; `comms.PumpTimer`'s own docstring
  says its periodic source is "deliberately NOT hard-coded ... whichever
  a later ticket wires up," and no ticket has). Steps A.4/A.5 (REPL
  wheel spin, safety triple) are unaffected — `diffdrive`/`robotio` are
  always-present native modules. Steps A.6–A.9 (ping via relay,
  `wifi_bench_gate`, `move_protocol_bench`, the M6 sweep) need this
  wiring assembled at the REPL each bench session until a boot script
  ships; documented as a known gap in the new doc's §A.3, not silently
  glossed over. Flagging as a reasonable candidate for a follow-on
  ticket — not filed here, out of this doc-only ticket's scope.
- **RAM/flash checkpoint honesty note**: ticket 007's own completion
  notes flag that the true pre-freeze baseline (from ticket 006) was
  never independently captured — overwritten by ticket 007's own
  `--clean` run before being read. The new doc's §A.9 item 4 states
  this plainly rather than presenting a "delta" that was never actually
  measured: ticket 007's post-freeze numbers (`text=333212 data=8
  bss=126992`, flash end `0x5159c`) are the first real baseline this
  repo has, and the M6 checkpoint's job is to confirm a fresh `--clean`
  rebuild reproduces them (a regression check), not to compute a delta
  that has no earlier half to diff against.
