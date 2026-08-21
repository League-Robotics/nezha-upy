"""demo_square -- on-device square tour demo. Drives 4 x 500 mm
straight legs interleaved with 4 x 90-degree LEFT (CCW) in-place
pivots, rest-to-rest, matching radio-robot-elite's ``TOUR_SQUARE``
shape.

Run standalone (with zetuv connected and ``diffdrive`` reachable over
USB)::

    mpremote connect /dev/cu.usbmodemXXXXXXX run src/demo_square.py

(resolve the port via ``mbdeploy list``, matched by UID, never a board
name alone).

Drives ``diffdrive`` directly, not ``motion.MoveQueue`` --
``MoveQueue`` only drives velocity mode via ``diffdrive.drive()``,
which the vendored kernel refuses whenever ``fullDutyVelocity <= 0``
(uncalibrated, zetuv's current state). ``_configure_and_start()``
tries the kernel's own per-wheel PID (velocity mode, bench-derived
``VELOCITY_GAINS``) first; falls back to raw duty (``driveDuty()``)
only if the binding predates the PID kwargs or the kernel's own ready
flag says calibration didn't take.

LANDMINE: ``diffdrive.configure()``'s ``max_duty`` and
``driveDuty()``'s ``dutyLeft``/``dutyRight`` are PERCENT values
(0-100) -- NOT the ``[-1,1]`` fraction ``native/moddiffdrive.cpp``'s
own file-header comment claims. Passing fractional values collapses
every commanded duty to the write path's ~3% output-deadband floor
(docs/bench-log-zetuv-2026-08-19.md).

LANDMINE: ``omega_max`` (2.4 rad/s pivot rate, sprint.md's own
ceiling) is not achievable via ``driveDuty()`` on this open-loop,
uncalibrated plant -- the duty constants below are the lowest
bench-verified to move both wheels reliably above breakaway, not
values chosen to hit that ceiling (bench log).

Geometry (``WHEEL_DIAMETER_MM``, ``EMPIRICAL_COUNTS_PER_REV``,
``TICKS_PER_MM``) has been corrected twice on bench/stakeholder
evidence (wrong template wheel numbers, then wrong circumference
input) and is now config-driven from ``robot.json``'s ``wheels`` block
via a dependency-free scan
(``demo_util.geometry_from_robot_config()``), with the values below as
a hardcoded fallback -- NOT via ``config.load_robot_config()``, whose
fail-closed required-key gate zetuv's no-calibration config can never
satisfy. Full derivation and bench evidence:
docs/bench-log-zetuv-2026-08-19.md. Still not independently
camera/tape-verified on zetuv's own physical wheel. ``TRACKWIDTH_MM``
is caliper-measured and NOT config-driven.

Wiring (``LEFT_PORT``/``RIGHT_PORT``/``FWD_SIGN_LEFT``/
``FWD_SIGN_RIGHT``) is likewise config-driven with a per-robot
hardcoded fallback -- never safe to hardcode one robot's signs for a
module shared across robots (tovez's own config has
``fwd_sign_left=-1``).

Termination is encoder-closed-loop, not a blind timer: each segment
polls ``diffdrive.output()`` and stops (commands neutral) once the
mean of ``|delta positionLeft|``/``|delta positionRight|`` reaches the
segment's target tick count, or a safety timeout elapses first. A
timed-out segment is logged and the tour continues to the next segment
(classroom demo, not a precision-survey run).

``run_single_leg()`` (button B) reuses the SAME
``_configure_and_start()``/``_leg_ticks()``/``_run_segment()`` pieces
``run()`` (button A, full tour) uses -- one segment instead of eight.

Auto-run: the bottom-of-file ``if __name__ == "__main__":`` guard is
for the standalone bench-debug entry point only (not yet independently
bench-verified that ``mpremote ... run`` executes with
``__name__ == "__main__"`` -- see bench log); ``main.py``'s button
handlers call ``run()``/``run_single_leg()`` explicitly and do not
depend on it at all.

Learned per-segment bias/coast-lead state persists across the
per-press module reload via ``tour_state.csv`` (see ``STATE_PATH``).
"""

import time

try:
    import diffdrive
    _ON_DEVICE = True
except ImportError:  # pragma: no cover -- exercised only off-device (CPython)
    _ON_DEVICE = False

