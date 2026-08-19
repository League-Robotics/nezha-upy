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

**Geometry -- SUPERSEDED sprint 005 ticket 001, 2026-08-19**
(stakeholder correction, live at the bench, ``clasi/sprints/
005-zetuv-wheel-diameter-rescale/``, UC-003/UC-014): the sprint 004
fix above got ``EMPIRICAL_COUNTS_PER_REV`` (975, ticks per WHEEL
REVOLUTION) right -- that number is UNCHANGED and PRESERVED below --
but it divided by the wrong wheel CIRCUMFERENCE. Sprint 004's
``WHEEL_CIRCUMFERENCE_MM = 145.0`` was itself the issue's own *stated*
figure, never independently camera/tape-measured. The stakeholder has
now directly confirmed (2026-08-19): "Tovez does in fact have the
correct wheel diameter... You need to set the wheel size for this
Micro:bit to be the same as Tovez's." ``data/tovez.json``'s own
``wheels.wheel_diameter_mm = 80.77`` (circumference = pi * 80.77 =
253.7464 mm) is therefore the corrected, config-derived source for
this constant -- NOT a re-guess, a stakeholder-blessed value carried
from the sibling robot that shares this same physical wheel.

**Net effect of the 145 mm assumption alone**: sprint 004's legs were
right in REVOLUTIONS (~2 rev was always the intent for a 500 mm leg)
but wrong in MM, because the wrong circumference converted that
revolution count to the wrong distance. Sprint 004's own leg target
(3362.069 ticks) is 3362.069 / 975.0 = 3.448 wheel revolutions -- at
the NOW-corrected 253.7464 mm circumference that is
3.448 * 253.7464 = 874.9 mm of real travel, 1.75x the 500 mm the
stakeholder actually intended.

**Fix**: ``WHEEL_DIAMETER_MM = 80.77`` (mirrors ``data/zetuv.json``'s
own corrected ``wheels.wheel_diameter_mm``, provenance:
stakeholder-confirmed 2026-08-19, same wheels as tovez),
``WHEEL_CIRCUMFERENCE_MM = PI * WHEEL_DIAMETER_MM`` ~= 253.7464 mm
(now DERIVED rather than a separately-stated magic number),
``EMPIRICAL_COUNTS_PER_REV = 975.0`` UNCHANGED, giving
``TICKS_PER_MM = 975.0 / 253.7464`` ~= 3.8424 (was ~6.7241) -- a
~0.5715x correction (3.8424 / 6.7241), the inverse of sprint 004's own
~4.74x correction, since this ticket corrects the SAME arithmetic's
other input in the opposite direction. 500 mm legs now target
``500.0 * 3.8424`` ~= 1921 ticks (was 3362.069) -- ~1.97 wheel
revolutions, matching the stakeholder's own intended ~2-revolution,
~500 mm leg. Pivot targets fall out of the SAME ``TICKS_PER_MM``
correction applied through the unchanged ``TRACKWIDTH_MM = 128.0``
geometry (``_pivot_ticks()`` below is untouched code, just fed the new
constant) -- a 90-degree pivot's arc length stays
``(pi/2) * 64.0`` ~= 100.53 mm (the same physical arc sprint 004 also
used), so the new pivot target is ``100.53 * 3.8424`` ~= 386 ticks
(was 675.984). ``TRACKWIDTH_MM`` remains untouched -- it was never
part of either the sprint 004 or this ticket's bug (caliper-measured,
independent of wheel diameter).

Still NOT independently camera/tape-verified on zetuv's own physical
wheel beyond the stakeholder's own verbal bench confirmation that it
matches tovez's -- disclosed, not hidden, same caveat this file has
carried through every prior correction. Segment lease/timeout
constants (``SEGMENT_LEASE_MS``/``SEGMENT_TIMEOUT_MS``/
``LEASE_REFRESH_MS``) are UNCHANGED -- the sprint 004 lease-refresh
mechanism itself is out of this ticket's scope, and the shorter
~1921-tick leg targets only need LESS time than the ~3362-tick targets
those budgets were already sized for, so the existing margin only
grows (see the constants' own updated comments below for the
recomputed expected timing).

