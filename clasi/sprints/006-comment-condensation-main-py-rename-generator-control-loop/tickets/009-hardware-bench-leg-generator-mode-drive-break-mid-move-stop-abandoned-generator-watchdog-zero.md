---
id: 009
title: 'Hardware bench leg: generator-mode drive, break-mid-move stop, abandoned-generator
  watchdog zero'
status: in-progress
use-cases:
- SUC-001
- SUC-002
depends-on:
- '007'
- 008
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
exception:
  thrown_by: programmer
  thrown_at: '2026-08-20T16:51:31.578425+00:00'
  attempted: 'Full bench procedure on tovez, wheels on blocks. Reflashed at HEAD c0d06ae
    after finding the first hex carried the pre-ticket-007 frozen motion.py. Legs
    run: begin plus neutral steps, mode latch, 600ms generator drive, break mid-move,
    abandoned generator, close-vs-break comparison, per-wheel duty isolation.'
  conflict: Break does not stop the wheels on MicroPython. close() runs the finally
    and lands duty 0/0, but a student break leaves duty 17/17 with no landing step,
    even after gc.collect. The unit test asserts this path via close(), not break,
    so the suite is green while the documented teaching invariant is false. Separately,
    a refused start() consumes the one-shot mode latch, locking out step mode for
    the whole boot. Both need fixing before this ticket can pass.
  surface: user-visible
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Hardware bench leg: generator-mode drive, break-mid-move stop, abandoned-generator watchdog zero

## Description

**Requires a robot on the bench. Do not execute this ticket without
one.** The target robot is a **parameter**, not hardwired to zetuv —
resolve it fresh at execution time using the procedure below, not from
this ticket's text or from prior sprints' bench-log entries.

### Live hardware situation (established fact as of sprint planning, 2026-08-20 — re-verify at execution time, do not assume it still holds)

- zetuv's registered UID (`...312bde85515a72e6`) has never appeared in
  any enumeration.
- A board has been observed flapping on and off the USB bus: it
  enumerated, then refused connection ("in use by another program" —
  this is very likely the known TLM-flood defect below, not a cable
  fault), then disappeared along with its `MICROBIT` volume.
- Stable at last check: `tovez` (robot), `getez` and `zavaz` (relays,
  never drive targets).
- Two boards observed self-identifying as `tovez`, not zetuv — one via
  the v5 cleartext protocol (`ID` → `ID:diffdrive:tovez:1.0.0`, `VER`
  → `VER:1.0.0`, `PING` → `PONG:t=...`), the other via its on-device
  `robot.json` (`{"identity":{"robot_name":"tovez"}}`).
- `config/devices.json`'s `port` fields are **stale** — ports churn on
  replug. Its UIDs are meaningful only if boards have not been
  swapped between chassis since it was last written, which is not
  guaranteed. **Do not trust `devices.json` for this ticket.**

### Step 1 — confirm target identity from the device itself (mandatory first step)

1. Enumerate connected boards (`mbdeploy list` or equivalent) to see
   what is physically present *right now* — do not read this from
   `config/devices.json`.
2. For each candidate board, read its **on-device** `robot.json`
   (filesystem, not `config/devices.json`) — e.g. over the v5
   cleartext protocol (`ID`) or by reading the file directly if REPL
   access allows. The device's own self-report is the authoritative
   identity check; `devices.json` is not.
3. **Refuse to proceed if the on-device identity does not match a
   `data/<robot>.json` calibration file you intend to apply.** This is
   a hard precondition, not a judgment call: `data/zetuv.json` (975
   ticks/rev, 3.4484 ticks/mm) and `data/tovez.json` (3600 ticks/rev,
   12.7602 ticks/mm) differ by a factor of 3.70. Commit `6c5f57c`
   already produced a concrete instance of this exact mistake —
   commanded 500 mm drove ~150 mm (3.3× error) — from a zetuv-titled
   change that, despite its own message, actually edited
   `data/tovez.json`. Do not repeat that class of error here.
4. If no board identifies as the intended target (e.g. zetuv is
   expected but every present board says `tovez`), **stop and escalate
   to the stakeholder** rather than substituting a different robot's
   calibration onto a mismatched chassis, or silently testing against
   whichever robot happens to be present. The stakeholder resolves
   whether to reconnect zetuv or formally retarget this ticket (and,
   if retargeted, review whether `data/vevov.json` needs deriving
   first — it does not currently exist, unlike `tovez`/`gopiv`/
   `togov`/`zetuv`).
