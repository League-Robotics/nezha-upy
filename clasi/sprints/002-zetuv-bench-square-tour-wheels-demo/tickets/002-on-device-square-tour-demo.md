---
id: '002'
title: On-device square tour demo
status: done
use-cases:
- UC-003
- UC-014
depends-on:
- '001'
github-issue: ''
issue: zetuv-square-tour-wheels-demo.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# On-device square tour demo

## Description

Build a small, repeatable on-device demo that drives zetuv through a
square path, mirroring radio-robot-elite's `src/host/robot_radio/
planner/tour.py` `TOUR_SQUARE` shape: **4 × 500 mm legs + 4 × 90° left
pivots**, rest-to-rest, ~1.2 s settle between segments, `omega_max`
2.4 rad/s. This is the sprint's actual deliverable — visible proof
the wheels move, driven through this repo's own stack rather than the
host-driven planner (which cannot talk to this image yet — a known,
out-of-scope gap; see sprint.md).

Depends on ticket 001: it needs zetuv's *measured* (not templated)
wiring signs to produce a square that's actually square, not a shape
distorted by a wrong sign.

**Ground the implementation in what `motion.py` actually supports —
don't assume.** `motion.Move` takes `v`, `twist`, `duration_ms`, and
`stop_distance_mm` (see `src/motion.py`'s `Move.__init__` and
`MoveQueue.enqueue`/`go_to`). If `motion.MoveQueue` can express both a
straight leg (via `v` + `duration_ms`, or `v` + `stop_distance_mm`) and
an in-place pivot (via `twist` + `duration_ms`, computed from the 90°
target angle and `omega_max`), build the demo as a sequence of
`MoveQueue.enqueue()` calls. If some part of the shape can't be
expressed that way, fall back to timed `diffdrive.drive()` calls for
that segment specifically — document exactly which parts used which
path and why, rather than silently mixing the two without explanation.

**Deliverable**: a demo module (e.g. `src/demo_square.py`) with a
single, clearly-named entry point, runnable via one documented command
(e.g. `mpremote run src/demo_square.py`, or frozen and invoked from
the REPL — programmer's choice, but it must be exactly one command
someone else can run without reading the source first). Between
segments, settle ~1.2 s (matching `TOUR_SQUARE`) before starting the
next leg/pivot.

Run the demo on zetuv (post-ticket-001 config in place) and record the
observation — wheels moved, the path was square-ish — in the same
bench log ticket 001 started.

## Acceptance Criteria

- [x] A demo module exists with one clearly-documented entry point and
      one documented command to run it.
- [~] The sequence matches `TOUR_SQUARE`'s shape: 4 straight legs of
      500 mm, 4 left pivots of 90°, rest-to-rest, ~1.2 s settle between
      segments, pivot rate at or below `omega_max` 2.4 rad/s.
      **Partially met, disclosed not hidden**: shape/count/rest-to-rest/
      settle are all met and bench-verified (2 full runs, 8/8 segments
      each). `omega_max` is NOT met and is not achievable with this
      robot's open-loop `driveDuty()` primitive — the gentlest
      bench-verified-reliable duty (6%) already produces ~3-4x the
      wheel speed a 2.4 rad/s pivot would need on this plant; a real
      velocity loop would be needed to hit that ceiling, which this
      sprint's no-cal scope excludes. Full reasoning: `src/
      demo_square.py`'s own docstring ("Honest limitation") and
      `docs/bench-log-zetuv-2026-08-19.md` section 14.
- [x] The implementation choice (MoveQueue vs. timed diffdrive.drive,
      per-segment if mixed) is documented in the module's docstring,
      grounded in what `motion.py` actually exposes — not assumed.
- [x] The demo was run on zetuv; the bench log records the observation
      (wheels moved; the path was square-ish — described plainly, not
      claimed as precision-verified, since `zetuv.json` carries no
      travel calibration this sprint).
- [x] `python3 -m pytest tests/` stays green (no regressions from
      sprint 001 or ticket 001).
- [x] `python3 -m py_compile` passes on the new demo module;
      `mpy-cross` lints it clean.

## Testing

- **Existing tests to run**: full `python3 -m pytest tests/` suite —
  must stay green, including ticket 001's `data/zetuv.json` addition.
- **New tests to write**: if the demo's segment-generation logic (leg/
  pivot sequence, duration computation from distance/angle/omega) is
  separable from the on-device run call, a CPython unit test asserting
  the generated sequence matches `TOUR_SQUARE`'s numbers is worthwhile
  — programmer's judgment on whether the module structure supports
  this cleanly; not a hard requirement if the module is thin enough
  that the on-device bench observation is the only meaningful check.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: read `src/motion.py`'s `Move`/`MoveQueue`/`enqueue`/
`go_to` closely first (do not assume it mirrors `tour.py`'s API);
compute each leg's `duration_ms` from 500 mm and a chosen speed, and
each pivot's `duration_ms` from 90° and `omega_max` (2.4 rad/s);
build the fixed 8-segment sequence (leg, pivot ×4, interleaved,
matching `TOUR_SQUARE`); wire the ~1.2 s settle between segments.

**Files to create/modify**: `src/demo_square.py` (new), the bench log
from ticket 001 (appended observation).

**Testing plan**: `python3 -m pytest tests/`; `mpy-cross`/py_compile
lint; the on-device run itself is the primary verification, logged in
the bench log per the acceptance criteria.

**Documentation updates**: the demo module's own docstring (entry
point, run command, the MoveQueue-vs-timed-diffdrive choice and why);
the bench log's ticket-002 observation entry.