# LANDMINE: this firmware ships neither ujson nor json (bench-confirmed)
# -- geometry below is read via a dependency-free two-key scan instead.

# --- Geometry -- see module docstring; mirrors data/zetuv.json -------
PI = 3.14159265358979323846

ROBOT_CONFIG_PATH = "robot.json"  # bare, no leading slash -- see main.py

import demo_util
# Split-module aliases (compile-heap ceiling; see demo_util).
_scan_number = demo_util._scan_number
geometry_from_robot_config = demo_util.geometry_from_robot_config
_wiring_from_robot_config = demo_util._wiring_from_robot_config
balanced_duties = demo_util.balanced_duties
BALANCE_GAIN = demo_util.BALANCE_GAIN
BALANCE_TRIM_MAX = demo_util.BALANCE_TRIM_MAX
BALANCE_KI = demo_util.BALANCE_KI
BALANCE_BIAS_MAX = demo_util.BALANCE_BIAS_MAX
BALANCE_BIAS_SEED = demo_util.BALANCE_BIAS_SEED


# Config-driven with a hardcoded fallback (see module docstring). Only
# attempted on-device -- under CPython there is no real robot.json, so
# the fallback constants are used deterministically every time.
_CONFIG_GEOMETRY = geometry_from_robot_config() if _ON_DEVICE else None
GEOMETRY_SOURCE = "robot.json" if _CONFIG_GEOMETRY is not None else "hardcoded fallback"

if _CONFIG_GEOMETRY is not None:
    WHEEL_DIAMETER_MM, EMPIRICAL_COUNTS_PER_REV = _CONFIG_GEOMETRY
else:
    WHEEL_DIAMETER_MM = 90.0             # [mm] fallback -- calibration
                                          # iteration point, not final
                                          # (mirrors data/zetuv.json)
    EMPIRICAL_COUNTS_PER_REV = 975.0     # [counts/rev] fallback --
                                          # empirical bench anchor,
                                          # mirrors data/zetuv.json

WHEEL_CIRCUMFERENCE_MM = PI * WHEEL_DIAMETER_MM  # [mm] derived, ~282.74 at fallback
TICKS_PER_MM = EMPIRICAL_COUNTS_PER_REV / WHEEL_CIRCUMFERENCE_MM  # [ticks/mm] ~3.4484 at fallback
TRACKWIDTH_MM = 128.0  # [mm] caliper-measured; NOT config-driven (only wheel diameter/ticks_per_rev are)

LEG_DISTANCE_MM = 500.0
PIVOT_ANGLE_RAD = PI / 2.0  # 90 degrees, LEFT (CCW)
OMEGA_MAX_RAD_S = 2.4  # [rad/s] reference ceiling only -- not achievable via driveDuty() (see module docstring)

# --- Duty / timing -- bench-verified; see module docstring ----------
MAX_DUTY_PERCENT = 25.0       # [%] LEGACY duty-mode rail: balanced_duties()
                              # clamps to it and SEGMENT_DUTY_PERCENT is
                              # calibrated against it. Not the velocity-mode
                              # rail -- see VELOCITY_MAX_DUTY.
VELOCITY_MAX_DUTY = 100.0     # [%] velocity-mode authority rail. 25% left
                              # almost no headroom over ~18% cruise, so the
                              # PID could not correct; the kernel's own duty
                              # limiting keeps this safe.
SEGMENT_DUTY_PERCENT = 15.0   # [%] commanded duty per segment -- 6% sat
                               # below breakaway on combined-load drive;
                               # 15% clears it on both robots (bench log)
CYCLE_PERIOD_MS = 32          # [ms]

SEGMENT_LEASE_MS = 600        # [ms] per-driveDuty() safety lease --
                               # REFRESHED periodically (LEASE_REFRESH_MS),
                               # not held for a whole segment: a short,
                               # frequently-renewed lease keeps the
                               # fail-safe tight (a hung poll loop loses
                               # the wheels within one lease period, not
                               # the segment's whole budget) while still
                               # clearing the native binding's hard
                               # 5000 ms single-lease ceiling.
LEASE_REFRESH_MS = 400        # [ms] reissue driveDuty() this often while
                               # still driving -- comfortably inside
                               # SEGMENT_LEASE_MS so it never expires
                               # mid-drive under normal poll timing