5. Record the confirmed target's identity, UID, and the `data/
   <robot>.json` file being applied in this ticket's own bench-log
   entry before proceeding to Step 2.

### Step 2 — known bench-tooling defect (read before connecting)

The robot floods TLM telemetry over USB serial at ~19 Hz and does
**not** stop on `TLM:OFF`. This blocks `mpremote`'s REPL handshake and
produces a misleading "port in use by another program" error that
looks like a cable or hardware fault but is not — it is a known,
separately-tracked defect (`tlm-stream-ignores-tlm-off.md`, not part
of this sprint). If a board that enumerates then refuses connection is
observed, this defect is the first suspect, not a bad cable or a dying
board. Fixing it is out of this ticket's scope; knowing about it
avoids losing bench time re-diagnosing it.

### Step 3 — the bench legs (only after Steps 1-2, on the confirmed target)

1. **Encoder-sign check**: step-driven drive via `motion.py`'s new
   generator function (ticket 007) at a small, smallest-visible-pulse
   speed first. Confirm encoder counts advance with the correct sign
   on both wheels.
2. **Break-mid-move stop**: start a generator-driven move, `break` out
   of the iterating loop partway through. Confirm the `finally` block
   fires (`neutral()` + landing `step()`) and wheels stop within one
   cycle (~24 ms) — explicit stop-verify (Δencoder ≈ 0 over 2 s after
   the stop).
3. **Abandoned-generator watchdog zero**: start a generator-driven
   move, then stop calling `next()` without a clean `break` (e.g. drop
   the reference, or let an unrelated exception abort the calling
   code). Confirm duty zeroes within the lease window (~3× cycle
   period) if iteration merely paused, or within ~250 ms via the
   starvation watchdog if Python stalled entirely.
4. Log `cycleOverrunCount_` during step-driven iteration — sane
   values expected (occasional overrun from student-loop-body jitter
   is fine; sustained large overrun would indicate a pacing bug).

Deploy discipline per bench convention: deploy by **UID only** (never
board name alone); `getez`/`zavaz` are relays — never pass
`--force-relay`; if any deploy tool refuses a target, stop and
investigate rather than working around the refusal; wait ~5 s
post-flash settle; power-cycle the WiFi module before any WiFi work
(not expected to be needed for this USB/REPL-only ticket).

## Acceptance Criteria

- [x] Target robot identity confirmed from the device's own
      `robot.json`/`ID` response, **not** from `config/devices.json`,
      and recorded in the bench log before any drive command.
      Confirmed: tovez, three independent ways (device `robot.json`,
      v5 `ID` response, `config/devices.json` UID map as corroboration
      only). See `docs/bench-log-zetuv-2026-08-19.md` §58.
- [x] Execution refused (and escalated to the stakeholder) if no
      present board matches the calibration file intended for
      application — this refusal is itself an acceptable, correct
      outcome for this ticket, not a failure to route around.
      Not exercised — the confirmed target matched
      `data/tovez.json` on the first check, so the refusal branch had
      nothing to refuse; no board other than tovez was evaluated. §58.
- [ ] Encoder-sign-correct step-driven drive demonstrated and logged.
      **Not satisfied by this session's data** — see Implementation
      Notes below. Left unchecked; do not reword.
- [ ] Break-mid-move stop demonstrated: wheels stop within one cycle;
      explicit stop-verify (Δencoder ≈ 0 over 2 s).
      **Partially evidenced only** — see Implementation Notes below.
      Left unchecked; do not reword.
- [x] Abandoned-generator watchdog/lease zero demonstrated within the
      expected window (~3× cycle period for lease decay, ~250 ms for
      the starvation watchdog if Python stalled). Confirmed: dropped
      generator zeroed duty after a ~300 ms stall, `watchdogFault`
      True, `watchdogTripCount` 1 (bench-log §62, "R2").
- [ ] Bench log updated with: confirmed target identity + UID, the
      `data/<robot>.json` applied, and results of all three legs.
      Identity/UID/calibration-file are logged (§58); results are
      logged for legs 2 and 3, but **not** leg 1 (encoder-sign check —
      see the two unchecked items above). Left unchecked because "all
      three legs" is not yet true.
- [x] If the TLM-flood/`mpremote` handshake defect is hit during this
      session, the bench log notes it was recognized as the known
      defect, not mis-diagnosed as a hardware fault. Not hit in either
      session this ticket covers — nothing to log, criterion vacuously
      satisfied.

## Testing

- **Existing tests to run**: none — this ticket is hardware
  verification, not a source change. (`uv run pytest` should already
  be green from tickets 001-008; no code changes happen here.)
- **New tests to write**: none — this ticket produces bench-log
  evidence, not new automated tests.
- **Verification command**: none automated. Verification is the bench
  procedure above, executed and logged by whoever has physical access
  to the confirmed target robot.

## Implementation Notes

Full session record: `docs/bench-log-zetuv-2026-08-19.md`, the
"Sprint 006 ticket 009 session" block (§58-§63 plus its own Summary),
appended after §57. Two runs are folded into that entry: the first run
recorded in this ticket's own `exception:` frontmatter block above
(not duplicated here), and the final re-verification run below.
Target both sessions: **tovez**, wheels on blocks throughout — no
travel-distance-in-mm check was ever possible; every reading is
encoder-count/duty/cycle-count/watchdog-flag based.

**Both defects from the first run, retested and confirmed fixed**:

1. Mode latch (fixed by ticket 011, `85d2ed4`): fresh boot,
   `diffdrive.step()` now succeeds (`cycleCount` 1) after a prior
   *refused* `start()`, and a subsequent `start()` still correctly
   refuses with `"start() refused: step() already latched step mode
   this boot"` — a refusal no longer consumes the latch, and mutual
   exclusion still holds.