**Geometry -- SUPERSEDED sprint 006 ticket 001, 2026-08-19** (stakeholder
directive, live at the bench, ``clasi/sprints/
006-zetuv-90mm-wheels-and-button-b-50cm-drive/``, UC-003/UC-014):
"set up its wheels to be 90 mm" -- an explicit calibration ITERATION
POINT, not a claim that 90 mm is more correct than sprint 005's own
stakeholder-confirmed 80.77 mm; the stakeholder is dialing this in by
direct measurement and expects to revise it again. ``WHEEL_DIAMETER_MM
= 90.0`` (fallback default; see "Config-driven geometry" below for the
now-live override path), ``EMPIRICAL_COUNTS_PER_REV = 975.0``
UNCHANGED (sprint 004's own bench-proven counts/wheel-revolution
anchor -- only the diameter input changed this ticket),
``TICKS_PER_MM = 975.0 / (pi * 90.0)`` ~= 3.4484 (was ~3.8424). A 500
mm leg (this ticket's own button-B distance, see below) now targets
``500.0 * 3.4484`` ~= 1724 ticks (~1.77 wheel revolutions); pivot arcs
keep the SAME ~100.53 mm physical arc (``TRACKWIDTH_MM = 128.0``,
caliper-measured, untouched by any wheel-diameter correction) ->
``100.53 * 3.4484`` ~= 347 ticks (was ~386). Mirrors
``data/zetuv.json``'s own ``wheels`` block (same derivation, same
provenance note, same calibration-formula instruction for future
iterations: ``new_diameter_mm = 90 x (measured_travel_mm / 500)``).

