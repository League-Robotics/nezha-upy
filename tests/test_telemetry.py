"""M5 gate: `src/core/telemetry.py`'s 22-field frame assembly against a
synthetic sensor/kernel-state fixture -- the watchdog fault bit and
`cycleOverrunCount_` must be present and populated."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from devices import line  # noqa: E402
from devices import otos  # noqa: E402
from core import telemetry  # noqa: E402


EXPECTED_FIELDS = {
    "now", "seq", "mode", "flags", "enc_left", "enc_right", "otos", "pose",
    "twist", "line", "color", "acks", "cycle_busy", "cycle_period",
    "duty_per_speed_left", "duty_per_speed_right", "bias_left", "bias_right",
    "pid_left", "pid_right", "cycle_overrun_count", "watchdog_fault",
}


def test_frame_has_exactly_22_fields():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    frame = builder.build(state, acks=[], now=0)
    assert set(frame.keys()) == EXPECTED_FIELDS
    assert len(frame) == 22


def test_default_state_all_zero_no_faults():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    frame = builder.build(state, acks=[], now=1000)
    assert frame["now"] == 1000
    assert frame["seq"] == 0
    assert frame["watchdog_fault"] is False
    assert frame["cycle_overrun_count"] == 0
    assert frame["flags"] & telemetry.FLAG_WATCHDOG_FAULT == 0
    assert frame["color"] == 0
    assert frame["duty_per_speed_left"] == 0.0
    assert frame["bias_left"] == 0.0
    assert frame["pid_left"] == 0.0


def test_seq_increments_and_wraps_mod_128():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    seqs = [builder.build(state, acks=[], now=i)["seq"] for i in range(140)]
    assert seqs[:5] == [0, 1, 2, 3, 4]
    assert seqs[127] == 127
    assert seqs[128] == 0
    assert seqs[139] == 11


def test_watchdog_fault_bit_present_and_populated():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.diffdrive_output = {"watchdogFault": True, "cycleOverrunCount": 3}
    frame = builder.build(state, acks=[], now=0)
    assert frame["watchdog_fault"] is True
    assert frame["flags"] & telemetry.FLAG_WATCHDOG_FAULT == telemetry.FLAG_WATCHDOG_FAULT
    assert frame["cycle_overrun_count"] == 3


def test_cycle_overrun_count_populated_from_kernel_state():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.diffdrive_output = {"cycleOverrunCount": 42}
    frame = builder.build(state, acks=[], now=0)
    assert frame["cycle_overrun_count"] == 42


def test_encoder_and_twist_fields_from_kernel_output():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.diffdrive_output = {
        "positionLeft": 100.0, "positionRight": 105.0,
        "velocityLeft": 10.0, "velocityRight": 11.0,
        "velocity": 10.5, "twist": 0.02,
    }
    frame = builder.build(state, acks=[], now=0)
    assert frame["enc_left"] == {"position": 100.0, "velocity": 10.0}
    assert frame["enc_right"] == {"position": 105.0, "velocity": 11.0}
    assert frame["twist"] == {"v_x": 10.5, "omega": 0.02}


def test_otos_field_populated_when_reading_present():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.otos_present = True
    state.otos_reading = otos.OtosReading(x=1.0, y=2.0, heading=0.5, v_x=3.0, v_y=4.0, omega=0.1)
    frame = builder.build(state, acks=[], now=0)
    assert frame["otos"]["x"] == 1.0
    assert frame["otos"]["heading"] == 0.5
    assert frame["flags"] & telemetry.FLAG_OTOS_PRESENT == telemetry.FLAG_OTOS_PRESENT
    assert frame["flags"] & telemetry.FLAG_OTOS_CONNECTED == telemetry.FLAG_OTOS_CONNECTED


def test_otos_field_zero_when_no_reading():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    frame = builder.build(state, acks=[], now=0)
    assert frame["otos"] == {"x": 0.0, "y": 0.0, "heading": 0.0, "v_x": 0.0, "v_y": 0.0, "omega": 0.0, "age": 0}
    assert frame["flags"] & telemetry.FLAG_OTOS_CONNECTED == 0


def test_line_field_packs_four_channels():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.line_present = True
    state.line_reading = line.LineReading(raw=[0x11, 0x22, 0x33, 0x44])
    frame = builder.build(state, acks=[], now=0)
    assert frame["line"] == 0x11223344
    assert frame["flags"] & telemetry.FLAG_LINE_PRESENT == telemetry.FLAG_LINE_PRESENT


def test_acks_pass_through_oldest_first():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    frame = builder.build(state, acks=[0x12, 0x34], now=0)
    assert frame["acks"] == [0x12, 0x34]


def test_pose_from_state():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.pose_x = 10
    state.pose_y = -5
    state.pose_heading = 3
    frame = builder.build(state, acks=[], now=0)
    assert frame["pose"] == {"x": 10, "y": -5, "heading": 3}


def test_active_and_connected_flags():
    builder = telemetry.TelemetryFrameBuilder()
    state = telemetry.TelemetryState()
    state.active = True
    state.diffdrive_output = {"connectedLeft": True, "connectedRight": False}
    frame = builder.build(state, acks=[], now=0)
    assert frame["flags"] & telemetry.FLAG_ACTIVE == telemetry.FLAG_ACTIVE
    assert frame["flags"] & telemetry.FLAG_CONN_LEFT == telemetry.FLAG_CONN_LEFT
    assert frame["flags"] & telemetry.FLAG_CONN_RIGHT == 0


def test_pack_line_channels_pads_short_list():
    assert telemetry.pack_line_channels([0xAA]) == 0xAA000000
    assert telemetry.pack_line_channels(None) == 0
