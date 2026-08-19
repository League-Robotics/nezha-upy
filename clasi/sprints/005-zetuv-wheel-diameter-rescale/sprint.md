---
id: '005'
title: Zetuv wheel diameter rescale
status: planning-docs
branch: sprint/005-zetuv-wheel-diameter-rescale
worktree: false
use-cases: [UC-003, UC-014]
issues:
- zetuv-wheel-diameter-from-tovez.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 005: Zetuv wheel diameter rescale

## Goals

Set zetuv's wheel diameter to tovez's stakeholder-confirmed 80.77 mm
and rescale the square tour's tick math from the corrected
circumference, so legs land at ~500 mm (not the ~874 mm sprint 004
actually produced from a wrong circumference assumption).

## Problem

Sprint 004 fixed the ticks-per-revolution side of the travel-units bug
(empirically ~975 ticks/wheel-revolution, confirmed correct) but kept
an assumed ~145 mm wheel circumference. Stakeholder correction, live at
the bench (2026-08-19): tovez's `wheel_diameter_mm = 80.77` (≈253.74 mm
circumference) is correct, and zetuv uses the same wheel — so sprint
004's circumference assumption was wrong, not the ticks-per-rev number.
Net effect: sprint 004's legs actually drive ≈874 mm (1.75× too long),
not the ~500 mm intended.

## Solution

Update `data/zetuv.json`'s wheel geometry to `wheel_diameter_mm:
80.77` (provenance: stakeholder-confirmed, same wheels as tovez) while
**keeping** the empirical ~975 ticks-per-wheel-revolution sprint 004
proved on the bench (do not revert to the template's `ticks_per_rev:
360`). Recompute `demo_square.py`'s `TICKS_PER_MM` (≈3.843, from
975/253.74) and pivot tick targets (rescaled from the same factor,
keeping the arc distance implied by the configured track width) from
these two config-derived numbers, with the derivation stated in
comments. Leave `data/tovez.json` untouched — its diameter is now
blessed; its own `ticks_per_rev: 360` inconsistency is a separate,
not-this-sprint question, noted but not fixed. Bench re-verify on
zetuv via a REPL-triggered handler run.

## Success Criteria

- `data/zetuv.json`'s `wheel_diameter_mm` is 80.77, with a provenance
  note (stakeholder-confirmed, same wheels as tovez); the empirical
  ~975 ticks/wheel-rev is preserved, not reverted to the template
  default.
- `demo_square.py`'s `TICKS_PER_MM` (≈3.843) and pivot tick targets are
  recomputed from the updated config-derived numbers, with derivations
  stated in comments (not just new magic numbers).
- `data/tovez.json` is untouched.
- Bench re-verify (REPL-triggered) shows leg deltas ≈1922 ticks
  (≈2 wheel revolutions, visibly ~50 cm), pivots ≈90°, and a clean
  stop-verify.
- Bench log updated, including a note that sprint 004's ticks were
  right in revolutions but wrong in mm, due to the circumference
  assumption this sprint corrects.
- Device left armed (`main.py` idle prompt live) for the stakeholder's
  physical A press.
- `python3 -m pytest tests/` stays green at the 204 baseline;
  `py_compile` + `mpy-cross` lint the changed files.

## Scope

### In Scope

- `data/zetuv.json`'s wheel-diameter/geometry field.
- `demo_square.py`'s `TICKS_PER_MM` and pivot-tick-target recomputation.
- Bench re-verification (REPL-triggered) and bench-log update.

### Out of Scope

- `data/tovez.json` — explicitly untouched; its own `ticks_per_rev:
  360` inconsistency is noted, not fixed, this sprint.
- Any board other than zetuv — getez/zavaz are relays, never touched.
- The sprint-004 400 ms segment-lease-refresh mechanism — stays as-is,
  not part of this sprint's scope.
- Any framework, module, or kernel change — this is config values plus
  demo constants only.

## Test Strategy

Offline: `python3 -m pytest tests/` (204 baseline) stays green;
`py_compile` + `mpy-cross` lint the changed files; tests referencing
the tick/mm constants follow the live constant, per how sprint 004
already wired them (no test hardcodes the old value). On hardware: a
REPL-triggered run of the same button-A handler (not a physical press)
to observe the corrected ≈1922-tick legs and ≈90° pivots with a clean
stop, logged in the bench log.

## Architecture

**Sizing: Trivial.** A config field correction
(`data/zetuv.json`'s `wheel_diameter_mm`) plus a recomputation of
already-existing demo constants (`demo_square.py`'s `TICKS_PER_MM` and
pivot targets) from that corrected config value — no new module, no
changed interface, no framework or data-model change (same schema,
corrected + one previously-default field, corrected derived
constants). No diagrams; no Design Rationale beyond the provenance
note already stated in Solution above (stakeholder-confirmed shared
wheel spec with tovez, empirical ticks-per-rev preserved); no
Migration Concerns beyond leaving the device armed, already covered
under Success Criteria.

## Use Cases

This sprint corrects a residual defect in existing use-case coverage
(the same one sprint 004 partially fixed) rather than adding new
behavior: UC-003 (student/operator drives wheels — the tour's actual
leg distance is what's being corrected) and UC-014 (bench acceptance/
verification — re-verified on zetuv and logged, same pattern as
sprints 002-004's own bench verification).

## GitHub Issues

(None — this sprint's issue is a CLASI-local `clasi/issues/` file.)

## Definition of Ready

- [x] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [x] Architecture review passed (skipped — trivial, no architectural
      impact)
- [x] Stakeholder has approved the sprint plan (direct directive at
      the bench, 2026-08-19: "set the wheel size for this Micro:bit to
      be the same as Tovez's")

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | Set zetuv wheel diameter to 80.77 mm and rescale square tour | — |

Tickets execute serially in the order listed.