SEGMENT_TIMEOUT_MS = 6000     # [ms] overall per-segment safety bound,
                               # decoupled from the native binding's
                               # 5000 ms single-lease ceiling now that
                               # driveDuty() is reissued (see
                               # SEGMENT_LEASE_MS)
POLL_INTERVAL_MS = 25   # [ms] finer cut resolution: a 12%-duty pivot
                         # covers ~20-30 ticks per poll
SETTLE_MS = 1200              # [ms] TOUR_SQUARE's own rest-to-rest settle

# LANDMINE: wiring is PER-ROBOT (config-driven from robot.json's motors
# group, falling back to zetuv's bench-measured values below) --
# tovez's own calibrated config has fwd_sign_left=-1, so hardcoding
# either robot's signs would silently mis-drive the other.
_CONFIG_WIRING = _wiring_from_robot_config() if _ON_DEVICE else None
WIRING_SOURCE = "robot.json" if _CONFIG_WIRING is not None else "hardcoded fallback"

if _CONFIG_WIRING is not None:
    LEFT_PORT, RIGHT_PORT, FWD_SIGN_LEFT, FWD_SIGN_RIGHT = _CONFIG_WIRING
else:
    LEFT_PORT = 2       # zetuv, bench-measured
    RIGHT_PORT = 1      # zetuv, bench-measured
    FWD_SIGN_LEFT = 1   # zetuv, bench-measured
    FWD_SIGN_RIGHT = 1  # zetuv, bench-measured


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
            "duty_left": -PIVOT_DUTY_PERCENT,
            "duty_right": PIVOT_DUTY_PERCENT,
        })
    return segments


def _mean_abs_delta(out, start_left, start_right):
    delta_left = out["positionLeft"] - start_left
    delta_right = out["positionRight"] - start_right
    return (abs(delta_left) + abs(delta_right)) / 2.0, delta_left, delta_right


# Learned feedforward bias, carried across segments/runs within a boot.
# Seeded from measured plant asymmetry (right out-runs left ~1.5x at
# 15% duty -- a physical-motor property, port-swap-confirmed).
_segment_bias = {"leg": BALANCE_BIAS_SEED, "pivot": BALANCE_BIAS_SEED}

# Two-phase segment drive: full duty to CREEP_START_FRACTION of target,
# then creep, to kill coast overshoot (was +0.5..19% over-rotation).
# Creep must stay above the left motor's breakaway (>=~10-12%).
CREEP_DUTY_PERCENT = 12.0
CREEP_START_FRACTION = {"leg": 0.80, "pivot": 0.50}

# Pivots are short (~300 ms at 15%) -- too fast for creep/lead to act
# (bench: corner misses oscillated +28%..-17%). Slower gives room.
PIVOT_DUTY_PERCENT = 12.0

# Adaptive coast compensation: stop driving this many ticks before the
# target and let momentum land the rest; updated per segment kind from
# the measured final-vs-target miss.
_coast_lead = {"leg": 60.0, "pivot": 100.0}   # bench-informed seeds
COAST_LEAD_LEARN = 0.5   # [1] fraction of the miss folded into the lead
COAST_LEAD_MAX = 200.0   # [ticks]

# LANDMINE: main.py reloads this module on every press (sys.modules.pop
# + import), which would wipe learned bias/lead each run -- this CSV
# carries them across reloads (fail-soft; delete to reset learning).
STATE_PATH = "tour_state.csv"


def _load_state():
    try:
        with open(STATE_PATH, "r") as f:
            parts = f.read().split(",")
        if len(parts) == 4:
            _segment_bias["leg"] = float(parts[0])
            _segment_bias["pivot"] = float(parts[1])
            _coast_lead["leg"] = float(parts[2])
            _coast_lead["pivot"] = float(parts[3])
    except (OSError, ValueError):
        pass


def _save_state():
    try:
        with open(STATE_PATH, "w") as f:
            f.write("%f,%f,%f,%f" % (
                _segment_bias["leg"], _segment_bias["pivot"],
                _coast_lead["leg"], _coast_lead["pivot"]))
    except OSError:
        pass


if _ON_DEVICE:
    _load_state()