**Config-driven geometry -- new this ticket, why NOT
``config.load_robot_config()``** (grounded in this file's own bench
history, ``docs/bench-log-zetuv-2026-08-19.md``, not assumed): the
ticket's own acceptance criteria explicitly offer two paths --
``config.load_robot_config()`` OR "an equivalent lightweight parse".
This module uses the LATTER, for two independent, concrete,
bench-established reasons, either of which alone would already be
disqualifying:

  1. Sprint 003's own bench pass (``docs/bench-log-zetuv-2026-08-19.md``
     Sec 17) found zetuv's resident FROZEN ``config`` module is a STALE
     STUB on the currently-deployed firmware image -- ``dir(config)``
     is only ``['__class__', '__name__']``; ``config.load_robot_config``
     does not exist as an attribute at all (``AttributeError``). No
     rebuild/reflash happened in any session since (sprints 004/005 both
     explicitly note "no source files changed" / filesystem-copy-only
     deploys) -- this remains true as of this ticket, unverified fresh
     this session only because zetuv was not physically connected to
     the bench at all (see the bench log's own sprint 006 section) --
     `import config; config.load_robot_config` would raise
     ``AttributeError`` on THIS resident image regardless.
  2. EVEN ON A REBUILT, CURRENT ``config`` module, ``load_robot_config()``
     would still be structurally unusable for zetuv's own
     ``data/zetuv.json``/``robot.json``: ``config.REQUIRED_KEYS`` demands
     ``motors.travel_calib_left``/``travel_calib_right`` and all 15
     ``wheel_control`` fields as a whole-document fail-CLOSED
     precondition (``config.parse_robot_config()`` raises
     ``ConfigError`` if ANY required key anywhere in the document is
     missing) -- and zetuv's own config deliberately omits
     ``travel_calib_left``/``right`` (sprint 002's own no-calibration
     scope decision, unchanged and out of THIS ticket's scope to
     revisit). So gating a read of the ``wheels`` group's two geometry
     fields behind ``load_robot_config()``'s full required-key gate
     would make that read ALWAYS fail on zetuv's own config, defeating
     this ticket's own stated goal ("each future calibration iteration
     = re-copy robot.json ONLY") before it could ever help.

Given both, this module implements a narrow, dedicated
``geometry_from_robot_config()`` below: reads ONLY
``wheels.wheel_diameter_mm``/``wheels.ticks_per_rev`` from the robot
config JSON, fail-SOFT (returns ``None`` on ANY problem -- missing
file, invalid JSON, missing group/field, non-numeric, non-positive --
NEVER raises). This is a deliberately different contract from
``config.ConfigError``'s fail-CLOSED posture: a wrong/missing geometry
constant should fall back to a safe hardcoded default and keep the
demo working (this module's own long-established "never brick the
demo" posture, e.g. ``run()``'s own off-device ``RuntimeError`` aside),
not refuse motion outright the way a missing safety-relevant
``wheel_control``/``travel_calib`` key correctly does in ``config.py``.
The read happens at every fresh (re-)import of this module -- which,
per ``main.py``'s own ``sys.modules.pop(...) + import demo_square``
per-press pattern (unchanged this ticket), means EVERY button press (A
or B alike) re-reads ``/robot.json`` fresh. This is a STRONGER
guarantee than a literal one-time "at boot" read: a stakeholder can
re-copy a freshly edited ``robot.json`` onto the device and see the new
geometry take effect on the VERY NEXT press, with no reset/redeploy
needed -- directly satisfying this ticket's own "re-copy robot.json
ONLY" iteration goal. ``TRACKWIDTH_MM`` remains a plain hardcoded
constant (caliper-measured, not named in this ticket's scope) -- only
``wheel_diameter_mm``/``ticks_per_rev`` are config-driven this ticket.

**Single-leg entry point (button B) -- reuses, does not reimplement**:
``run_single_leg()`` below is the "straight-drive primitive"
``main.py``'s own new button-B handler (this ticket, sprint 006 ticket
001) reuses (per this ticket's explicit instruction not to reimplement
straight-line driving). It
shares the SAME ``_configure_and_start()``/``_leg_ticks()``/
``_run_segment()`` pieces ``run()``'s own square tour already uses for
every leg -- the only new code is the thin wrapper that builds ONE leg
segment and drives it, mirroring ``run()``'s own leg-segment shape
exactly (same duty, same lease-refresh discipline, same
encoder-termination convention).

**Auto-run trigger changed from ``_ON_DEVICE`` to a ``__name__`` guard
-- why, disclosed plainly**: prior to this ticket, this module's ONLY
callable behaviour was the full square tour, so "importing this module
runs the one thing it does" (``if _ON_DEVICE: run()``, unconditional)
was a reasonable, minimal design. This ticket adds a SECOND, distinct
behaviour (``run_single_leg()``) that must be selectable per press --
but MicroPython's ``import`` statement takes no arguments, so an
unconditional "import always runs the (now ambiguous) one thing" no
longer has a well-defined meaning. Rather than invent an out-of-band
signalling mechanism (e.g. stashing a flag on a shared module) this
ticket instead makes the two production entry points EXPLICIT:
``main.py``'s ``run_tour()``/``run_straight_drive()`` both call
``demo_square.run()``/``demo_square.run_single_leg(...)`` directly
after their own ``sys.modules.pop(...) + import demo_square`` (see
``src/main_zetuv_demo.py``) -- production behaviour therefore no longer
depends AT ALL on what a bare ``import demo_square`` does by itself.
The bottom of this file keeps a convenience auto-run for the
STANDALONE bench-debug entry point this project has used throughout
(``mpremote connect PORT run src/demo_square.py``, documented at the
top of this docstring) -- but now gated on ``__name__ == "__main__"``
rather than ``_ON_DEVICE`` alone, since Python's own `import` statement
GUARANTEES ``__name__`` is set to the module's own dotted name
(``"demo_square"``) for every ``import`` call, on any Python
implementation -- so this guard is PROVABLY never true for
``main.py``'s own import-based invocations, with no port-specific
assumption needed there. The one genuinely NEW assumption this
introduces is whether ``mpremote ... run <file>.py`` executes with
``__name__ == "__main__"`` -- reasoned, not yet independently
bench-verified THIS ticket (zetuv was not physically connected to the
bench for the whole of this session; see the bench log's own sprint
006 section), from EXISTING bench evidence: ``main.py``'s own REPL
verification scripts (``docs/bench-log-zetuv-2026-08-19.md``, sprint
003 Sec 21 onward) had to explicitly override ``__name__`` to
``"verify"`` specifically BECAUSE the REPL's own default execution
namespace already has ``__name__ == "__main__"`` -- and ``mpremote
... run`` sends a file's source to be executed through that SAME raw-REPL
mechanism, not a distinct one. If this reasoning turns out wrong, the
ONLY failure mode is the STANDALONE bench-debug convenience silently
doing nothing (non-destructive, easily diagnosed with a one-line
``print(__name__)`` probe, the same technique already used to verify
``main.py``'s own ``__name__`` semantics) -- button A/B production
behaviour is unaffected either way, since both call their target
function explicitly. Flagged here for whoever next has bench access to
zetuv to confirm directly.

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

# No JSON parser import: this build's firmware ships NEITHER ujson NOR
# json (bench-confirmed 2026-08-19, help('modules') on zetuv -- the
# frozen config module's own ujson import can never have worked on this
# image). The geometry read below is a dependency-free two-key scan of
# the compact deployed /robot.json instead.

# ---------------------------------------------------------------------
# Geometry -- SUPERSEDED sprint 006 ticket 001, 2026-08-19 (stakeholder
# directive: "set up its wheels to be 90 mm" -- an explicit calibration
# iteration point). See module docstring's "Geometry" and "Config-driven
# geometry" sections for the full derivation/rationale. Mirrors
# data/zetuv.json's own wheels block (kept in sync, same derivation/
# provenance note there).
# ---------------------------------------------------------------------
PI = 3.14159265358979323846

ROBOT_CONFIG_PATH = "robot.json"   # bare, no leading slash -- mirrors
                                    # main.py's own bench-confirmed "Path
                                    # convention" (leading-slash ENOENTs
                                    # on this port even though the same
                                    # file opens fine under the bare form)


def _scan_number(text, key):
    """Return the numeric value following ``"key":`` in ``text``, or
    ``None`` if the key is absent or its value does not parse as a
    float. Whitespace after the colon is tolerated; the value ends at
    the first ``,``, ``}``, or ``]``."""
    i = text.find('"' + key + '"')
    if i < 0:
        return None
    i = text.find(":", i)
    if i < 0:
        return None
    j = i + 1
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    k = j
    while k < len(text) and text[k] not in ",}]":
        k += 1
    try:
        return float(text[j:k])
    except ValueError:
        return None


def geometry_from_robot_config(path=ROBOT_CONFIG_PATH):
    """Sprint 006 ticket 001: narrow, fail-SOFT read of ONLY
    ``wheels.wheel_diameter_mm``/``wheels.ticks_per_rev`` from the robot
    config JSON at ``path`` -- see module docstring's "Config-driven
    geometry" section for why this is a dedicated lightweight parse
    rather than ``config.load_robot_config()`` (two independent,
    bench-grounded, concrete reasons stated there). Returns
    ``(wheel_diameter_mm, ticks_per_rev)`` as floats on success;
    ``None`` on ANY problem -- missing/unreadable file, either key not
    found, non-numeric value, or non-positive. NEVER raises; the caller
    falls back to the hardcoded constants below.

    Implementation is a dependency-free string scan, not a JSON parse:
    this image ships no json/ujson module (bench-confirmed), and both
    keys appear exactly once in the deployed compact config (their only
    JSON home is the wheels group)."""
    try:
        with open(path, "r") as f:
            text = f.read()
        wheel_diameter_mm = _scan_number(text, "wheel_diameter_mm")
        ticks_per_rev = _scan_number(text, "ticks_per_rev")
    except OSError:
        return None
    if wheel_diameter_mm is None or ticks_per_rev is None:
        return None
    if wheel_diameter_mm <= 0.0 or ticks_per_rev <= 0.0:
        return None
    return wheel_diameter_mm, ticks_per_rev


# Config-driven, with a hardcoded fallback -- see module docstring's
# "Config-driven geometry" section. Only attempted on-device: under
# CPython (offline tests) there is no real /robot.json to read and no
# reason to depend on the test runner's own cwd, so the fallback
# constants are used directly, deterministically, every time.
_CONFIG_GEOMETRY = geometry_from_robot_config() if _ON_DEVICE else None
GEOMETRY_SOURCE = "robot.json" if _CONFIG_GEOMETRY is not None else "hardcoded fallback"

if _CONFIG_GEOMETRY is not None:
    WHEEL_DIAMETER_MM, EMPIRICAL_COUNTS_PER_REV = _CONFIG_GEOMETRY
else:
    WHEEL_DIAMETER_MM = 90.0            # [mm] fallback -- mirrors
                                        # data/zetuv.json's own
                                        # wheels.wheel_diameter_mm
                                        # (stakeholder-directed
                                        # calibration starting point,
                                        # 2026-08-19 -- an explicit
                                        # iteration point, not a claimed
                                        # final value)
    EMPIRICAL_COUNTS_PER_REV = 975.0   # [counts/rev] fallback --
                                        # UNCHANGED empirical bench
                                        # anchor (sprint 004), mirrors
                                        # data/zetuv.json

WHEEL_CIRCUMFERENCE_MM = PI * WHEEL_DIAMETER_MM  # ~282.7433 mm at the
                                    # fallback 90.0 mm diameter -- DERIVED,
                                    # not a separately-stated magic number
TICKS_PER_MM = EMPIRICAL_COUNTS_PER_REV / WHEEL_CIRCUMFERENCE_MM  # ~3.4484
                                    # at the fallback values (was ~3.8424
                                    # under the old 80.77 mm diameter)
TRACKWIDTH_MM = 128.0               # [mm] UNCHANGED -- caliper-measured,
                                    # NOT config-driven this ticket (only
                                    # wheel_diameter_mm/ticks_per_rev are)

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
                               # leg targets. UNCHANGED sprint 005 ticket
                               # 001: the mechanism itself is out of this
                               # ticket's scope, and the now-corrected
                               # ~1921-tick leg target (was ~3362) needs
                               # only ~2.4-2.8 s of continuous drive at
                               # SEGMENT_DUTY_PERCENT (scaled from sprint
                               # 004's own ~4.2-4.9 s bench measurement by
                               # the same ~0.5715x TICKS_PER_MM ratio,
                               # 3.8424/6.7241) -- well clear of the native
                               # binding's hard 5000 ms single-lease ceiling
                               # (refused outright above it, never clamped)
                               # even without refreshing, so this mechanism
                               # keeps working with growing margin, not
                               # tighter margin. A short, frequently-renewed
                               # lease reaches the same total drive duration
                               # while keeping the lease's own fail-safe
                               # intent tight (a polling loop that itself
                               # hangs still loses the wheels within one
                               # lease period, not within whatever the
                               # segment's full budget is).
LEASE_REFRESH_MS = 400        # reissue driveDuty() this often while still
                               # driving -- comfortably inside
                               # SEGMENT_LEASE_MS so the lease never
                               # actually expires mid-drive under normal
                               # poll timing
SEGMENT_TIMEOUT_MS = 6000     # CORRECTED sprint 004 ticket 001: overall
                               # per-segment safety bound, decoupled from
                               # the native binding's 5000 ms single-lease
                               # ceiling now that driveDuty() is reissued
                               # (see SEGMENT_LEASE_MS above). UNCHANGED
                               # sprint 005 ticket 001: the ~1921-tick leg
                               # target (was ~3362) now needs only
                               # ~2.4-2.8 s typical completion time (see
                               # SEGMENT_LEASE_MS's own comment for the
                               # scaling), so this bound's margin only
                               # grows; pivots finish in well under 1 s and
                               # exit this bound long before it matters.
                               # UNCHANGED sprint 006 ticket 001: the
                               # 90 mm-diameter leg target (~1724 ticks,
                               # was ~1921) is smaller still (~0.90x) --
                               # margin only grows again, no adjustment
                               # needed.
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


def _require_on_device(caller_name):
    if not _ON_DEVICE:
        raise RuntimeError(
            "demo_square.%s() requires the diffdrive native module "
            "(run this on zetuv via mpremote, not under CPython)" % (caller_name,))


def _configure_and_start(caller_name):
    """Shared ``diffdrive.configure()``/``begin()``/``start()``
    bracketing -- ``run()`` (button A, full tour) and ``run_single_leg()``
    (button B, sprint 006 ticket 001) both call this identically, so the
    wiring facts (ports/signs/duty rail) can never drift between the two
    entry points. Bypasses config.py/boot.py -- see module docstring for
    why."""
    cfg = diffdrive.configure(
        left_port=LEFT_PORT, right_port=RIGHT_PORT,
        fwd_sign_left=FWD_SIGN_LEFT, fwd_sign_right=FWD_SIGN_RIGHT,
        max_duty=MAX_DUTY_PERCENT, full_duty_velocity=0.0,
        cycle_period_ms=CYCLE_PERIOD_MS)
    print("demo_square: %s configure" % (caller_name,), cfg)
    print("demo_square: %s begin" % (caller_name,), diffdrive.begin())
    print("demo_square: %s start" % (caller_name,), diffdrive.start())
    time.sleep_ms(100)


def run():
    """The square tour entry point (button A). Configures diffdrive
    directly, then drives the 8-segment square tour, printing
    per-segment encoder evidence as it goes."""
    _require_on_device("run")
    _configure_and_start("run")

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


def run_single_leg(distance_mm=LEG_DISTANCE_MM, ticks_per_mm=TICKS_PER_MM):
    """Sprint 006 ticket 001: button B's straight-drive entry point --
    drives ONE leg segment of ``distance_mm`` (default 500 mm, the
    ticket's own commanded distance) via the SAME
    ``_configure_and_start()``/``_leg_ticks()``/``_run_segment()``
    pieces ``run()``'s own square-tour legs already use -- reused, not
    reimplemented (see module docstring's "Single-leg entry point"
    section). Same duty, same encoder-termination convention, same
    lease-refresh discipline (``_run_segment()`` itself, unchanged).
    Returns the single segment's result dict (see ``_run_segment()``)
    for the caller to inspect/log."""
    _require_on_device("run_single_leg")
    _configure_and_start("run_single_leg")

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
    print("demo_square: run_single_leg complete")
    return result


# ---------------------------------------------------------------------
# Standalone bench-debug entry point ONLY -- see module docstring's
# "Auto-run trigger changed from _ON_DEVICE to a __name__ guard" section
# for why this changed this ticket, and for the one new, disclosed,
# not-yet-bench-verified assumption it carries (mpremote's own `run`
# execution context). Production button A/B behaviour (src/
# main_zetuv_demo.py) calls run()/run_single_leg() explicitly and does
# NOT depend on this guard at all.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    run()
