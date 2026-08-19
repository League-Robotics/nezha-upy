---
id: '001'
title: Set zetuv wheel diameter to 80.77 mm and rescale square tour
status: in-progress
use-cases:
- UC-003
- UC-014
depends-on: []
github-issue: ''
issue: zetuv-wheel-diameter-from-tovez.md
completes_issue: true
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
- [ ] **BLOCKED, hardware not connected**: Bench re-run (REPL-triggered)
      shows leg deltas ≈1922 ticks (≈2 wheel revolutions, visibly
      ~50 cm), pivots ≈90°, and a clean stop-verify. `zetuv` is not
      physically connected to the bench machine this session (confirmed
      via `mbdeploy list`/`probe` and independently via `pyocd list` —
      two separate USB interfaces, both agree, re-checked 3x — see
      `docs/bench-log-zetuv-2026-08-19.md` Sec 39). Escalated via
      `throw_ticket_exception`.
- [x] Bench log updated with the root-cause note (sprint 004 was right
      in revolutions but wrong in mm due to the circumference
      assumption) and with this session's hardware-blocker finding
      (Sec 37-40). Bench *results* (leg/pivot deltas) could not be
      recorded — blocked, see above.
- [ ] **BLOCKED, hardware not connected**: Device left armed (`main.py`
      idle prompt live) for the stakeholder's physical A press —
      unverifiable this session since `zetuv` was never reachable; its
      last-known state (armed, from the end of sprint 004's own
      session) was not disturbed, as no device command was issued this
      session.
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
