---
id: '001'
title: 'Fix square tour travel units + bench re-verify'
status: open
use-cases: [UC-003, UC-014]
depends-on: []
github-issue: ''
issue: square-tour-legs-4-5x-short-units-bug.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Fix square tour travel units + bench re-verify

## Description

Stakeholder bug report, live at the bench (2026-08-19): each "500 mm"
leg of the button-A square tour turns the wheels only ~270° of
rotation — a Nezha wheel (~145 mm circumference) needs ~3.3-3.6
revolutions for 500 mm, so legs are running ~4-5× short. "I think you
got some unit problems here."

Golden measurement from the stakeholder: current leg ≈ 270° of wheel
rotation. Sprint-002's own bench log (run 1) recorded leg encoder
deltas of ~650-811 counts — dividing that by the observed 270°
(0.75 rev) gives an empirical counts-per-revolution of roughly
870-1080. Compare that against whatever `data/zetuv.json` (template-
derived from `tovez_nocal.json`, never travel-calibrated) and
`demo_square.py`'s counts-per-mm math currently assume.

**Likely root cause** (from the issue's diagnosis, to be confirmed —
not assumed): `demo_square.py` derives its encoder targets from
`zetuv.json`'s travel-calibration fields, which were never measured
(sprint 002 ticket 001 only verified wiring/signs, explicitly deferred
calibration). This may be compounded by a counts-native vs. mm-based
convention mismatch — sprint 001 ticket 004's own finding is that the
vendored kernel leaf is the 2026-08-15 counts-native rebake, so any
code still assuming the older mm-native convention would be wrong by
whatever factor separates the two.

**Fix approach**:

1. Audit the counts↔mm↔degrees math end to end: `demo_square.py`'s
   leg/pivot duration or target computation, `data/zetuv.json`'s
   wheel/encoder fields (whatever `travel_calib`-family keys exist per
   `robot_config.schema.json`), and what `diffdrive.output()` actually
   reports (read `native/` source or its `README.md` from sprint 001
   ticket 004 to confirm counts vs. mm — do not assume either way).
   **State the root cause explicitly in this ticket once found** — not
   just "fixed."
2. Correct using `data/tovez.json`'s real, camera-measured travel
   calibration as the reference (same Nezha kit hardware — borrowing
   is acceptable with an explicit provenance note: "uniform kit,
   borrowed from tovez.json, not independently measured for zetuv").
   Cross-check the corrected math against the stakeholder's empirical
   counts-per-rev range (~870-1080, derived above). **If `tovez.json`'s
   value and the empirical range disagree, the empirical bench number
   wins** — say in the ticket which source ended up governing and why.
3. Update `data/zetuv.json`'s travel-calibration fields with the
   corrected values and their provenance note.

## Acceptance Criteria

- [ ] Root cause is identified and stated plainly in this ticket
      (what was wrong in the counts/mm/degrees math, not just "legs
      now run further").
- [ ] Corrected math/values are cross-checked against both
      `tovez.json`'s calibrated values and the empirical counts-per-rev
      range (~870-1080); the ticket states which source ended up
      governing when they disagreed (empirical wins on conflict, per
      the issue's explicit instruction).
- [ ] `data/zetuv.json`'s travel-calibration fields are updated with
      the corrected values and a provenance note (borrowed from
      `tovez.json`, uniform-kit assumption, cross-checked against the
      bench empirical count).
- [ ] `data/zetuv.json` still validates against
      `data/robot_config.schema.json`.
- [ ] Bench re-run (REPL-triggered handler invocation, not a physical
      button press) shows leg encoder deltas scaled to roughly 4-5×
      the old 650-811 counts (i.e., in the neighborhood of 3000-4000+
      counts for a 500 mm leg, consistent with ~870-1080 counts/rev ×
      ~3.3-3.6 revolutions), pivots proportionally sane, and a clean
      stop-verify (wheels stop cleanly at the end of the run).
- [ ] The bench log is updated with this run's results, and explicitly
      corrects sprint-002's bench-log claim of "500 mm legs" with a
      pointer to this fix (append, don't silently rewrite history —
      sprint-002's log entry stays, with a correction note pointing
      here).
- [ ] The device is left armed (`main.py`'s idle prompt live, per
      sprint 003) for the stakeholder to press A themselves — hand
      back promptly once the REPL-triggered check passes.
- [ ] `python3 -m pytest tests/` stays green at the 204 baseline.
- [ ] `python3 -m py_compile` passes on every changed file; `mpy-cross`
      lints `demo_square.py` clean.

## Testing

- **Existing tests to run**: full `python3 -m pytest tests/` suite
  (204-passed baseline) — must stay green; extend
  `tests/test_robot_config_data.py`'s zetuv coverage if the schema
  validation doesn't already exercise the corrected travel-calibration
  fields.
- **New tests to write**: if the counts↔mm↔degrees conversion is
  separable into a pure function, a CPython unit test asserting the
  corrected constant/formula against the golden measurement (270° for
  the *old* wrong value, ~3.3-3.6 rev for the corrected 500 mm target)
  is worthwhile — programmer's judgment on whether `demo_square.py`'s
  structure supports this cleanly without over-engineering a one-file
  fix.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: read `demo_square.py`'s current math first (do not
assume the root cause described above is exactly right — confirm by
reading), read `data/zetuv.json`'s current travel-calibration field
values and `data/tovez.json`'s equivalents, read what
`diffdrive.output()` reports (counts or mm) from `native/` source or
its README. Compute the correction, cross-check both ways described
above, apply it to both `demo_square.py` and `data/zetuv.json`.
Bench-verify via REPL (probe zetuv's resident image first — it should
already be current from sprint 003, per this project's established
probe-before-reflash discipline; only reflash if actually stale).

**Files to create/modify**: `src/demo_square.py` (or wherever sprint
002 landed it — confirm the actual path), `data/zetuv.json`, the bench
log file(s) from sprints 002/003.

**Testing plan**: `python3 -m pytest tests/`; `py_compile`/`mpy-cross`
lint; REPL-triggered bench re-run as the primary hardware verification.

**Documentation updates**: bench log correction/append entry, as
described in Acceptance Criteria.