def _run_segment(index, segment):
    """Drives one segment to completion (target reached or timeout),
    then commands neutral and settles. Returns a small result dict for
    the caller to log/print.

    ``driveDuty()``'s lease is REFRESHED periodically (every
    ``LEASE_REFRESH_MS``) rather than held once for the whole segment
    -- see ``SEGMENT_LEASE_MS``. If a refresh call itself refuses (e.g.
    an estop landed mid-segment), the loop stops driving immediately
    rather than continuing to poll a segment nothing is advancing."""
    out0 = diffdrive.output()
    start_left = out0["positionLeft"]
    start_right = out0["positionRight"]

    bias = _segment_bias.get(segment["kind"], BALANCE_BIAS_SEED)
    lead = _coast_lead.get(segment["kind"], 40.0)
    if _velocity_mode:
        # Kernel PID owns straightness/symmetry -- no Python trim.
        if segment["kind"] == "leg":
            vel_cmd = CRUISE_VELOCITY if segment["duty_left"] > 0 else -CRUISE_VELOCITY
            twist_cmd = 0.0
        else:
            vel_cmd = 0.0
            twist_cmd = PIVOT_TWIST if segment["duty_right"] > 0 else -PIVOT_TWIST
        status = diffdrive.drive(vel_cmd, twist_cmd, SEGMENT_LEASE_MS)
    else:
        vel_cmd = 0.0
        twist_cmd = 0.0
        duty_l0, duty_r0 = balanced_duties(
            segment["duty_left"], segment["duty_right"], 0.0, 0.0, bias=bias)
        status = diffdrive.driveDuty(duty_l0, duty_r0, SEGMENT_LEASE_MS)

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
        # Adaptive early stop: cut drive a learned coast-lead BEFORE the
        # target; momentum lands the remainder (measured after settle).
        if mean_delta >= segment["target_ticks"] - lead:
            reached = True
            break
        in_creep = mean_delta >= (segment["target_ticks"]
                                  * CREEP_START_FRACTION[segment["kind"]])
        if _velocity_mode:
            # Kernel PID path: refresh drive() every poll (lease
            # renewal); creep = reduced commanded speed near target.
            scale = (CREEP_VELOCITY_FRACTION[segment["kind"]]
                     if in_creep else 1.0)
            refresh_status = diffdrive.drive(
                vel_cmd * scale, twist_cmd * scale, SEGMENT_LEASE_MS)
        else:
            # Legacy raw-duty path (uncalibrated robots): Python
            # encoder-balancing PI trim, re-issued EVERY poll.
            err = abs(delta_left) - abs(delta_right)
            bias += BALANCE_KI * err
            if bias > BALANCE_BIAS_MAX:
                bias = BALANCE_BIAS_MAX
            elif bias < -BALANCE_BIAS_MAX:
                bias = -BALANCE_BIAS_MAX
            if in_creep:
                duty_base_l = (CREEP_DUTY_PERCENT
                               if segment["duty_left"] > 0
                               else -CREEP_DUTY_PERCENT)
                duty_base_r = (CREEP_DUTY_PERCENT
                               if segment["duty_right"] > 0
                               else -CREEP_DUTY_PERCENT)
            else:
                duty_base_l = segment["duty_left"]
                duty_base_r = segment["duty_right"]
            duty_l, duty_r = balanced_duties(
                duty_base_l, duty_base_r, delta_left, delta_right,
                bias=bias)
            refresh_status = diffdrive.driveDuty(duty_l, duty_r,
                                                 SEGMENT_LEASE_MS)
        since_refresh_ms = 0

    diffdrive.neutral()
    _segment_bias[segment["kind"]] = bias
    time.sleep_ms(SETTLE_MS)

    # Post-settle final measurement (includes coast) -- the geometric
    # truth the tour traces; the miss feeds the next segment's coast lead.
    out_final = diffdrive.output()
    mean_delta, delta_left, delta_right = _mean_abs_delta(
        out_final, start_left, start_right)
    miss = mean_delta - segment["target_ticks"]
    lead += COAST_LEAD_LEARN * miss
    if lead < 0.0:
        lead = 0.0
    elif lead > COAST_LEAD_MAX:
        lead = COAST_LEAD_MAX
    _coast_lead[segment["kind"]] = lead

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


def _require_on_device(caller_name):
    if not _ON_DEVICE:
        raise RuntimeError(
            "demo_square.%s() requires the diffdrive native module "
            "(run this on zetuv via mpremote, not under CPython)" % (caller_name,))


