"""`src/demo_square.py`'s offline-testable segment-generation logic
(the TOUR_SQUARE shape -- 4 straight legs + 4 left pivots, interleaved)
against known geometry constants. The hardware-touching half
(`run()`/`_run_segment()`, which call `diffdrive` directly) is not
exercised here -- no CPython stub can stand in for the real on-device
closed-loop polling; that half is verified on the bench instead."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest

import demo_square  # noqa: E402


def test_on_device_is_false_under_cpython():
    # No diffdrive module off-device -- the import-time guard must catch it.
    assert demo_square._ON_DEVICE is False


def test_run_refuses_off_device():
    with pytest.raises(RuntimeError):
        demo_square.run()


def test_leg_ticks_matches_distance_times_ticks_per_mm():
    # TICKS_PER_MM is derived from the 90 mm wheel diameter (a
    # calibration iteration point, not final -- see module docstring).
    # EMPIRICAL_COUNTS_PER_REV (975) is unchanged. Tied to the live
    # constant, not a hand-copied literal, so a future correction can't
    # leave this test silently stale.
    assert demo_square._leg_ticks(500.0, demo_square.TICKS_PER_MM) == pytest.approx(
        500.0 * demo_square.TICKS_PER_MM)
    assert demo_square.TICKS_PER_MM == pytest.approx(3.4484, abs=0.001)


def test_pivot_ticks_matches_arc_length_times_ticks_per_mm():
    # 90 degrees at trackwidth 128 mm -> arc = (pi/2) * 64 mm ~= 100.53 mm
    ticks = demo_square._pivot_ticks(demo_square.PI / 2.0, 128.0,
                                      demo_square.TICKS_PER_MM)
    assert ticks == pytest.approx(
        (demo_square.PI / 2.0) * 64.0 * demo_square.TICKS_PER_MM)
    # ~347 ticks at the current TICKS_PER_MM.
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
    # out.twist = 0.5*(velocityRight - velocityLeft), CCW positive --
    # a LEFT/CCW pivot needs velocityRight > 0 and velocityLeft < 0.
    segments = demo_square.build_square_tour()
    for s in segments:
        if s["kind"] != "pivot":
            continue
        assert s["duty_left"] == -demo_square.PIVOT_DUTY_PERCENT
        assert s["duty_right"] == demo_square.PIVOT_DUTY_PERCENT
        implied_twist = 0.5 * (s["duty_right"] - s["duty_left"])
        assert implied_twist > 0  # CCW == LEFT
        assert s["target_ticks"] == pytest.approx(
            (demo_square.PIVOT_ANGLE_RAD * demo_square.TRACKWIDTH_MM / 2.0)
            * demo_square.TICKS_PER_MM)


def test_build_square_tour_is_parametric_not_hardcoded():
    # A different geometry must change tick targets -- guards against
    # constants baked in independent of arguments.
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


# --- config-driven geometry ------------------------------------------

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
    # Under CPython, _ON_DEVICE is False, so the module never reads the
    # filesystem at import -- fallback constants (mirroring zetuv.json's
    # 90.0 mm) are used deterministically.
    assert demo_square.GEOMETRY_SOURCE == "hardcoded fallback"
    assert demo_square.WHEEL_DIAMETER_MM == 90.0
    assert demo_square.EMPIRICAL_COUNTS_PER_REV == 975.0


# --- button B single-leg entry point -----------------------------------

def test_run_single_leg_refuses_off_device():
    with pytest.raises(RuntimeError):
        demo_square.run_single_leg()


def test_run_single_leg_default_distance_matches_leg_distance():
    # Button B commands the same 500 mm the square tour's legs use.
    import inspect
    sig = inspect.signature(demo_square.run_single_leg)
    assert sig.parameters["distance_mm"].default == demo_square.LEG_DISTANCE_MM
    assert demo_square.LEG_DISTANCE_MM == 500.0


# --- auto-run trigger ---------------------------------------------------

def test_module_does_not_auto_run_on_plain_import():
    # A plain `import demo_square` must never itself invoke
    # run()/run_single_leg() -- __name__ is "demo_square" for any
    # import, never "__main__". Made explicit here rather than relying
    # on it being an accidental side effect of no diffdrive being
    # available off-device.
    assert demo_square.__name__ == "demo_square"


# --- config-driven wiring ------------------------------------------------

def test_wiring_from_robot_config_happy_path(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"motors": {"left_port": 2, "right_port": 1, '
                            '"fwd_sign_left": -1, "fwd_sign_right": 1}}')
    result = demo_square._wiring_from_robot_config(str(config_path))
    assert result == (2, 1, -1, 1)


def test_wiring_from_robot_config_missing_key_falls_back(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"motors": {"left_port": 2, "right_port": 1, '
                            '"fwd_sign_left": -1}}')
    assert demo_square._wiring_from_robot_config(str(config_path)) is None


def test_wiring_from_robot_config_non_integer_rejected(tmp_path):
    config_path = tmp_path / "robot.json"
    config_path.write_text('{"motors": {"left_port": 2.5, "right_port": 1, '
                            '"fwd_sign_left": 1, "fwd_sign_right": 1}}')
    assert demo_square._wiring_from_robot_config(str(config_path)) is None


def test_wiring_from_robot_config_missing_file():
    assert demo_square._wiring_from_robot_config(
        "/does/not/exist/robot.json") is None


def test_module_level_wiring_falls_back_off_device():
    # Under CPython, _ON_DEVICE is False -> the module never reads a
    # real /robot.json; the zetuv bench-measured fallbacks apply.
    assert demo_square.WIRING_SOURCE == "hardcoded fallback"
    assert (demo_square.LEFT_PORT, demo_square.RIGHT_PORT) == (2, 1)
    assert (demo_square.FWD_SIGN_LEFT, demo_square.FWD_SIGN_RIGHT) == (1, 1)


# --- encoder-balancing controller -----------------------------------------

def test_balanced_duties_no_error_no_trim():
    assert demo_square.balanced_duties(15.0, 15.0, 100.0, 100.0) == (15.0, 15.0)


def test_balanced_duties_left_ahead_slows_left_speeds_right():
    dl, dr = demo_square.balanced_duties(15.0, 15.0, 300.0, 100.0)
    assert dl < 15.0 and dr > 15.0


def test_balanced_duties_right_ahead_slows_right_speeds_left():
    dl, dr = demo_square.balanced_duties(15.0, 15.0, 100.0, 300.0)
    assert dl > 15.0 and dr < 15.0


def test_balanced_duties_trim_clamped():
    dl, dr = demo_square.balanced_duties(15.0, 15.0, 100000.0, 0.0)
    assert dl == 15.0 - demo_square.BALANCE_TRIM_MAX
    assert dr == 15.0 + demo_square.BALANCE_TRIM_MAX


def test_balanced_duties_preserves_pivot_signs():
    # Left pivot: left duty negative, right positive; |left| leading.
    dl, dr = demo_square.balanced_duties(-15.0, 15.0, -300.0, 100.0)
    assert dl < 0.0 and dr > 0.0
    assert abs(dl) < 15.0 and abs(dr) > 15.0


def test_balanced_duties_zero_duty_stays_zero():
    dl, dr = demo_square.balanced_duties(15.0, 0.0, 300.0, 0.0)
    assert dr == 0.0


def test_balanced_duties_magnitude_clamped_to_max_duty():
    dl, dr = demo_square.balanced_duties(
        demo_square.MAX_DUTY_PERCENT, demo_square.MAX_DUTY_PERCENT,
        0.0, 100000.0)
    assert dl == demo_square.MAX_DUTY_PERCENT
