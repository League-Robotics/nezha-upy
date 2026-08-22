"""M5 gate / sprint 007 ticket 006: `src/core/config.py`'s fail-closed
key validation and the `wheel_control` -> `DiffDrive::Config` mapping
(travel_calib x10).

  - fail-closed key validation against data/tovez.json, data/gopiv.json,
    and a deliberately-malformed fixture (refusal asserted);
  - wheel_control -> DiffDrive::Config mapping (travel_calib x10)
    against known input/output pairs;
  - the name-keyed get_field()/set_field() accessors v6's GET/SET verbs
    delegate to (sprint 007 ticket 005) -- v5's own binary
    CONFIG/SET_FIELD/GET_CONFIG dispatch retired with the v6 cutover
    (ticket 006) and is no longer tested here.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
DATA_DIR = REPO_ROOT / "data"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import config  # noqa: E402  (path must be set up first)


# --- fail-closed key validation ----------------------------------------

def test_tovez_loads_fail_closed_ok():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    assert robot_config["identity"]["robot_name"] == "tovez"


def test_gopiv_loads_fail_closed_ok():
    robot_config = config.load_robot_config(str(DATA_DIR / "gopiv.json"))
    assert robot_config["identity"]["robot_name"] == "gopiv"


def test_malformed_fixture_is_refused():
    with pytest.raises(config.ConfigError):
        config.load_robot_config(str(FIXTURES_DIR / "robot_config_malformed.json"))


def test_missing_file_is_refused():
    with pytest.raises(config.ConfigError):
        config.load_robot_config(str(DATA_DIR / "does_not_exist.json"))


def test_non_numeric_required_key_is_refused():
    text = (
        '{"identity": {"robot_name": "x"}, "connection": {"radio_channel": "not-a-number"}, '
        '"motors": {"left_port": 2, "right_port": 1, "fwd_sign_left": 1, '
        '"fwd_sign_right": -1, "travel_calib_left": 0.7, "travel_calib_right": 0.7}, '
        '"wheel_control": {"v_min": 0, "bias_max": 0, "tau_adapt": 0, "a_steady": 0, '
        '"deficit_threshold": 0, "deficit_window": 0, "pid_kp": 0, "pid_ki": 0, '
        '"pid_i_max": 0, "pid_kaff": 0, "pid_max": 0, "pos_err_max": 0, "stall_speed": 0, '
        '"stall_demand": 0, "stall_window": 0}}'
    )
    with pytest.raises(config.ConfigError):
        config.parse_robot_config(text)


def test_bool_is_not_accepted_as_numeric():
    # JSON true/false decode to Python bool, a subclass of int --
    # explicitly rejected.
    text = (
        '{"identity": {"robot_name": "x"}, "connection": {"radio_channel": true}, '
        '"motors": {"left_port": 2, "right_port": 1, "fwd_sign_left": 1, '
        '"fwd_sign_right": -1, "travel_calib_left": 0.7, "travel_calib_right": 0.7}, '
        '"wheel_control": {"v_min": 0, "bias_max": 0, "tau_adapt": 0, "a_steady": 0, '
        '"deficit_threshold": 0, "deficit_window": 0, "pid_kp": 0, "pid_ki": 0, '
        '"pid_i_max": 0, "pid_kaff": 0, "pid_max": 0, "pos_err_max": 0, "stall_speed": 0, '
        '"stall_demand": 0, "stall_window": 0}}'
    )
    with pytest.raises(config.ConfigError):
        config.parse_robot_config(text)


# --- wheel_control -> DiffDrive::Config mapping (travel_calib x10) -----

def test_tovez_wheel_control_mapping_known_pairs():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    mapped = config.wheel_control_to_diffdrive_config(robot_config)

    # Direct 1:1 renamed fields -- known pairs from data/tovez.json's
    # wheel_control group.
    assert mapped["vMin"] == 20.0
    assert mapped["biasMax"] == 23.8
    assert mapped["tauAdapt"] == 30.0
    assert mapped["aSteady"] == 30.0
    assert mapped["deficitThreshold"] == 0.0
    assert mapped["deficitWindow"] == 0.0
    assert mapped["kp"] == 0.0
    assert mapped["ki"] == 6.0
    assert mapped["iMax"] == 60.0
    assert mapped["kaff"] == 0.0
    assert mapped["pidMax"] == 100.0
    assert mapped["posErrMax"] == 10.0
    assert mapped["stallSpeed"] == 15.0
    assert mapped["stallDemand"] == 40.0
    assert mapped["stallWindow"] == 500.0

    # travel_calib x10: tovez's travel_calib_left/right are both 0.7837.
    assert mapped["fullDutyVelocity"] == pytest.approx(
        0.7837 * config._TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY)

    assert mapped["maxDuty"] == config.DEFAULT_MAX_DUTY
    assert mapped["cyclePeriod"] == config.DEFAULT_CYCLE_PERIOD_MS


def test_gopiv_wheel_control_mapping_known_pairs():
    robot_config = config.load_robot_config(str(DATA_DIR / "gopiv.json"))
    mapped = config.wheel_control_to_diffdrive_config(robot_config)

    assert mapped["vMin"] == 0.0
    assert mapped["biasMax"] == 0.0
    assert mapped["stallSpeed"] == 0.0

    # gopiv's travel_calib_left/right are both 0.70486.
    assert mapped["fullDutyVelocity"] == pytest.approx(
        0.70486 * config._TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY)


def test_full_duty_velocity_averages_asymmetric_travel_calib():
    text = (
        '{"identity": {"robot_name": "x"}, "connection": {"radio_channel": 1}, '
        '"motors": {"left_port": 2, "right_port": 1, "fwd_sign_left": 1, '
        '"fwd_sign_right": -1, "travel_calib_left": 0.6, "travel_calib_right": 0.8}, '
        '"wheel_control": {"v_min": 0, "bias_max": 0, "tau_adapt": 0, "a_steady": 0, '
        '"deficit_threshold": 0, "deficit_window": 0, "pid_kp": 0, "pid_ki": 0, '
        '"pid_i_max": 0, "pid_kaff": 0, "pid_max": 0, "pos_err_max": 0, "stall_speed": 0, '
        '"stall_demand": 0, "stall_window": 0}}'
    )
    robot_config = config.parse_robot_config(text)
    mapped = config.wheel_control_to_diffdrive_config(robot_config)
    assert mapped["fullDutyVelocity"] == pytest.approx(
        ((0.6 + 0.8) / 2.0) * config._TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY)


def test_diffdrive_configure_kwargs_matches_native_signature():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    kwargs = config.diffdrive_configure_kwargs(robot_config)
    assert kwargs["left_port"] == 2
    assert kwargs["right_port"] == 1
    assert kwargs["fwd_sign_left"] == -1
    assert kwargs["fwd_sign_right"] == 1
    assert kwargs["max_duty"] == config.DEFAULT_MAX_DUTY
    assert kwargs["full_duty_velocity"] == pytest.approx(
        0.7837 * config._TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY)
    assert kwargs["cycle_period_ms"] == config.DEFAULT_CYCLE_PERIOD_MS


def test_radio_channel():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    assert config.radio_channel(robot_config) == 3


def _make_dispatch():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    return config.ConfigDispatch(robot_config)


# --- name-keyed get_field/set_field (sprint 007 ticket 005) -------------
# v6's GET/SET are by-name, not by-index -- src/hardware/
# protocol_adapter.py's on_get()/on_set() delegate to these rather than
# reaching into ConfigDispatch's private _wheel_control dict directly.

def test_get_field_returns_live_value_for_known_name():
    dispatch = _make_dispatch()
    assert dispatch.get_field("v_min") == pytest.approx(
        dispatch.current_wheel_control()["v_min"])


def test_get_field_returns_none_for_unknown_name():
    dispatch = _make_dispatch()
    assert dispatch.get_field("not_a_real_field") is None


def test_set_field_by_name_applies_live_and_returns_true():
    dispatch = _make_dispatch()
    assert dispatch.set_field("v_min", 42.0) is True
    assert dispatch.current_wheel_control()["v_min"] == pytest.approx(42.0)
    assert dispatch.get_field("v_min") == pytest.approx(42.0)


def test_set_field_by_name_returns_false_for_unknown_name():
    dispatch = _make_dispatch()
    assert dispatch.set_field("not_a_real_field", 1.0) is False


def test_get_field_and_set_field_cover_every_wheel_control_field():
    dispatch = _make_dispatch()
    for json_field, _kernel_field in config.WHEEL_CONTROL_FIELDS:
        assert dispatch.set_field(json_field, 7.0) is True
        assert dispatch.get_field(json_field) == pytest.approx(7.0)