# --- Velocity mode: the kernel's own per-wheel PID -------------------
# Gains below are tovez's calibrated wheel_control values converted
# mm->counts at the bench-measured 3.8424 counts/mm (JSON is mm-era;
# the kernel is counts-native). fullDutyVelocity is bench-derived:
# 15%->~1050 c/s, 25%->~1915 c/s per wheel => ~8500 c/s at 100%.
VELOCITY_GAINS = {
    # Design values in mm-based units, scaled to counts by the robot's
    # OWN ticks/mm at import. The old table hardcoded counts derived from
    # 3.8424 ticks/mm -- the calibration disproved by the encoder audit --
    # so on tovez (12.76) every limit was 3.3x too small: the PID had
    # 30 mm/s of authority where 100 was intended. That starvation, not
    # the move profile, was the field wobble.
    "full_duty_velocity": 10715.0,  # [counts/s] MEASURED, tools/plant_id.py
    "pid_kp": 0.6,                  # [1] was 0.0 (pure-I). The kernel models
                                    # gain by |speed| only, so a pivot's
                                    # reversed wheel -- ~16% weaker in reverse,
                                    # measured -- is mismodeled and only the
                                    # integrator could fix it. kp cuts turn
                                    # scatter from 6.4 deg range to ~2.
    "pid_ki": 6.0,                  # [1/s]
    "pid_i_max": 60.0 * TICKS_PER_MM,
    "pid_kaff": 0.0,
    "pid_max": 100.0 * TICKS_PER_MM,
    "pos_err_max": 10.0 * TICKS_PER_MM,
    "v_min": 20.0 * TICKS_PER_MM,   # [counts/s] ~3% duty: the motor deadband.
                                    # NOTE applySpeedFloor rescales BOTH wheels
                                    # up to this, so a taper crawl commanded
                                    # below it does not actually slow down.
    "bias_max": 23.8 * TICKS_PER_MM,
    "tau_adapt": 30.0,              # [s]
    "a_steady": 30.0 * TICKS_PER_MM,
    "twist_hold_gain": 2.0,         # [1/s] encoder-ratio straightness hold
    "stall_speed": 15.0 * TICKS_PER_MM,
    "stall_demand": 0.0,            # detector OFF: arms during accel ramps and
                                    # the binding exposes no clearStallLatch,
                                    # so one latch killed the rest of a tour.
                                    # Lease + watchdog still cover runaways.
    "stall_window": 500.0,          # [ms]
    "wheel_gain_left": 0.892,       # MEASURED (plant_id): L 9554 c/s full duty
    "wheel_gain_right": 1.108,      # MEASURED: R 11875 c/s full duty
    "wheel_intercept_left": 0.0,
    "wheel_intercept_right": 0.0,
}
CRUISE_VELOCITY = 1300.0    # [counts/s] leg speed (~15%-duty-equivalent)
PIVOT_TWIST = 800.0         # [counts/s] pivot half-difference (CCW +)
CREEP_VELOCITY_FRACTION = {"leg": 0.4, "pivot": 0.85}
# Pivot creep stays high: left wheel's reverse breakaway needs ~15%+
# duty-equivalent; a lower creep twist stalls it (bench).

_velocity_mode = False      # set by _configure_and_start from ready flag
_started = False            # once-per-boot bracket latch -- see _configure_and_start


def _gain_overrides(path=ROBOT_CONFIG_PATH):
    """Optional per-robot overrides: a "demo_velocity" object in
    robot.json whose keys match VELOCITY_GAINS/CRUISE/PIVOT names.
    Lets gain tuning iterate by config re-copy, no reflash (the demo
    modules are frozen). Fail-soft: absent file/group/ujson -> {}."""
    try:
        import gc
        gc.collect()  # parse needs ~3 KB contiguous; defragment first
        import ujson
        with open(path, "r") as f:
            doc = ujson.loads(f.read())
        group = doc.get("demo_velocity", {})
        del doc
        gc.collect()
        return group if isinstance(group, dict) else {}
    except (ImportError, OSError, ValueError, MemoryError):
        # MemoryError included deliberately: parsing the whole config
        # needs ~3 KB contiguous and a fragmented press-time heap can
        # refuse it (bench: every press faulted here). Overrides are
        # OPTIONAL -- defaults must drive; a tuning nicety must never
        # cost the button.
        return {}


