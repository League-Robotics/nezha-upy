---
id: '001'
title: Set zetuv wheel diameter to 80.77 mm and rescale square tour
status: done
use-cases:
- UC-003
- UC-014
depends-on: []
github-issue: ''
issue: zetuv-wheel-diameter-from-tovez.md
completes_issue: true
exception:
  thrown_by: programmer
  thrown_at: '2026-08-19T21:20:06.733823+00:00'
  attempted: 'Ticket was reopened to in-progress on the coordinator''s report that
    the stakeholder said "Zetuv has returned" (physically reconnected). Re-checked
    zetuv''s connectivity immediately and four more times over the following ~15s
    using the same four independent methods as the original exception: mbdeploy list
    (x2), a fresh mbdeploy probe re-scan (x2), raw OS-level serial enumeration (ls
    -la /dev/cu.usbmodem*), and pyocd list (the separate CMSIS-DAP interface, independent
    of the CDC serial mbdeploy/mpremote use). All five checks agree: zetuv is still
    not connected -- only getez (/dev/cu.usbmodem214102), zavaz (/dev/cu.usbmodem2121302),
    tovez (/dev/cu.usbmodem2121202, still occupying zetuv''s former port), and vevov
    (/dev/cu.usbmodem2121102) enumerate on either interface. Zetuv''s UID (9906360200052820312bde85515a72e6000000006e052820)
    does not appear anywhere. No device command was issued against any board this
    pass either -- only read-only enumeration calls. Findings recorded in docs/bench-log-zetuv-2026-08-19.md
    Sec 41 and reported back to the coordinator directly rather than proceeding (deploy/REPL/motor
    commands) on an unconfirmed hardware premise.'
  conflict: Same underlying conflict as the original exception (ticket 001's Bench
    re-verify section and Acceptance Criteria require a REPL-triggered bench re-run
    and armed handoff on zetuv specifically) -- re-raised because the stakeholder-reported
    resolution ("Zetuv has returned") does not match what this machine's hardware
    enumeration shows. This is not a new architectural conflict, it is the same physical
    bench precondition (zetuv not connected to this machine) persisting past the point
    where it was reported fixed -- worth flagging explicitly rather than silently
    treating the coordinator's report as ground truth, since this agent has no way
    to reconcile a verbal/relayed report against three independent, repeatedly-checked
    hardware enumeration sources that all disagree with it.
  surface: user-visible
  resolved: true
  resolution: 'Coordinator independently verified the reconnection before re-dispatching
    (mbdeploy list showing zetuv, correct UID, CONNECTED on a NEW port /dev/cu.usbmodem2121402
    -- the bench had been reshuffled: vevov moved to zetuv''s old port 2121202, tovez
    moved to 2121102). Independently re-confirmed here via mbdeploy list + a fresh
    mbdeploy probe re-scan before touching anything: zetuv genuinely connected at
    that new port, tovez/vevov/getez/zavaz all present and none touched. Deployed
    the rescaled stripped copies (robot.json regenerated from the corrected data/zetuv.json,
    2415 bytes; demo_square.py regenerated stripped from the corrected src/demo_square.py,
    12495 bytes; both verified byte-for-byte via on-device os.stat); main.py (2999
    bytes, unchanged) confirmed still present. Cautious single-wheel probe (LEFT alone
    then RIGHT alone, modest duty, short lease) confirmed real, correctly-signed encoder
    motion on both wheels with clean stop-verify before trusting a full tour. REPL-triggered
    on_button_a() (the exact button-A handler) via exec(main.py source, {"__name__":
    "verify"}): all 8/8 segments reached True -- legs (target 1921.209 ticks) delivered
    mean deltas 1924.0/1937.5/1948.5/1933.5 (within ~1.5% of target, ~2 wheel revolutions
    each); pivots (target 386.2821 ticks) delivered mean deltas 419.5/411.0/400.0/414.0
    (within ~3.6-8.6% of target, correctly signed -- delta_left negative, delta_right
    positive, matching the kernel''s CCW/LEFT convention). Stop-verify: position (6059.0,
    11059.0) before and after a 2 s wait -- Delta=(0,0), no drift. Device reset +
    5 s settle afterward; mbdeploy list confirmed still connected, responsive, at
    the same port, with no further exec/run issued -- left armed at the idle prompt
    for the stakeholder''s physical A press. Full results in docs/bench-log-zetuv-2026-08-19.md
    Sec 42.'
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Set zetuv wheel diameter to 80.77 mm and rescale square tour

