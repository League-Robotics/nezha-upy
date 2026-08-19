"""demo_square -- on-device square tour demo (sprint 002 ticket 002,
``clasi/sprints/002-zetuv-bench-square-tour-wheels-demo/``, UC-003/
UC-014). Drives zetuv through 4 x 500 mm straight legs interleaved with
4 x 90-degree LEFT (counter-clockwise) in-place pivots, rest-to-rest,
matching radio-robot-elite's ``TOUR_SQUARE`` shape.

**Run it** (one command, from the repo root, with zetuv connected and
the ``diffdrive`` native module reachable over USB)::

    mpremote connect /dev/cu.usbmodemXXXXXXX run src/demo_square.py

(resolve the port via ``mbdeploy list`` -- match zetuv's UID, never a
board name alone, per this sprint's own deploy-target discipline).

**Why direct ``diffdrive`` calls, not ``motion.MoveQueue`` -- grounded,
not assumed** (this ticket's own instruction: read ``motion.py``
closely before assuming it applies here):

``MoveQueue.tick()`` drives every queued move through
``diffdrive.drive(v, twist, lease_ms)`` -- VELOCITY mode. The vendored
kernel (``vendor/differential_drive.h``, ``Config::fullDutyVelocity``'s
own doc comment) REFUSES velocity-mode commands outright whenever
``fullDutyVelocity <= 0`` ("0 = uncalibrated -> VELOCITY refused").
zetuv's own config (``data/zetuv.json``) deliberately carries NO
``travel_calib_left``/``travel_calib_right`` this sprint (sprint.md's
own Out of Scope: "zetuv.json stays a no-calibration profile") --
``config.diffdrive_configure_kwargs()`` has no real number to derive
``full_duty_velocity`` from, and inventing one would be exactly the
fabricated-calibration sprint.md's own Design Rationale rejects. So
``MoveQueue``/``drive()`` are structurally unusable for zetuv as
configured this sprint -- this is not a stylistic choice.

``diffdrive.driveDuty(dutyLeft, dutyRight, lease_ms)`` (RAW DUTY mode)
needs no ``fullDutyVelocity`` at all -- the vendored kernel's own
comment on ``driveDuty()``: "That is what makes it usable for plant-ID
runs on an uncalibrated robot." This module drives EVERY segment (legs
and pivots alike) through timed, encoder-terminated ``driveDuty()``
calls -- one uniform path, not a leg/pivot split, so there is nothing
to explain about mixing two different primitives.

**Units, bench-verified this ticket** (see the bench log's own
"combined-drive anomaly" write-up, ``docs/bench-log-zetuv-2026-08-19.md``):
``diffdrive.configure()``'s ``max_duty`` and ``diffdrive.driveDuty()``'s
``dutyLeft``/``dutyRight`` are PERCENT values (0-100), matching the
vendored kernel's own field comments (``vendor/differential_drive.h``:
``Config.maxDuty // [%]``, ``Command.dutyLeft // [%]``) -- NOT the
``[-1,1]`` fraction ``native/moddiffdrive.cpp``'s own file-header
comment claims. Passing small fractional values (e.g. ``max_duty=0.15``,
matching sprint 001/ticket 001's own bench convention) collapses to an
authority rail far below the write path's own 3% output-deadband floor,
so every commanded duty gets boosted to that SAME ~3% floor regardless
of what was asked for -- a value that sits right at the LEFT wheel
(port 2)'s own breakaway threshold, producing unreliable, sometimes-
zero motion that looked like a "combined-drive-specific" fault but
reproduced identically when driving LEFT alone (see the bench log).
This module uses the bench-verified-working PERCENT convention
throughout (``MAX_DUTY_PERCENT = 25.0`` authority rail,
``SEGMENT_DUTY_PERCENT = 6.0`` commanded duty) -- at this scale both
wheels move reliably, alone and combined (bench-verified, ``docs/
bench-log-zetuv-2026-08-19.md``).

**Honest limitation: ``omega_max`` is not met, and cannot be with this
primitive.** sprint.md's acceptance criteria ask for pivot rate "at or
below ``omega_max`` 2.4 rad/s" (a value carried over from radio-robot-
elite's closed-loop-controlled ``TOUR_SQUARE`` planner). ``driveDuty()``
is OPEN-LOOP raw PWM with no velocity feedback -- there is no dial that
maps to rad/s at all. Bench sweep this ticket (``docs/bench-log-
zetuv-2026-08-19.md``): zetuv's wheel plant is close to on/off around
its breakaway threshold -- 3% duty (this fleet's old, accidentally-tiny
effective value) was unreliable, but the very next step tested, 6%,
already produces ~480-680 mm/s at the wheel (measured
``velocityLeft``/``velocityRight``), which is 3-4x the ~150 mm/s a 2.4
rad/s pivot at this robot's 128 mm trackwidth would need. There is no
duty value bench-verified to be BOTH reliably above breakaway AND at or
below the omega_max-implied wheel speed. ``SEGMENT_DUTY_PERCENT = 6.0``
is the lowest duty bench-verified to move both wheels reliably (the
gentlest choice available), not a value chosen to satisfy the numeric
ceiling -- reaching that would need either a real velocity control loop
(this sprint's own no-cal scope excludes it) or the drive block's
``crawl_pulse`` dithering (``data/zetuv.json``'s ``crawl_pulse: 0.0``,
disabled, and tuning it is its own calibration exercise). Recorded here
and in the bench log rather than silently claimed as met.

**Geometry**, uncalibrated (this sprint's own scope: "wheels visibly
execute a square-ish tour", not survey-grade geometry): ``TICKS_PER_MM``
and ``TRACKWIDTH_MM`` below mirror ``data/zetuv.json``'s own
``wheels``/``geometry`` blocks, which are themselves INHERITED,
UNVERIFIED-ON-ZETUV template values (see that file's own provenance
note) -- carried here as plain module constants rather than read from
``/robot.json`` at runtime, so this module has no filesystem
dependency and works even before a config is copied onto the device.

**Termination is encoder-closed-loop, not a blind timer.** Each
segment polls ``diffdrive.output()`` and stops (commands neutral) once
the mean of ``|delta positionLeft|``/``|delta positionRight|`` reaches
the segment's target tick count (the same mean-of-both-wheels
convention ``motion.MoveQueue._distance_travelled()`` uses) -- or a
safety timeout elapses first, whichever comes first. A segment that
times out is stopped and logged, and the tour continues to the next
segment rather than aborting outright (this is a classroom demo, not a
precision-survey run -- see the acceptance criteria's own "uncalibrated
... square-ish" framing).
"""

