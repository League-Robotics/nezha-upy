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

**Geometry -- CORRECTED sprint 004 ticket 001, 2026-08-19** (root-cause
fix for the "legs run ~4-5x short" bug,
``clasi/sprints/004-square-tour-travel-units-fix/``, UC-003/UC-014;
full derivation in the bench log's own sprint-004 section,
``docs/bench-log-zetuv-2026-08-19.md``): ``TICKS_PER_MM`` below used to
mirror ``data/zetuv.json``'s own ``wheels`` block
(``wheel_diameter_mm=80.77``, ``ticks_per_rev=360`` -> ``ticks_per_mm=
1.4187``). BOTH of those two source numbers were unverified
``tovez_nocal.json`` template defaults, never independently measured on
ANY real Nezha unit in this repo's ``data/`` -- including
``data/tovez.json`` itself, whose own ``wheels`` block carries the
IDENTICAL unqualified 80.77/360/1.4187 trio with no camera/bench
provenance note, unlike every other calibrated group in that file, so
it offered no real second data point, only a matching template
default. The arithmetic combining them (``ticks_per_mm = ticks_per_rev
/ (pi * wheel_diameter_mm)``) was correct; the two INPUT numbers were
simply wrong, by a factor that made every leg/pivot's
encoder-termination target ~4.2-5.3x too small -- exactly matching the
stakeholder's live bench observation (2026-08-19): a "500 mm" leg
turned the wheels only ~270 degrees (0.75 rev, the issue's own golden
measurement), not the ~3.3-3.6 rev that 500 mm actually needs on a
~145 mm-circumference Nezha wheel.

**Fix**: ``TICKS_PER_MM`` is now derived from the stakeholder's own
empirical bench anchor, per the issue's explicit instruction that the
empirical number governs on conflict with any borrowed/templated
value. Sprint-002 run-1's four leg segments (the run the issue itself
cites) delivered mean per-wheel encoder deltas of
725.5/719.0/730.5/750.5 counts (``docs/bench-log-zetuv-2026-08-19.md``
Sec 15) for that same observed 0.75 rev, averaging 731.4 counts -- an
empirical counts-per-revolution of 731.4 / 0.75 = 975.2 (the issue's
own stated range is ~870-1080; its midpoint, 975, is used here as the
clean anchor -- see ``EMPIRICAL_COUNTS_PER_REV`` below). Combined with
the issue's stated wheel circumference (``WHEEL_CIRCUMFERENCE_MM`` =
145.0 mm) this gives ``TICKS_PER_MM`` = 975.0 / 145.0 ~= 6.7241 -- a
~4.74x correction, landing squarely in the ticket's own expected
4-5x / 3.3-3.6-rev band (bench-re-verified, see the bench log).