## Description

Stakeholder correction, live at the bench (2026-08-19): "Tovez does in
fact have the correct wheel diameter. It's probably correct. You need
to set the wheel size for this Micro:bit to be the same as Tovez's."

This is the second half of the sprint-004 travel-units fix. Sprint 004
correctly established the empirical ticks-per-wheel-revolution
(~975, derived from the stakeholder's 270° observation against logged
encoder deltas) but kept an *assumed* ~145 mm wheel circumference. That
assumption is now known wrong: tovez's `wheel_diameter_mm = 80.77`
(circumference ≈253.74 mm) is stakeholder-confirmed correct, and zetuv
uses the same wheel. Net effect of sprint 004 alone: legs actually
drove ≈874 mm — 1.75× too long, not the ~500 mm intended (the ticks
were right in *revolutions*, wrong in *mm*, because the mm-per-tick
conversion used the wrong circumference).

**Derivation** (from the issue; confirm by reading the current
`demo_square.py`/`data/zetuv.json` state, don't assume it matches this
exactly):

- `TICKS_PER_MM = 975 / 253.74 ≈ 3.843` (was ≈6.724, derived from the
  wrong ~145 mm circumference).
- 500 mm legs → ≈1922 ticks (≈1.97 wheel revolutions) — was 3362 ticks
  under the old (wrong) constant.