import time

try:
    import diffdrive
    _ON_DEVICE = True
except ImportError:  # pragma: no cover -- exercised only off-device (CPython)
    _ON_DEVICE = False

# ---------------------------------------------------------------------
# Geometry -- mirrors data/zetuv.json's wheels/geometry blocks, INHERITED
# from tovez_nocal.json, NOT independently bench-verified on zetuv (see
# that file's own provenance note). Good enough for an uncalibrated
# "square-ish" tour, not a precision claim.
# ---------------------------------------------------------------------
TICKS_PER_MM = 1.4187
TRACKWIDTH_MM = 128.0
PI = 3.14159265358979323846

LEG_DISTANCE_MM = 500.0
PIVOT_ANGLE_RAD = PI / 2.0  # 90 degrees, LEFT (CCW)
OMEGA_MAX_RAD_S = 2.4  # sprint.md's own ceiling -- NOT achievable via
                        # driveDuty() on this uncalibrated plant; kept
                        # here for reference only, see the module
                        # docstring's own "Honest limitation" section

# ---------------------------------------------------------------------
# Duty / timing -- bench-verified this ticket (see module docstring).
# ---------------------------------------------------------------------
MAX_DUTY_PERCENT = 25.0       # diffdrive.configure()'s authority rail
SEGMENT_DUTY_PERCENT = 6.0    # commanded duty for every segment -- the
                               # gentlest bench-verified-reliable value,
                               # not an omega_max-derived one (see the
                               # module docstring's "Honest limitation")
CYCLE_PERIOD_MS = 24          # matches ticket 001's own bench convention

SEGMENT_LEASE_MS = 3000       # per-segment driveDuty() lease; well under
                               # the native binding's 5000 ms ceiling
SEGMENT_TIMEOUT_MS = 3000     # safety bound: stop and move on regardless
POLL_INTERVAL_MS = 50
SETTLE_MS = 1200              # TOUR_SQUARE's own rest-to-rest settle

LEFT_PORT = 2
RIGHT_PORT = 1
FWD_SIGN_LEFT = 1
FWD_SIGN_RIGHT = 1


def _leg_ticks(distance_mm, ticks_per_mm):
    return distance_mm * ticks_per_mm


def _pivot_ticks(angle_rad, trackwidth_mm, ticks_per_mm):
    arc_mm = angle_rad * (trackwidth_mm / 2.0)
    return arc_mm * ticks_per_mm


