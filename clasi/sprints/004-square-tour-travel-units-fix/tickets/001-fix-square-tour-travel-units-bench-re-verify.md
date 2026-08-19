---
id: '001'
title: Fix square tour travel units + bench re-verify
status: in-progress
use-cases:
- UC-003
- UC-014
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

- [x] Root cause is identified and stated plainly in this ticket
      (what was wrong in the counts/mm/degrees math, not just "legs
      now run further").

      **Root cause**: `src/demo_square.py`'s `TICKS_PER_MM` (1.4187)
      mirrored `data/zetuv.json`'s `wheels` group
      (`wheel_diameter_mm=80.77`, `ticks_per_rev=360`). BOTH of those
      two inputs were unverified `tovez_nocal.json` template defaults,
      never independently measured on any real Nezha unit in this
      repo's `data/` — including `data/tovez.json` itself, whose own
      `wheels` block carries the *identical* unqualified 80.77/360/
      1.4187 trio with no camera/bench provenance note, unlike every
      other calibrated group in that file. The arithmetic combining
      them (`ticks_per_mm = ticks_per_rev / (pi * wheel_diameter_mm)`)
      was correct; the two INPUT numbers were simply wrong, making
      every leg/pivot's encoder-termination target ~4.2-5.3x too
      small — exactly matching the stakeholder's live observation
      (a "500 mm" leg turning the wheels only ~270°/0.75 rev instead
      of the ~3.3-3.6 rev 500 mm needs on a ~145 mm-circumference
      wheel). `diffdrive.output()`'s `positionLeft/Right` are
      confirmed counts-native raw shaft encoder ticks (tenths of a
      degree per count — `vendor/nezha_motor.cpp`'s own comment,
      cross-checked against two independent `vendor/nezha_motor.h`
      constant-derivation comments), so this was a bad-input-data bug
      in the two template numbers feeding an otherwise-correct
      conversion, not a units-family (counts-vs-mm) mismatch in the
      formula itself.
- [x] Corrected math/values are cross-checked against both
      `tovez.json`'s calibrated values and the empirical counts-per-rev
      range (~870-1080); the ticket states which source ended up
      governing when they disagreed (empirical wins on conflict, per
      the issue's explicit instruction).

      **Cross-check result — they disagreed, empirical governs.**
      `tovez.json`'s `wheels` block is NOT independently calibrated
      (see root cause above) so it offered no real second reference.
      The one field in `tovez.json` actually named "travel
      calib" — `motors.travel_calib_left/right` (0.7837) — DOES carry
      a real vendor-grounded unit (`vendor/nezha_motor.h`'s own
      comments: mm per DEGREE of raw encoder rotation, at 10
      counts/degree), and implies `ticks_per_mm ≈ 12.76` — but that
      field feeds a *different* kernel input entirely
      (`fullDutyVelocity`, VELOCITY-mode `drive()`'s plant-gain
      calibration via `src/config.py`'s
      `wheel_control_to_diffdrive_config()`), which `demo_square.py`
      never reads (it drives via `driveDuty()` directly, bypassing
      `config.py`/`travel_calib` entirely — see that module's own
      docstring). The empirical anchor — sprint-002 run-1's four leg
      segments averaging 731.4 counts of encoder delta for the
      stakeholder's observed 0.75 rev, i.e. 975.2 counts/rev, inside
      the issue's own stated 870-1080 range — implies `ticks_per_mm ≈
      6.7241`, about 1.9x lower than the `travel_calib`-implied figure.
      Per the issue's explicit instruction, **the empirical anchor
      governs**: `TICKS_PER_MM = EMPIRICAL_COUNTS_PER_REV (975.0) /
      WHEEL_CIRCUMFERENCE_MM (145.0) ≈ 6.7241`. Full derivation in
      `src/demo_square.py`'s own module docstring and
      `data/zetuv.json`'s `wheels._wheels_note`.
- [x] `data/zetuv.json`'s travel-calibration fields are updated with
      the corrected values and a provenance note (borrowed from
      `tovez.json`, uniform-kit assumption, cross-checked against the
      bench empirical count).

      Done — `data/zetuv.json`'s `wheels` block (`wheel_diameter_mm`,
      `ticks_per_rev`, `ticks_per_mm`) updated with the corrected
      values and a full provenance note (`_wheels_note`). Deliberately
      did **not** add `motors.travel_calib_left/right` to
      `zetuv.json` — see the cross-check note above (that field is
      unrelated to this bug and would silently enable
      `config.load_robot_config()`'s VELOCITY-mode boot auto-configure
      path with an untested calibration figure, reversing sprint
      002/003's explicit "zetuv stays no-cal profile" decision, which
      is out of this ticket's scope).
- [x] `data/zetuv.json` still validates against
      `data/robot_config.schema.json`.

      Confirmed — `tests/test_robot_config_data.py` passes unchanged
      (8 passed, 518 subtests). The `wheels` group is not modeled by
      the schema (`data/README.md`'s own documented "known gap"), so
      this edit doesn't touch the schema-checked groups at all.
- [ ] Bench re-run (REPL-triggered handler invocation, not a physical
      button press) shows leg encoder deltas scaled to roughly 4-5×
      the old 650-811 counts (i.e., in the neighborhood of 3000-4000+
      counts for a 500 mm leg, consistent with ~870-1080 counts/rev ×
      ~3.3-3.6 revolutions), pivots proportionally sane, and a clean
      stop-verify (wheels stop cleanly at the end of the run).

      **BLOCKED — hardware fault, not a software issue.** The
      corrected `target_ticks` read back from the device exactly as
      computed (3362.069 for legs, 675.984 for pivots — matching the
      ~4.74x / ~3.45 rev expectation precisely), confirming the
      software fix is logically correct. But three independent
      REPL-triggered duty diagnostics (combined 20%/20%, left-alone,
      right-alone — all well above the 6% breakaway threshold that
      was reliable in every sprint 002/003 session today, same ports/
      signs/`max_duty`/`cycle_period_ms`) all show `appliedDutyLeft/
      Right` correctly nonzero and `connectedLeft/Right: True`, but
      `positionLeft`/`positionRight` staying at exactly 0.0 throughout
      every trial — reproduced identically after a fresh hardware
      reset (ruling out stale session state). See `throw_ticket_
      exception` below and the bench log's new section for full
      evidence. Not something this ticket's software-only scope
      (units/math correction) can fix.
- [x] The bench log is updated with this run's results, and explicitly
      corrects sprint-002's bench-log claim of "500 mm legs" with a
      pointer to this fix (append, don't silently rewrite history —
      sprint-002's log entry stays, with a correction note pointing
      here).
- [x] The device is left armed (`main.py`'s idle prompt live, per
      sprint 003) for the stakeholder to press A themselves — hand
      back promptly once the REPL-triggered check passes.

      Device is armed/idle (final `reset` + 5 s settle, no further
      `exec` issued afterward, matching sprint 003's own handoff
      convention) — but the physical A-press will currently show the
      same zero-motion symptom the REPL diagnostics found, since that
      is a hardware-level fault, not something this fix touches.
      Flagging this honestly rather than handing back silently.
- [x] `python3 -m pytest tests/` stays green at the 204 baseline.
- [x] `python3 -m py_compile` passes on every changed file; `mpy-cross`
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