def _configure_and_start(caller_name):
    """Shared ``diffdrive.configure()``/``begin()``/``start()``
    bracketing -- ``run()`` (button A) and ``run_single_leg()``
    (button B) both call this identically, so wiring facts (ports/
    signs/duty rail) can never drift between the two entry points.

    Tries VELOCITY mode first (kernel per-wheel PID, VELOCITY_GAINS);
    the kernel's own ready flag is the authority for whether it took.
    Falls back to raw duty mode if the binding predates the PID kwargs
    or calibration is absent."""
    global _velocity_mode, CRUISE_VELOCITY, PIVOT_TWIST, _started
    if _started:
        # LANDMINE: the bracket must run ONCE PER BOOT. start() is
        # irreversible by design (no stop(); the kernel fiber's run()
        # never returns), so a second configure() placement-news the
        # kernel UNDER the live fiber and a second start() launches a
        # second fiber on the same storage. Bench-measured: press 2
        # "completed" in 25 ms on a -41255-count encoder discontinuity,
        # press 3 timed out with the wheels dead. Idempotent re-entry
        # keeps every later press on the healthy first-boot kernel.
        print("demo_square: %s reusing running kernel" % (caller_name,))
        return
    _velocity_mode = False
    gains = dict(VELOCITY_GAINS)
    if _ON_DEVICE:
        ov = _gain_overrides()
        for k, v in ov.items():
            if k == "cruise_velocity":
                CRUISE_VELOCITY = float(v)
            elif k == "pivot_twist":
                PIVOT_TWIST = float(v)
            elif k in gains:
                gains[k] = float(v)
    try:
        cfg = diffdrive.configure(
            left_port=LEFT_PORT, right_port=RIGHT_PORT,
            fwd_sign_left=FWD_SIGN_LEFT, fwd_sign_right=FWD_SIGN_RIGHT,
            max_duty=VELOCITY_MAX_DUTY,
            cycle_period_ms=CYCLE_PERIOD_MS, **gains)
    except TypeError:
        cfg = diffdrive.configure(
            left_port=LEFT_PORT, right_port=RIGHT_PORT,
            fwd_sign_left=FWD_SIGN_LEFT, fwd_sign_right=FWD_SIGN_RIGHT,
            max_duty=MAX_DUTY_PERCENT, full_duty_velocity=0.0,
            cycle_period_ms=CYCLE_PERIOD_MS)
    print("demo_square: %s configure" % (caller_name,), cfg)
    print("demo_square: %s begin" % (caller_name,), diffdrive.begin())
    print("demo_square: %s start" % (caller_name,), diffdrive.start())
    time.sleep_ms(100)
    _started = True
    _velocity_mode = bool(diffdrive.output().get("ready", False))
    print("demo_square: %s mode" % (caller_name,),
          "VELOCITY(PID)" if _velocity_mode else "raw-duty fallback")


MOVE_RAMP_MS = 400.0        # [ms] accel ramp floor->full (pxt serviceMove port)
MOVE_DIST_TAPER = 600.0     # [counts] ~47 mm decel window
MOVE_YAW_TAPER = 360.0      # [counts] ~30 deg decel window
MOVE_DIST_MARGIN = 35.0     # [counts] ~3mm: the measured brake+coast at floor 0.18
MOVE_YAW_MARGIN = 12.0      # [counts] ~0.9deg: centered on measured turn coast
MOVE_YAW_RATE_DEG_S = 60.0  # [deg/s] pivot rate


