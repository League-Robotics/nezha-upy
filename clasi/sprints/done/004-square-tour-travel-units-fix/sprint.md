---
id: '004'
title: Square tour travel-units fix
status: closed
branch: sprint/004-square-tour-travel-units-fix
worktree: false
use-cases:
- UC-003
- UC-014
issues:
- square-tour-legs-4-5x-short-units-bug.md
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Sprint 004: Square tour travel-units fix

## Goals

Fix the square tour's travel-units bug so each "500 mm" leg actually
covers ~500 mm (~3.3+ wheel revolutions), not the ~270° (< 1
revolution) the stakeholder observed live at the bench.

## Problem

Stakeholder bug report, live at the bench (2026-08-19): each leg of
the button-A square tour turns the wheels only ~270° — ~4-5× short of
the ~3.3-3.6 revolutions a 500 mm leg needs on a Nezha wheel (~145 mm
circumference). Sprint-002's own bench log recorded leg encoder deltas
of ~650-811 counts, implying an empirical counts-per-revolution of
~870-1080 — the wrong number is somewhere in `demo_square.py`'s
counts↔mm↔degrees math and/or `data/zetuv.json`'s never-measured
travel-calibration fields (zetuv is wiring-verified only, not
travel-calibrated). Likely compounded by a counts-native vs. mm-based
convention mismatch in the vendored kernel (sprint 001 ticket 004's own
finding: the vendored leaf is the 2026-08-15 counts-native rebake).

## Solution

Audit the counts↔mm↔degrees math end to end — `demo_square.py`,
`data/zetuv.json`'s wheel/encoder fields, and what `diffdrive.output()`
actually reports (counts vs. mm) — and correct it. Use
`data/tovez.json`'s real, camera-measured travel calibration as the
reference for the same Nezha kit hardware (explicit provenance note:
borrowed, uniform-kit assumption), cross-checked against the
stakeholder's empirical counts-per-rev range (~870-1080); if the two
disagree, the empirical bench number wins. Re-verify on the bench via
a REPL-triggered handler run, update the bench log (correcting
sprint-002's "500 mm legs" claim), and leave the device armed for the
stakeholder.

## Success Criteria

- Root cause is identified and stated plainly in the ticket (not just
  "fixed" — what was wrong and why).
- Corrected math is cross-checked against both `tovez.json`'s
  calibrated values and the empirical counts-per-rev range
  (~870-1080); empirical wins on conflict, and the ticket says which
  source ended up governing.
- Bench re-run (REPL-triggered, not a physical press) shows leg
  encoder deltas scaled to ~4-5× the old 650-811 counts, pivots
  proportionally sane, and a clean stop-verify.
- The bench log is updated, explicitly correcting sprint-002's "500 mm
  legs" claim with a pointer to this fix.
- The device is left armed (`main.py` idle prompt live) for the
  stakeholder to press A themselves.
- `python3 -m pytest tests/` stays green at the 204 baseline;
  `py_compile` + `mpy-cross` lint the changed files clean.

## Scope

### In Scope

- Correcting `demo_square.py`'s travel-unit math.
- Correcting `data/zetuv.json`'s travel-calibration fields (borrowed
  from `tovez.json`, cross-checked against the empirical count).
- Bench re-verification (REPL-triggered) and bench-log correction.

### Out of Scope

- Any change to `vendor/`, the native module's counts/mm reporting
  convention itself, or any other module — this is a consumer-side
  math correction, not a kernel change.
- Any board other than zetuv — getez and zavaz are relays, never
  touched.
- Full travel calibration of zetuv from scratch (camera-measured) —
  this sprint borrows `tovez.json`'s values with a provenance note,
  it does not re-derive them.

## Test Strategy

Offline: `python3 -m pytest tests/` (204 baseline) stays green;
`py_compile` + `mpy-cross` lint the changed files. On hardware: a
REPL-triggered run of the same button-A handler (not a physical press)
to observe corrected encoder deltas and a clean stop, logged in the
bench log alongside the corrected math's derivation.

## Architecture

**Sizing: Trivial.** This is a math/constant correction in
`demo_square.py` plus corrected values in `data/zetuv.json`'s existing
travel-calibration fields — no new module, no changed interface, no
framework change, no data-model change (same schema, corrected field
values). No diagrams; no Design Rationale beyond the provenance note
already captured in Goals/Solution above (borrowing `tovez.json`'s
calibration, empirical bench number wins on conflict); no Migration
Concerns beyond leaving the device armed for the stakeholder, already
covered under Success Criteria.

## Use Cases

This sprint corrects a defect in existing use-case coverage rather
than adding new behavior: UC-003 (student/operator drives wheels — the
square tour's actual travel distance is the thing being fixed) and
UC-014 (bench acceptance/verification — the corrected math is
re-verified on zetuv and logged, same pattern as sprint 002/003's own
bench verification).

## GitHub Issues

(None — this sprint's issue is a CLASI-local `clasi/issues/` file.)

## Definition of Ready

- [x] Sprint planning document is complete (sprint.md, including its
      Architecture and Use Cases sections)
- [x] Architecture review passed (skipped — trivial, no architectural
      impact)
- [x] Stakeholder has approved the sprint plan (direct bug report at
      the bench, 2026-08-19: "each leg... maybe 270°... unit
      problems")

## Tickets

| # | Title | Depends On |
|---|-------|------------|
| 001 | Fix square tour travel units + bench re-verify | — |

Tickets execute serially in the order listed.
