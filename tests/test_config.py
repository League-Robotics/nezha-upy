"""M5 gate: `src/config.py`'s fail-closed key validation and the
`wheel_control` -> `DiffDrive::Config` mapping (travel_calib x10).
See `clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/
007-python-firmware-layer-config-telemetry-motion-otos-line-m5.md`'s
acceptance criteria this file encodes:

  - fail-closed key validation against data/tovez.json, data/gopiv.json,
    and a deliberately-malformed fixture (refusal asserted);
  - wheel_control -> DiffDrive::Config mapping (travel_calib x10)
    against known input/output pairs;
  - the CONFIG/SET_FIELD/GET_CONFIG dispatch wiring (Gate section).
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

import config  # noqa: E402  (path must be set up first)
import wire  # noqa: E402


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
    # JSON `true`/`false` decode to Python bool, a subclass of int --
    # explicitly rejected (see config.py's own comment on this).
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

    # Direct 1:1 renamed fields -- known input/output pairs straight from
    # data/tovez.json's own wheel_control group.
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
    assert mapped["fullDutyVelocity"] == pytest.approx(0.7837 * 10.0)

    assert mapped["maxDuty"] == config.DEFAULT_MAX_DUTY
    assert mapped["cyclePeriod"] == config.DEFAULT_CYCLE_PERIOD_MS


def test_gopiv_wheel_control_mapping_known_pairs():
    robot_config = config.load_robot_config(str(DATA_DIR / "gopiv.json"))
    mapped = config.wheel_control_to_diffdrive_config(robot_config)

    assert mapped["vMin"] == 0.0
    assert mapped["biasMax"] == 0.0
    assert mapped["stallSpeed"] == 0.0

    # gopiv's travel_calib_left/right are both 0.70486.
    assert mapped["fullDutyVelocity"] == pytest.approx(0.70486 * 10.0)


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
    assert mapped["fullDutyVelocity"] == pytest.approx(((0.6 + 0.8) / 2.0) * 10.0)


def test_diffdrive_configure_kwargs_matches_native_signature():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    kwargs = config.diffdrive_configure_kwargs(robot_config)
    assert kwargs["left_port"] == 2
    assert kwargs["right_port"] == 1
    assert kwargs["fwd_sign_left"] == -1
    assert kwargs["fwd_sign_right"] == 1
    assert kwargs["max_duty"] == config.DEFAULT_MAX_DUTY
    assert kwargs["full_duty_velocity"] == pytest.approx(0.7837 * 10.0)
    assert kwargs["cycle_period_ms"] == config.DEFAULT_CYCLE_PERIOD_MS


def test_radio_channel():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    assert config.radio_channel(robot_config) == 3


# --- CONFIG/SET_FIELD/GET_CONFIG dispatch -------------------------------

class _FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(bytes(data))


def _make_dispatch():
    robot_config = config.load_robot_config(str(DATA_DIR / "tovez.json"))
    return config.ConfigDispatch(robot_config)


def test_set_field_applies_live_and_acks_ok():
    dispatch = _make_dispatch()
    import struct
    payload = bytes([7, config.CONFIG_GROUP_WHEEL_CONTROL, 0]) + struct.pack("<f", 99.0)
    result = dispatch.handle_command("SET_FIELD", payload, 1000)
    assert result == (7, config.ERR_OK)
    assert dispatch.current_wheel_control()["v_min"] == pytest.approx(99.0)


def test_set_field_rejects_unwired_group():
    dispatch = _make_dispatch()
    import struct
    payload = bytes([7, 99, 0]) + struct.pack("<f", 1.0)
    result = dispatch.handle_command("SET_FIELD", payload, 1000)
    assert result == (7, config.ERR_UNIMPLEMENTED)


def test_set_field_rejects_bad_field_index():
    dispatch = _make_dispatch()
    import struct
    payload = bytes([7, config.CONFIG_GROUP_WHEEL_CONTROL, 200]) + struct.pack("<f", 1.0)
    result = dispatch.handle_command("SET_FIELD", payload, 1000)
    assert result == (7, config.ERR_MALFORMED)


def test_set_field_rejects_wrong_length():
    dispatch = _make_dispatch()
    result = dispatch.handle_command("SET_FIELD", bytes([7, 1]), 1000)
    assert result == (7, config.ERR_MALFORMED)


def test_config_bulk_applies_whole_group():
    dispatch = _make_dispatch()
    import struct
    body = bytes([9, config.CONFIG_GROUP_WHEEL_CONTROL])
    for i in range(len(config.WHEEL_CONTROL_FIELDS)):
        body += struct.pack("<f", float(i))
    result = dispatch.handle_command("CONFIG", body, 1000)
    assert result == (9, config.ERR_OK)
    wc = dispatch.current_wheel_control()
    for i, (json_field, _kernel_field) in enumerate(config.WHEEL_CONTROL_FIELDS):
        assert wc[json_field] == pytest.approx(float(i))


def test_get_config_acks_and_broadcasts_cfg_frame():
    dispatch = _make_dispatch()
    transport = _FakeTransport()
    dispatch.add_transport(transport)
    payload = bytes([3, config.CONFIG_GROUP_WHEEL_CONTROL])
    result = dispatch.handle_command("GET_CONFIG", payload, 1000)
    assert result == (3, config.ERR_OK)
    assert len(transport.sent) == 1

    decoded = wire.decode_frame(transport.sent[0], command=b"CFG")
    assert decoded is not None
    assert decoded[0] == config.CONFIG_GROUP_WHEEL_CONTROL


def test_get_config_unwired_group_acks_unimplemented_no_broadcast():
    dispatch = _make_dispatch()
    transport = _FakeTransport()
    dispatch.add_transport(transport)
    payload = bytes([3, 99])
    result = dispatch.handle_command("GET_CONFIG", payload, 1000)
    assert result == (3, config.ERR_UNIMPLEMENTED)
    assert transport.sent == []


def test_get_config_with_no_transports_still_acks():
    dispatch = _make_dispatch()
    payload = bytes([3, config.CONFIG_GROUP_WHEEL_CONTROL])
    result = dispatch.handle_command("GET_CONFIG", payload, 1000)
    assert result == (3, config.ERR_OK)


def test_unknown_verb_returns_none():
    dispatch = _make_dispatch()
    assert dispatch.handle_command("WHEELS", b"", 1000) is None