def _move(dist_mm, yaw_deg, speed_mm_s):
    """Tuned move: accel ramp, end-of-move taper, active brake. Port of
    pxt-nezha-diffdrive serviceMove(); bench-measured on tovez it took
    the 50 cm square tour from 171 mm closure to 9 mm. Velocity mode
    only -- callers fall back to the segment engine without it."""
    o = diffdrive.output()
    p0l = o["positionLeft"]; p0r = o["positionRight"]
    dt = dist_mm * TICKS_PER_MM
    yt = _pivot_ticks(yaw_deg * 0.0174533, TRACKWIDTH_MM, TICKS_PER_MM)
    spd = speed_mm_s * TICKS_PER_MM
    yr = _pivot_ticks(MOVE_YAW_RATE_DEG_S * 0.0174533, TRACKWIDTH_MM,
                      TICKS_PER_MM)
    dur = 0.0
    if dt:
        dur = abs(dt) / spd
    if yt:
        yd = abs(yt) / yr
        if yd > dur:
            dur = yd
    if dur <= 0:
        return
    vel = dt / dur; tw = yt / dur
    pure = (yt != 0 and dt == 0)
    floor = 0.15 if pure else 0.18
    ymargin = MOVE_YAW_MARGIN if pure else MOVE_DIST_MARGIN
    start = time.ticks_ms()
    deadline = int(dur * 1800) + 4000
    diffdrive.drive(vel * floor, tw * floor, 500)
    while True:
        o = diffdrive.output()
        dl = o["positionLeft"] - p0l; dr = o["positionRight"] - p0r
        mp = (dl + dr) * 0.5; dp = (dr - dl) * 0.5
        scale = 1.0; dd = True; yd_ = True
        if dt:
            rem = abs(dt) - abs(mp); dd = rem <= MOVE_DIST_MARGIN
            sc = rem / MOVE_DIST_TAPER
            if sc < scale:
                scale = sc
        if yt:
            rem = abs(yt) - abs(dp); yd_ = rem <= ymargin
            sc = rem / MOVE_YAW_TAPER
            if sc < scale:
                scale = sc
        if scale < floor:
            scale = floor
        ramp = time.ticks_diff(time.ticks_ms(), start) / MOVE_RAMP_MS
        if ramp < floor:
            ramp = floor
        if ramp < scale:
            scale = ramp
        if scale > 1.0:
            scale = 1.0
        if dd and yd_:
            break
        if o["stallHalted"] or \
                time.ticks_diff(time.ticks_ms(), start) > deadline:
            break
        diffdrive.drive(vel * scale, tw * scale, 500)
        time.sleep_ms(32)
    diffdrive.drive(0.0, 0.0, 300)   # active zero-hold brake
    time.sleep_ms(250)
    diffdrive.neutral()
    time.sleep_ms(350)
    o = diffdrive.output()
    print("demo_square: move d=%.0fmm y=%.0fdeg dL=%.0f dR=%.0f" % (
        dist_mm, yaw_deg, o["positionLeft"] - p0l, o["positionRight"] - p0r))


def run():
    """The square tour entry point (button A). Configures diffdrive
    directly, then drives the 8-segment square tour, printing
    per-segment encoder evidence as it goes."""
    _require_on_device("run")
    _configure_and_start("run")

    if _velocity_mode:
        print("demo_square: tour (tuned move engine)")
        for _i in range(4):
            _move(LEG_DISTANCE_MM, 0.0, 100.0)
            _move(0.0, 90.0, 100.0)
        diffdrive.neutral()
        _save_state()
        print("demo_square: tour complete")
        return

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
    _save_state()
    print("demo_square: tour complete")


def run_single_leg(distance_mm=LEG_DISTANCE_MM, ticks_per_mm=TICKS_PER_MM):
    """Button B's straight-drive entry point -- drives ONE leg segment
    of ``distance_mm`` (default 500 mm) via the SAME
    ``_configure_and_start()``/``_leg_ticks()``/``_run_segment()``
    pieces ``run()``'s square-tour legs use, reused rather than
    reimplemented. Returns the single segment's result dict (see
    ``_run_segment()``) for the caller to inspect/log."""
    _require_on_device("run_single_leg")
    _configure_and_start("run_single_leg")

    if _velocity_mode:
        _move(distance_mm, 0.0, 100.0)
        _save_state()
        print("demo_square: run_single_leg complete")
        return None

    segment = {
        "kind": "leg",
        "target_ticks": _leg_ticks(distance_mm, ticks_per_mm),
        "duty_left": SEGMENT_DUTY_PERCENT,
        "duty_right": SEGMENT_DUTY_PERCENT,
    }
    result = _run_segment(0, segment)
    print("demo_square: run_single_leg segment", result["kind"],
          "status", result["status"],
          "target_ticks", result["target_ticks"],
          "delta_left", result["delta_left"],
          "delta_right", result["delta_right"],
          "mean_delta", result["mean_delta"],
          "reached", result["reached"],
          "elapsed_ms", result["elapsed_ms"])

    diffdrive.neutral()
    _save_state()
    print("demo_square: run_single_leg complete")
    return result


# Standalone bench-debug entry point only -- see module docstring's
# "Auto-run" section. Production button A/B behaviour (src/main.py)
# calls run()/run_single_leg() explicitly and does not depend on this.
if __name__ == "__main__":
    run()