- Pivot targets rescale by the same `TICKS_PER_MM` correction, but
  re-derive them from the track width the config/geometry actually
  specifies (don't just apply a blanket scale factor blindly) — sanity
  check from the issue: the old 676-tick pivot implied a ≈100.5 mm arc,
  implying a ≈128 mm track width; keep that arc distance, rescale the
  ticks needed to cover it to ≈386.

**Changes**:

1. `data/zetuv.json`'s wheel geometry: set `wheel_diameter_mm: 80.77`,
   with a provenance note ("stakeholder-confirmed 2026-08-19, same
   wheels as tovez.json"). **Keep** the empirical ~975
   ticks-per-wheel-revolution sprint 004 already established and
   proved on the bench — do **not** revert to the template's
   `ticks_per_rev: 360` default, which sprint 004 already disproved.
2. `demo_square.py`: recompute `TICKS_PER_MM` and the pivot tick
   targets from the two config-derived numbers above (wheel
   circumference from the corrected diameter; empirical ticks/rev from
   config). State the derivation in code comments — a future reader
   should be able to see where ≈3.843 and ≈1922/≈386 (or whatever the
   actual recomputed values are) came from, not just find new magic
   numbers.
3. **Do not touch `data/tovez.json`** — its diameter is now blessed by
   the stakeholder as-is. Its own `ticks_per_rev: 360` field is
   internally inconsistent with the same empirical-975 finding sprint
   004 made on zetuv (same kit hardware), but that is a tovez-bench
   question for a separate day — note the inconsistency in this
   ticket's notes, do not fix it here.
4. Any test that currently hardcodes sprint 004's tick constants must
   follow the live/recomputed constant instead (sprint 004 already
   wired tests this way per the issue — confirm, don't assume, and fix
   any that don't).

**Bench re-verify** (REPL-triggered handler invocation, not a physical
press): leg deltas ≈1922 ticks (≈2 wheel revolutions, visibly ~50 cm
legs), pivots ≈90°, clean stop-verify. Update the bench log, including
a note that sprint 004's ticks were right in revolutions but wrong in
mm, due to the circumference assumption this ticket corrects. Leave
the device armed (`main.py`'s idle prompt live) for the stakeholder's
physical A press when done.

**Bench facts**: zetuv UID
`9906360200052820312bde85515a72e6...`, port `/dev/cu.usbmodem2121202`
(re-verify — bench USB assignment can shift between sessions).
getez/zavaz are relays — never touch. On-device copies are
docstring-stripped (repo sources are canonical — edit the repo, not
the device copy directly, then redeploy). Sprint 004's 400 ms
segment-lease-refresh mechanism stays as-is, out of this ticket's
scope.

## Acceptance Criteria

- [x] `data/zetuv.json`'s `wheel_diameter_mm` is `80.77`, with a
      provenance note (stakeholder-confirmed, same wheels as tovez).
- [x] `data/zetuv.json`'s empirical ~975 ticks-per-wheel-revolution
      value (from sprint 004) is preserved, not reverted to the
      template default.
- [x] `data/zetuv.json` still validates against
      `data/robot_config.schema.json`.
- [x] `demo_square.py`'s `TICKS_PER_MM` and pivot tick targets are
      recomputed from the updated config-derived numbers, with the
      derivation stated in code comments.
- [x] `data/tovez.json` is byte-for-byte untouched by this ticket
      (`git diff` confirms no changes to it).
- [x] The `tovez.json` `ticks_per_rev: 360` inconsistency is noted in
      this ticket (or a follow-up issue reference), not fixed here.
- [x] Any test hardcoding a stale tick constant is updated to follow
      the live/recomputed constant (confirm sprint 004's tests already
      do this; fix any that don't).
- [x] Bench re-run (REPL-triggered) shows leg deltas ≈1922 ticks
      (≈2 wheel revolutions, visibly ~50 cm), pivots ≈90°, and a clean
      stop-verify. RESOLVED once zetuv reconnected on its new port
      (`/dev/cu.usbmodem2121402` this session, bench reshuffled — see
      `docs/bench-log-zetuv-2026-08-19.md` Sec 42): all 8/8 segments
      `reached True`. Legs (target 1921.209 ticks) mean deltas
      1924.0/1937.5/1948.5/1933.5 (within ~1.5% of target). Pivots
      (target 386.2821 ticks) mean deltas 419.5/411.0/400.0/414.0
      (within ~3.6-8.6% of target, correctly signed). Stop-verify:
      position `(6059.0, 11059.0)` before and after a 2 s wait —
      Δ=(0,0), no drift.
- [x] Bench log updated with the root-cause note (sprint 004 was right
      in revolutions but wrong in mm due to the circumference
      assumption), this session's earlier hardware-blocker findings
      (Sec 37-41), and the final successful reconnection + full-tour
      results (Sec 42).
- [x] Device left armed (`main.py` idle prompt live) for the
      stakeholder's physical A press — confirmed this session: reset
      + 5 s settle performed after the REPL-triggered verification,
      `mbdeploy list` confirmed zetuv still connected and responsive at
      the same port immediately after, with no further `exec`/`run`
      issued.
- [x] `python3 -m pytest tests/` stays green at the 204 baseline.
- [x] `python3 -m py_compile` passes on every changed file; `mpy-cross`
      lints `demo_square.py` clean.

## Testing

- **Existing tests to run**: full `python3 -m pytest tests/` suite
  (204-passed baseline) — must stay green, including any test that
  reads `data/zetuv.json`'s schema-validated fields or
  `demo_square.py`'s tick constants.
- **New tests to write**: none required beyond confirming existing
  tests follow the live constant per the acceptance criteria above; a
  small assertion on the recomputed `TICKS_PER_MM`/pivot-tick value
  (matching the derivation from the corrected diameter and the
  preserved empirical ticks/rev) is worthwhile if `demo_square.py`'s
  structure supports it cleanly, mirroring sprint 004's approach.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: read `data/zetuv.json`'s current wheel/geometry fields
and `demo_square.py`'s current `TICKS_PER_MM`/pivot-target constants
first (confirm sprint 004's actual field names and values — don't
assume they match the issue's derivation exactly). Apply the diameter
correction to config, recompute the demo constants from the two
config-derived numbers (corrected circumference, preserved empirical
ticks/rev), with derivation comments. Confirm `tovez.json` is
untouched. Bench-verify via REPL (probe zetuv's resident image and USB
port first — should already be current from sprint 004, per this
project's established probe-before-reflash discipline; only reflash if
actually stale).

**Files to create/modify**: `data/zetuv.json`, `src/demo_square.py` (or
wherever prior sprints landed it — confirm the actual path), the bench
log file(s) from sprints 002-004, any test hardcoding a stale
constant.

**Testing plan**: `python3 -m pytest tests/`; `py_compile`/`mpy-cross`
lint; REPL-triggered bench re-run as the primary hardware verification.

**Documentation updates**: bench log correction/append entry, as
described in Acceptance Criteria; a note (in this ticket or a
follow-up issue) on `tovez.json`'s unresolved `ticks_per_rev: 360`
inconsistency.
