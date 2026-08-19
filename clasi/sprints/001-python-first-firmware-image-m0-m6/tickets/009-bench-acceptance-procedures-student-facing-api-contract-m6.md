---
id: '009'
title: Bench acceptance procedures + student-facing API contract (M6)
status: open
use-cases: [UC-002, UC-003, UC-004, UC-005, UC-007, UC-008, UC-009, UC-010, UC-012, UC-013, UC-014]
depends-on: ['004', '006', '007']
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

- [ ] A bench acceptance procedures doc exists, listing all six
      hardware-ladder steps above in order, each naming the exact
      command and the bench fixture (tovez, channel 3, `mbdeploy`,
      deploy-by-UID, ~5 s settle, WiFi power-cycle).
- [ ] The doc explicitly separates "stakeholder executes this on
      hardware" from what tickets 001-008 already verified offline —
      it is a procedure to run, not a restatement of already-passing
      offline tests.
- [ ] A student-facing API contract note exists (in the doc, or as
      `src/motion.py`/`src/comms.py` docstrings cross-referenced from
      the doc) stating the idle-reaching requirement and the watchdog
      visibility contract.
- [ ] The doc references the RAM/flash checkpoint method (pre-freeze
      vs. post-freeze heap, from ticket 007).
- [ ] The doc states that the `git diff master -- src/firm` =
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
