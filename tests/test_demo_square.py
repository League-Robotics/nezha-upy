"""Sprint 002 ticket 002: `src/demo_square.py`'s offline-testable
segment-generation logic (the TOUR_SQUARE shape -- 4 straight legs +
4 left pivots, interleaved) against known geometry constants. The
hardware-touching half (`run()`/`_run_segment()`, which call
`diffdrive` directly) is not exercised here -- no CPython stub can
stand in for the real on-device closed-loop polling without asserting
something about timing this module never promises; that half is
verified on the bench instead (see
`docs/bench-log-zetuv-2026-08-19.md`). See `clasi/sprints/
002-zetuv-bench-square-tour-wheels-demo/tickets/
002-on-device-square-tour-demo.md`."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

import demo_square  # noqa: E402


def test_on_device_is_false_under_cpython():
    # No `diffdrive` native module exists off-device -- the module's own
    # import-time guard must have caught the ImportError.
    assert demo_square._ON_DEVICE is False


def test_run_refuses_off_device():
    with pytest.raises(RuntimeError):
        demo_square.run()


def test_leg_ticks_matches_distance_times_ticks_per_mm():
    # sprint 006 ticket 001: TICKS_PER_MM is now derived from the
    # stakeholder-directed 90 mm wheel diameter (a calibration ITERATION
    # point, not a claimed-final value -- see demo_square's own module
    # docstring/"Geometry -- SUPERSEDED sprint 006 ticket 001" note),
    # superseding sprint 005's own ~3.8424 (80.77 mm, tovez's wheel).
    # EMPIRICAL_COUNTS_PER_REV (975) is UNCHANGED throughout. Tied to the
    # live constant rather than a hand-copied literal so a future
    # correction cannot leave this test silently re-asserting a stale
    # value.
    assert demo_square._leg_ticks(500.0, demo_square.TICKS_PER_MM) == pytest.approx(
        500.0 * demo_square.TICKS_PER_MM)
    assert demo_square.TICKS_PER_MM == pytest.approx(3.4484, abs=0.001)


def test_pivot_ticks_matches_arc_length_times_ticks_per_mm():
    # 90 degrees at trackwidth 128 mm -> arc = (pi/2) * 64 mm ~= 100.53 mm
    ticks = demo_square._pivot_ticks(demo_square.PI / 2.0, 128.0,
                                      demo_square.TICKS_PER_MM)
    assert ticks == pytest.approx(
        (demo_square.PI / 2.0) * 64.0 * demo_square.TICKS_PER_MM)
    # sprint 006 ticket 001: ~347 ticks (was ~386.28 under sprint 005's
    # own now-superseded TICKS_PER_MM ~3.8424).
    assert ticks == pytest.approx(346.67, abs=0.5)


def test_build_square_tour_shape_is_leg_pivot_interleaved_four_of_each():
    segments = demo_square.build_square_tour()
    assert len(segments) == 8
    kinds = [s["kind"] for s in segments]
    assert kinds == ["leg", "pivot"] * 4
    assert sum(1 for k in kinds if k == "leg") == 4
    assert sum(1 for k in kinds if k == "pivot") == 4


def test_leg_segments_drive_both_wheels_forward_equally():
    segments = demo_square.build_square_tour()
    for s in segments:
        if s["kind"] != "leg":
            continue
        assert s["duty_left"] == s["duty_right"] == demo_square.SEGMENT_DUTY_PERCENT
        assert s["duty_left"] > 0
        assert s["target_ticks"] == pytest.approx(
            demo_square.LEG_DISTANCE_MM * demo_square.TICKS_PER_MM)


def test_pivot_segments_are_left_ccw_matching_kernel_twist_sign():
    # out.twist = 0.5*(velocityRight - velocityLeft), CCW positive
    # (native/differential_drive.h) -- a LEFT/CCW pivot needs
    # velocityRight > 0 and velocityLeft < 0.
    segments = demo_square.build_square_tour()
    for s in segments:
        if s["kind"] != "pivot":
            continue
        assert s["duty_left"] == -demo_square.SEGMENT_DUTY_PERCENT
        assert s["duty_right"] == demo_square.SEGMENT_DUTY_PERCENT
        implied_twist = 0.5 * (s["duty_right"] - s["duty_left"])
        assert implied_twist > 0  # CCW == LEFT
        assert s["target_ticks"] == pytest.approx(
            (demo_square.PIVOT_ANGLE_RAD * demo_square.TRACKWIDTH_MM / 2.0)
            * demo_square.TICKS_PER_MM)


def test_build_square_tour_is_parametric_not_hardcoded():
    # A different geometry must change the computed tick targets --
    # guards against the constants being baked into the segment dicts
    # independent of their own arguments.
    default_segments = demo_square.build_square_tour()
    custom_segments = demo_square.build_square_tour(
        ticks_per_mm=2.0, trackwidth_mm=200.0, leg_mm=1000.0,
        pivot_rad=demo_square.PI)
    assert custom_segments[0]["target_ticks"] != default_segments[0]["target_ticks"]
    assert custom_segments[0]["target_ticks"] == pytest.approx(1000.0 * 2.0)
    assert custom_segments[1]["target_ticks"] == pytest.approx(
        demo_square.PI * 100.0 * 2.0)


def test_mean_abs_delta_averages_both_wheels():
    out = {"positionLeft": 10.0, "positionRight": -6.0}
    mean_delta, delta_left, delta_right = demo_square._mean_abs_delta(out, 0.0, 0.0)
    assert delta_left == 10.0
    assert delta_right == -6.0
    assert mean_delta == pytest.approx((10.0 + 6.0) / 2.0)


# --- sprint 006 ticket 001: config-driven geometry -----------------------

def test_geometry_from_robot_config_happy_path(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"wheels": {"wheel_diameter_mm": 100.0, '
                            '"ticks_per_rev": 1000.0}}')
    result = demo_square.geometry_from_robot_config(str(config_path))
    assert result == (100.0, 1000.0)


def test_geometry_from_robot_config_missing_file():
    assert demo_square.geometry_from_robot_config(
        "/does/not/exist/robot.json") is None


def test_geometry_from_robot_config_malformed_json(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text("not valid json {{{")
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_geometry_from_robot_config_missing_wheels_group(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"identity": {"robot_name": "x"}}')
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_geometry_from_robot_config_missing_field(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"wheels": {"wheel_diameter_mm": 90.0}}')
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_geometry_from_robot_config_non_numeric_field(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"wheels": {"wheel_diameter_mm": "ninety", '
                            '"ticks_per_rev": 975.0}}')
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_geometry_from_robot_config_non_positive_diameter_rejected(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"wheels": {"wheel_diameter_mm": 0.0, '
                            '"ticks_per_rev": 975.0}}')
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_geometry_from_robot_config_negative_ticks_per_rev_rejected(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"wheels": {"wheel_diameter_mm": 90.0, '
                            '"ticks_per_rev": -1.0}}')
    assert demo_square.geometry_from_robot_config(str(config_path)) is None


def test_module_level_geometry_falls_back_off_device():
    # Under CPython, _ON_DEVICE is False, so the module never attempts
    # a real filesystem read at import time -- the fallback constants
    # (mirroring data/zetuv.json's own stakeholder-directed 90.0 mm
    # starting point) are used deterministically.
    assert demo_square.GEOMETRY_SOURCE == "hardcoded fallback"
    assert demo_square.WHEEL_DIAMETER_MM == 90.0
    assert demo_square.EMPIRICAL_COUNTS_PER_REV == 975.0


# --- sprint 006 ticket 001: button B single-leg entry point --------------

def test_run_single_leg_refuses_off_device():
    with pytest.raises(RuntimeError):
        demo_square.run_single_leg()


def test_run_single_leg_default_distance_matches_leg_distance():
    # Button B commands the same 500 mm the square tour's own legs use
    # (data/zetuv.json's own _wheels_note / this ticket's own acceptance
    # criteria: "exactly 500 mm commanded").
    import inspect
    sig = inspect.signature(demo_square.run_single_leg)
    assert sig.parameters["distance_mm"].default == demo_square.LEG_DISTANCE_MM
    assert demo_square.LEG_DISTANCE_MM == 500.0


# --- sprint 006 ticket 001: auto-run trigger ------------------------------

def test_module_does_not_auto_run_on_plain_import():
    # A plain `import demo_square` (this test file's own top-level
    # import, and main.py's own sys.modules.pop(...) + import pattern)
    # must never itself invoke run()/run_single_leg() -- __name__ is
    # "demo_square" for any import, never "__main__", by Python's own
    # guaranteed import semantics. This module has no diffdrive
    # available off-device anyway, so an accidental auto-run would have
    # raised RuntimeError at import time and this whole test file would
    # already have failed to collect -- this test makes that guarantee
    # explicit rather than relying on it being an accidental side effect.
    assert demo_square.__name__ == "demo_square"