**Cross-checked against, and found to CONFLICT with,**
``data/tovez.json``'s own ``motors.travel_calib_left/right`` (0.7837)
-- the one "travel calibration"-named field that DOES carry a real
vendor-grounded unit (``vendor/nezha_motor.h``'s own comments confirm
``travel_calib``'s units are literally mm PER DEGREE of raw encoder
shaft rotation, and that the raw encoder register itself reports
TENTHS of a degree, i.e. 10 counts/degree): that implies
``ticks_per_mm`` = 1 / (0.7837 / 10) ~= 12.76, roughly 1.9x the
empirical-anchored 6.7241 above. Per the issue's own explicit
instruction ("if they disagree, the empirical bench number wins"), the
empirical anchor governs here, NOT ``travel_calib`` -- flagged, not
silently discarded: this disagreement, plus ``src/config.py``'s own
already-flagged uncertainty about ``travel_calib``'s "x10" multiplier
("No document in this repo elaborates the multiplier's derivation
further than 'x10'"), together suggest ``travel_calib`` itself may be
an unverified/stale figure, not a settled reference -- worth a fresh
camera pass before trusting either number as final. Also note
``travel_calib_left/right`` feeds a DIFFERENT kernel field entirely
(``fullDutyVelocity``, VELOCITY-mode ``drive()``'s plant-gain
calibration, ``src/config.py``'s own
``wheel_control_to_diffdrive_config()``) -- this module never calls
``drive()``/reads ``travel_calib`` at all (see "Why direct diffdrive
calls" above), so it was never the field actually driving this bug,
regardless of the conflict above.

``data/zetuv.json``'s own ``wheels`` block is updated to match (same
derivation, same provenance note) for consistency between the repo's
config source of truth and this module's own hardcoded mirror -- still
NOT independently camera/tape-verified on zetuv's own physical wheel,
same disclosed-not-hidden caveat this whole file already carried
before this fix. This module still reads nothing from ``/robot.json``
at runtime -- ``TICKS_PER_MM``/``TRACKWIDTH_MM`` remain plain module
constants, so it has no filesystem dependency and works even before a
config is copied onto the device.

``TRACKWIDTH_MM`` (128.0) is UNCHANGED and NOT part of this bug --
``data/tovez.json``'s own ``geometry._trackwidth_note``: "the
CALIPER-MEASURED wheel separation (stakeholder, 128 mm) ... the one
independently verifiable number in this file," and pivots scale
correctly off it (bench-re-verified, the same ~4.74x factor as legs --
see the bench log).

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
# Geometry -- CORRECTED sprint 004 ticket 001, 2026-08-19 (root-cause
# units fix). See module docstring's "Geometry" section for the full
# derivation, the tovez.json travel_calib cross-check, and why the
# empirical bench anchor governs. Mirrors data/zetuv.json's own
# wheels block (kept in sync, same derivation/provenance note there).
# ---------------------------------------------------------------------
WHEEL_CIRCUMFERENCE_MM = 145.0     # [mm] issue's own stated figure --
                                    # not independently re-measured this
                                    # ticket (no camera/caliper access
                                    # available to this agent)
EMPIRICAL_COUNTS_PER_REV = 975.0   # [counts/rev] stakeholder's own
                                    # golden-measurement anchor -- see
                                    # module docstring for the full
                                    # sprint-002-run-1-derived math
TICKS_PER_MM = EMPIRICAL_COUNTS_PER_REV / WHEEL_CIRCUMFERENCE_MM  # ~6.7241
TRACKWIDTH_MM = 128.0               # [mm] UNCHANGED -- caliper-measured,
                                    # not part of this bug (see docstring)
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

SEGMENT_LEASE_MS = 600        # per-driveDuty() safety lease -- REFRESHED
                               # periodically by _run_segment() (see
                               # LEASE_REFRESH_MS) rather than held for a
                               # whole segment. CORRECTED sprint 004 ticket
                               # 001: the old single-shot 3000 ms lease was
                               # sized for the old, wrong (~4-5x too short)
                               # leg targets; the corrected ~3362-tick leg
                               # target needs ~4.2-4.9 s of continuous drive
                               # at SEGMENT_DUTY_PERCENT (bench-measured,
                               # docs/bench-log-zetuv-2026-08-19.md), which
                               # would sit right at (or over) the native
                               # binding's own hard 5000 ms single-lease
                               # ceiling (refused outright above it, never
                               # clamped) if held as one long lease. A
                               # short, frequently-renewed lease reaches the
                               # same total drive duration while keeping the
                               # lease's own fail-safe intent tight (a
                               # polling loop that itself hangs still loses
                               # the wheels within one lease period, not
                               # within whatever the segment's full budget
                               # is).
LEASE_REFRESH_MS = 400        # reissue driveDuty() this often while still
                               # driving -- comfortably inside
                               # SEGMENT_LEASE_MS so the lease never
                               # actually expires mid-drive under normal
                               # poll timing
SEGMENT_TIMEOUT_MS = 6000     # CORRECTED sprint 004 ticket 001: overall
                               # per-segment safety bound, decoupled from
                               # the native binding's 5000 ms single-lease
                               # ceiling now that driveDuty() is reissued
                               # (see SEGMENT_LEASE_MS above). Sized with
                               # real margin over the corrected leg
                               # target's bench-measured ~4.2-4.9 s typical
                               # completion time; pivots finish in ~1 s and
                               # exit this bound long before it matters.
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
    evidence trail, printed by run() below.

    CORRECTED sprint 004 ticket 001: driveDuty()'s lease is now
    REFRESHED periodically (every LEASE_REFRESH_MS) rather than held
    once for the whole segment -- see SEGMENT_LEASE_MS's own comment
    for why. If a refresh call itself refuses (e.g. an estop landed
    mid-segment), the loop stops driving immediately rather than
    continuing to poll a segment nothing is actually advancing."""
    out0 = diffdrive.output()
    start_left = out0["positionLeft"]
    start_right = out0["positionRight"]

    status = diffdrive.driveDuty(segment["duty_left"], segment["duty_right"],
                                  SEGMENT_LEASE_MS)

    elapsed_ms = 0
    since_refresh_ms = 0
    reached = False
    mean_delta = 0.0
    delta_left = 0.0
    delta_right = 0.0
    refresh_status = status
    while elapsed_ms < SEGMENT_TIMEOUT_MS and refresh_status == "ok":
        time.sleep_ms(POLL_INTERVAL_MS)
        elapsed_ms += POLL_INTERVAL_MS
        since_refresh_ms += POLL_INTERVAL_MS
        out = diffdrive.output()
        mean_delta, delta_left, delta_right = _mean_abs_delta(
            out, start_left, start_right)
        if mean_delta >= segment["target_ticks"]:
            reached = True
            break
        if since_refresh_ms >= LEASE_REFRESH_MS:
            refresh_status = diffdrive.driveDuty(
                segment["duty_left"], segment["duty_right"], SEGMENT_LEASE_MS)
            since_refresh_ms = 0

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