def build_square_tour(ticks_per_mm=TICKS_PER_MM, trackwidth_mm=TRACKWIDTH_MM,
                       leg_mm=LEG_DISTANCE_MM, pivot_rad=PIVOT_ANGLE_RAD):
    """Pure, offline-testable segment generator -- no hardware touched.
    Returns the 8-segment TOUR_SQUARE shape: leg, pivot, leg, pivot...
    (4 of each), as a list of dicts: ``{"kind": "leg"|"pivot",
    "target_ticks": float, "duty_left": float, "duty_right": float}``.
    ``duty_left``/``duty_right`` are the PERCENT (0-100) signs/values
    ``diffdrive.driveDuty()`` should be called with for that segment --
    a "leg" drives both wheels forward equally; a "pivot" drives them
    in opposite directions (LEFT/CCW: left reverses, right advances,
    matching the kernel's own ``twist`` sign convention -- ``out.twist
    = 0.5*(velocityRight - velocityLeft)``, CCW positive)."""
    leg_ticks = _leg_ticks(leg_mm, ticks_per_mm)
    pivot_ticks = _pivot_ticks(pivot_rad, trackwidth_mm, ticks_per_mm)
    segments = []
    for _ in range(4):
        segments.append({
            "kind": "leg",
            "target_ticks": leg_ticks,
            "duty_left": SEGMENT_DUTY_PERCENT,
            "duty_right": SEGMENT_DUTY_PERCENT,
        })
        segments.append({
            "kind": "pivot",
            "target_ticks": pivot_ticks,
            "duty_left": -SEGMENT_DUTY_PERCENT,
            "duty_right": SEGMENT_DUTY_PERCENT,
        })
    return segments


def _mean_abs_delta(out, start_left, start_right):
    delta_left = out["positionLeft"] - start_left
    delta_right = out["positionRight"] - start_right
    return (abs(delta_left) + abs(delta_right)) / 2.0, delta_left, delta_right


def _run_segment(index, segment):
    """Drives one segment to completion (target reached or timeout),
    then commands neutral and settles. Returns a small result dict for
    the caller to log -- this is the module's own bench-observation
    evidence trail, printed by run() below."""
    out0 = diffdrive.output()
    start_left = out0["positionLeft"]
    start_right = out0["positionRight"]

    status = diffdrive.driveDuty(segment["duty_left"], segment["duty_right"],
                                  SEGMENT_LEASE_MS)

    elapsed_ms = 0
    reached = False
    mean_delta = 0.0
    delta_left = 0.0
    delta_right = 0.0
    while elapsed_ms < SEGMENT_TIMEOUT_MS:
        time.sleep_ms(POLL_INTERVAL_MS)
        elapsed_ms += POLL_INTERVAL_MS
        out = diffdrive.output()
        mean_delta, delta_left, delta_right = _mean_abs_delta(
            out, start_left, start_right)
        if mean_delta >= segment["target_ticks"]:
            reached = True
            break

    diffdrive.neutral()
    time.sleep_ms(SETTLE_MS)

    return {
        "index": index,
        "kind": segment["kind"],
        "status": status,
        "target_ticks": segment["target_ticks"],
        "delta_left": delta_left,
        "delta_right": delta_right,
        "mean_delta": mean_delta,
        "reached": reached,
        "elapsed_ms": elapsed_ms,
    }


def run():
    """The demo's single entry point. Configures diffdrive directly
    (bypassing config.py/boot.py -- see module docstring for why),
    then drives the 8-segment square tour, printing per-segment
    encoder evidence as it goes."""
    if not _ON_DEVICE:
        raise RuntimeError(
            "demo_square.run() requires the diffdrive native module "
            "(run this on zetuv via mpremote, not under CPython)")

    cfg = diffdrive.configure(
        left_port=LEFT_PORT, right_port=RIGHT_PORT,
        fwd_sign_left=FWD_SIGN_LEFT, fwd_sign_right=FWD_SIGN_RIGHT,
        max_duty=MAX_DUTY_PERCENT, full_duty_velocity=0.0,
        cycle_period_ms=CYCLE_PERIOD_MS)
    print("demo_square: configure", cfg)
    print("demo_square: begin", diffdrive.begin())
    print("demo_square: start", diffdrive.start())
    time.sleep_ms(100)

    segments = build_square_tour()
    print("demo_square: tour has", len(segments), "segments")

    for i, segment in enumerate(segments):
        result = _run_segment(i, segment)
        print("demo_square: segment", result["index"], result["kind"],
              "status", result["status"],
              "target_ticks", result["target_ticks"],
              "delta_left", result["delta_left"],
              "delta_right", result["delta_right"],
              "mean_delta", result["mean_delta"],
              "reached", result["reached"],
              "elapsed_ms", result["elapsed_ms"])

    diffdrive.neutral()
    print("demo_square: tour complete")


if _ON_DEVICE:
    run()
