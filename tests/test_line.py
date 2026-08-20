"""M5 Gate: `src/devices/line.py` against a fake `robotio.i2c_xfer` with the
captured bus facts (0x1A x4 channel reads, 50 ms read period)."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from devices import line  # noqa: E402


class _FakeI2c:
    """Fake `robotio` for the line sensor's write-channel/read-byte
    protocol -- one write/read pair per channel, four per sample."""

    def __init__(self, channel_values=(0, 0, 0, 0), connected=True):
        self.channel_values = list(channel_values)
        self._connected = connected
        self.calls = []

    def i2c_xfer(self, address, write_data=b"", read_len=0, repeated=False,
                 pre_clear=0, post_clear=0):
        self.calls.append((address, bytes(write_data), read_len))
        if address != line.LINE_ADDR or not self._connected:
            return (1, b"")
        channel = write_data[0]
        return (0, bytes([self.channel_values[channel]]))


def test_init_connected_on_successful_4_channel_read():
    i2c = _FakeI2c(channel_values=(10, 20, 30, 40))
    sensor = line.LineSensor(i2c)
    assert sensor.init() is True
    assert sensor.connected is True


def test_init_not_connected_on_bus_error():
    i2c = _FakeI2c(connected=False)
    sensor = line.LineSensor(i2c)
    assert sensor.init() is False


def test_init_touches_all_four_channels():
    i2c = _FakeI2c(channel_values=(10, 20, 30, 40))
    sensor = line.LineSensor(i2c)
    sensor.init()
    channels_written = [call[1][0] for call in i2c.calls if call[0] == line.LINE_ADDR]
    assert channels_written == [0, 1, 2, 3]


def test_read_returns_raw_and_normalized_default_identity_scale():
    i2c = _FakeI2c(channel_values=(0, 128, 255, 64))
    sensor = line.LineSensor(i2c)
    sensor.init()
    reading = sensor.read(now_ms=100)
    assert reading.raw == [0, 128, 255, 64]
    assert reading.normalized[0] == pytest.approx(0.0)
    assert reading.normalized[2] == pytest.approx(1.0)
    assert reading.normalized[1] == pytest.approx(128 / 255.0)


def test_read_applies_custom_calibration_bounds():
    i2c = _FakeI2c(channel_values=(50, 50, 50, 50))
    sensor = line.LineSensor(i2c, cal_min=[20, 20, 20, 20], cal_max=[80, 80, 80, 80])
    sensor.init()
    reading = sensor.read(now_ms=100)
    assert reading.normalized[0] == pytest.approx((50 - 20) / float(80 - 20))


def test_read_clamps_normalized_to_0_1():
    i2c = _FakeI2c(channel_values=(0, 0, 0, 0))
    sensor = line.LineSensor(i2c, cal_min=[10, 10, 10, 10], cal_max=[20, 20, 20, 20])
    sensor.init()
    reading = sensor.read(now_ms=100)
    assert reading.normalized == [0.0, 0.0, 0.0, 0.0]


def test_read_is_gated_by_50ms_period():
    i2c = _FakeI2c(channel_values=(10, 10, 10, 10))
    sensor = line.LineSensor(i2c)
    sensor.init()
    first = sensor.read(now_ms=0)
    assert first.raw == [10, 10, 10, 10]

    i2c.channel_values = [99, 99, 99, 99]
    still_cached = sensor.read(now_ms=49)
    assert still_cached.raw == [10, 10, 10, 10]

    fresh = sensor.read(now_ms=50)
    assert fresh.raw == [99, 99, 99, 99]


def test_read_when_not_connected_returns_cached_no_bus_call():
    i2c = _FakeI2c(connected=False)
    sensor = line.LineSensor(i2c)
    sensor.init()
    calls_before = len(i2c.calls)
    reading = sensor.read(now_ms=100)
    assert reading is sensor.reading
    assert len(i2c.calls) == calls_before


def test_read_bus_error_keeps_last_good_reading():
    i2c = _FakeI2c(channel_values=(5, 6, 7, 8))
    sensor = line.LineSensor(i2c)
    sensor.init()
    good = sensor.read(now_ms=0)
    assert good.raw == [5, 6, 7, 8]

    i2c._connected = False
    still_good = sensor.read(now_ms=100)
    assert still_good.raw == [5, 6, 7, 8]