2. Break-mid-move stop (fixed by ticket 012, `a8e5408`): `with
   motion.drive(...) as move: ... break` and `mv.stop(); break` both
   land duty `(0.0, 0.0)` within one landing cycle (iters 5, cycles 6).
   A bare `break` with no `stop()` still leaves duty `(17.0, 17.0)`
   commanded — this is ticket 012's own documented, accepted gap
   (watchdog-covered failsafe, not the contract), not a residual bug.

Image flashed for the final run: HEAD `85d2ed4` (both fixes present).
Verified on-device before any drive command, applying the procedural
lesson below: `hasattr(diffdrive, 'step')` and `hasattr(motion,
'drive')` both True, `diffdrive.cyclePeriod() == 24`.

Regression pass (R1-R3 in the bench log) re-confirmed three of the
first run's already-passing legs with no regression: the one-`next()`-
equals-one-cycle pacing invariant, the abandoned-generator watchdog/
lease zeroing (`watchdogFault` True, `watchdogTripCount` 1 after a
~300 ms stall), and `cycleOverrunCount` housekeeping (0, `lastError`
`ok`).

**Why three acceptance criteria are left unchecked, not reworded**:
the first run's per-wheel duty-isolation / encoder-sign-check leg
(ticket Step 3 leg 1 — confirming encoder counts advance with the
correct sign on both wheels) was **not** re-run in the final session,
and no encoder position/sign values were captured in either session's
own notes handed to this write-up. Separately, the break-mid-move
retest (above) evidences "wheels stop within one cycle" via duty and
cycle-count readings, but the ticket's own acceptance criterion also
asks for an *explicit* stop-verify reading (`Δencoder ≈ 0` over 2 s)
that was not itself captured either. Both gaps cascade into the
"results of all three legs" bench-log criterion, which is therefore
also left unchecked. **Ticket status is left `in-progress`, not set to
`done`, pending the team-lead's decision on whether to schedule the
missing leg or amend the criteria.**

**Timing observation, not a settled finding** (see bench log §63 for
the full statement with its uncertainty intact): `cycleBusy` measured
23501 us against the 24 ms `cyclePeriod` on this final run, taken
after driving under load; an earlier, separate reading (idle motors)
measured 15987 us. These are two single samples under different,
uncontrolled conditions — not averaged, neither treated as settled.
*If* ~23.5 ms is representative under load, a student's per-`next()`
loop-body budget would be well under 1 ms rather than the ~14 ms the
design assumed, which bears on the primary-teaching-posture question
`docs/design/specification.md` §10 item 4 defers to this ticket — but
a single loaded sample cannot close that question; a dedicated
characterization run is still needed.

**Procedural lesson recorded for future bench sessions**: the first
run's own flash carried the native `diffdrive.step()` binding paired
with the pre-ticket-007 frozen `motion.py` (no `drive()`), i.e. half a
two-sided feature — the image still imported cleanly. A bench
procedure should assert both `hasattr(diffdrive, 'step')` and
`hasattr(motion, 'drive')` before trusting an image, not either alone.

Verification run: `uv run pytest tests/` — 244 passed, 518 subtests
passed (unchanged from ticket 012's baseline — this ticket is
docs/ticket-notes only, no source changed). `git diff --exit-code --
vendor/` clean.
