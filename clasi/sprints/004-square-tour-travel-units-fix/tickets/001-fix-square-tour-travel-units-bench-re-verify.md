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
exception:
  thrown_by: programmer
  thrown_at: '2026-08-19T20:08:22.420147+00:00'
  attempted: 'Completed the full software fix: audited demo_square.py''s TICKS_PER_MM
    (1.4187) end to end, confirmed via vendor/nezha_motor.cpp + two independent vendor/nezha_motor.h
    comments that diffdrive.output() positions are counts-native raw shaft-encoder
    ticks (tenths of a degree/count), and found the bug was bad input data (zetuv.json''s/tovez.json''s
    identical, unverified wheel_diameter_mm=80.77/ticks_per_rev=360 template defaults)
    feeding an otherwise-correct formula, not a units-convention mismatch. Cross-checked
    against tovez.json''s motors.travel_calib_left/right (0.7837 mm/deg, vendor-grounded)
    and found it conflicts by ~1.9x with the empirical bench anchor (975 counts/rev
    derived from sprint-002 run-1''s own recorded leg deltas over the stakeholder''s
    observed 270 deg) -- also confirmed travel_calib feeds an unrelated kernel field
    (fullDutyVelocity, VELOCITY-mode) that demo_square.py never reads. Per the issue''s
    explicit "empirical wins on conflict" instruction, set TICKS_PER_MM = 975.0/145.0
    ~= 6.7241 in demo_square.py, mirrored the same corrected values into data/zetuv.json''s
    wheels block with a full provenance note, updated the two hardcoded-literal tests
    in tests/test_demo_square.py, ran the full suite (204 passed, 518 subtests, unchanged
    baseline), py_compile + mpy-cross both clean, vendor/ untouched. Deployed docstring-stripped
    copies of the corrected demo_square.py and robot.json to zetuv (same convention
    as sprint 002/003), then ran a REPL-triggered on_button_a() invocation: the read-back
    target_ticks (3362.069 legs, 675.984 pivots) matched the hand-derived correction
    exactly, confirming the software fix is logically correct -- but every one of
    the 8 segments timed out with delta_left/delta_right exactly 0.0 (no wheel motion
    at all). Ran three further diagnostics matching sprint 002 ticket 002''s own bench-verified-working
    protocol exactly (combined driveDuty(20,20,500), left-alone, right-alone, all
    well above the 6% breakaway floor reliable all day): appliedDutyLeft/Right read
    correctly nonzero and connectedLeft/Right stayed True throughout, but positionLeft/positionRight
    stayed frozen at exactly 0.0 in every trial. Performed a full hardware reset +
    5s settle and repeated the diagnostic identically -- same zero-motion result,
    ruling out stale in-session kernel state. Did not press further (no higher duty,
    no longer duration) per this project''s own conservative-duty/minimal-necessary-probing
    discipline and this ticket''s own explicit "if hardware faults, STOP + record
    + throw exception" instruction. Committed all software work (commit d3f0cd8) and
    documented full evidence in the bench log (Sec 24-31) and the ticket''s own Acceptance
    Criteria before throwing this exception.'
  conflict: 'Acceptance Criterion 5 ("Bench re-run ... shows leg encoder deltas scaled
    to roughly 4-5x ... pivots proportionally sane, and a clean stop-verify") and
    this ticket''s completes_issue:true resolution of the issue, plus the sprint''s
    own Use Cases UC-003/UC-014 (button-A square tour must physically execute), are
    blocked by a newly-discovered hardware-level fault: both wheels show zero encoder
    motion under duty commands that reliably moved them in every sprint 002/003 session
    earlier today, reproduced identically across a fresh hardware reset. This is outside
    this ticket''s software-only scope (units/math correction in demo_square.py +
    zetuv.json) -- there is no code change available to a programmer agent that can
    restore physical wheel motion, and continuing to escalate duty/retry against a
    possibly-jammed or power-starved drivetrain risks equipment damage, which this
    project''s hardware rules explicitly instruct against. The stakeholder is at the
    bench and can physically inspect (battery charge, loose wheel/gearbox, obstruction)
    far faster than further remote REPL diagnostics could isolate it.'
  surface: user-visible
  resolved: true
  resolved_at: '2026-08-19T20:20:00.000000+00:00'
  resolution: 'Stakeholder resolved directly: "the robot has plenty of power,
    but I completely reset it, so have at it." Power explicitly ruled out; a
    full physical robot reset plausibly cleared the wedged Nezha motor board
    (the exception''s own zero-motion signature -- duty applied, I2C connected,
    encoders frozen -- is consistent with a board-level wedge a physical reset
    would clear). Re-verified the connection (mbdeploy list, same port/UID),
    confirmed the filesystem survived (robot.json/main.py/demo_square.py all
    present, unchanged sizes), then did a cautious single-wheel re-probe
    (modest duty, short lease) BEFORE trusting a full tour again -- motion
    confirmed alive on both wheels. Running the full corrected tour then
    surfaced a SECOND, separate, unrelated issue: SEGMENT_LEASE_MS/
    SEGMENT_TIMEOUT_MS (3000 ms) were sized for the OLD, much-shorter leg
    targets and were too short for the corrected ~4.74x-longer ones (legs
    hit the timeout at ~70-74% of target). Fixed by refreshing driveDuty()''s
    lease periodically (every 400 ms) instead of holding one lease for the
    whole segment, decoupling the per-segment timeout (raised to 6000 ms)
    from the native binding''s 5000 ms single-lease ceiling. Re-deployed and
    re-ran: all 8 segments reached target (legs ~3373-3390 vs target 3362.069,
    pivots ~691-710 vs target 675.984), clean stop-verify (delta 0,0 over
    2 s). Full evidence: docs/bench-log-zetuv-2026-08-19.md Sec 32-36.'
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
- [x] Bench re-run (REPL-triggered handler invocation, not a physical
      button press) shows leg encoder deltas scaled to roughly 4-5×
      the old 650-811 counts (i.e., in the neighborhood of 3000-4000+
      counts for a 500 mm leg, consistent with ~870-1080 counts/rev ×
      ~3.3-3.6 revolutions), pivots proportionally sane, and a clean
      stop-verify (wheels stop cleanly at the end of the run).

      **RESOLVED.** The prior hardware wedge (zero encoder motion,
      see the ticket's own `exception` block above) was cleared by the
      stakeholder's own physical robot reset; power was ruled out.
      After re-verifying the connection and a cautious single-wheel
      re-probe confirmed motion was alive again, the full corrected
      tour surfaced one further, unrelated issue — the per-segment
      lease/timeout budget (3000 ms) was still sized for the OLD,
      much-shorter targets and was too short for the corrected
      ~4.74x-longer legs. Fixed by refreshing `driveDuty()`'s lease
      periodically instead of holding one long lease, and raising the
      per-segment timeout to 6000 ms. Final bench re-run: **all 8
      segments `reached True`.** Legs: mean deltas 3373.5/3385.5/
      3373.5/3390.0 against target 3362.069 (within ~1%, a **4.63×**
      increase over the old 650-811/~730-average run — inside the
      3000-4000+ neighborhood and the 4-5x band). Pivots: mean deltas
      691.0/709.5/691.5/694.5 against target 675.984 (within ~5%, a
      **4.5×** increase, correctly signed). Stop-verify: position
      `(10634.0, 18045.0)` before and after a 2 s hold — delta
      `(0.0, 0.0)`, clean. Full evidence:
      `docs/bench-log-zetuv-2026-08-19.md` Sec 32-36.
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
      convention), connection re-confirmed via `mbdeploy list`. Motion
      is confirmed alive and the full corrected tour bench-verified
      (see the criterion above) — the stakeholder's physical A-press
      should now run the complete, correctly-scaled square tour.
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
