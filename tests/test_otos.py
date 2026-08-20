"""M5 Gate: `src/devices/otos.py` against a fake `robotio.i2c_xfer` with the
captured bus facts (0x17, init/scales, 20 ms read period)."""

import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from devices import otos  # noqa: E402


class _FakeI2c:
    """Fake `robotio` -- records every transaction and answers from a
    small register model matching the real chip's own layout (product
    ID at 0x00, scalar registers at 0x04/0x05, a 12-byte position+
    velocity block starting at 0x20)."""

    def __init__(self, product_id=otos._EXPECTED_PRODUCT_ID, connected=True):
        self._product_id = product_id
        self._connected = connected
        self.calls = []
        self.written_linear_scalar = None
        self.written_angular_scalar = None
        self.position_velocity_raw = (0, 0, 0, 0, 0, 0)  # x,y,h,vx,vy,omega ints

    def i2c_xfer(self, address, write_data=b"", read_len=0, repeated=False,
                 pre_clear=0, post_clear=0):
        self.calls.append((address, bytes(write_data), read_len))
        if address != otos.OTOS_ADDR:
            return (1, b"") if read_len else 1
        if not self._connected:
            return (1, b"") if read_len else 1

        if write_data and write_data[0] == otos._REG_PRODUCT_ID and read_len == 1:
            return (0, bytes([self._product_id]))
        if write_data and write_data[0] == otos._REG_POSITION_XL and read_len == 12:
            return (0, struct.pack("<6h", *self.position_velocity_raw))
        if len(write_data) == 2 and write_data[0] == otos._REG_LINEAR_SCALAR:
            self.written_linear_scalar = write_data[1]
            return 0
        if len(write_data) == 2 and write_data[0] == otos._REG_ANGULAR_SCALAR:
            self.written_angular_scalar = write_data[1]
            return 0
        return (0, b"\x00" * read_len) if read_len else 0


def test_init_connected_when_product_id_matches():
    i2c = _FakeI2c()
    driver = otos.Otos(i2c, linear_scale=1.0, angular_scale=1.0)
    assert driver.init() is True
    assert driver.connected is True
    assert driver.product_id == otos._EXPECTED_PRODUCT_ID


def test_init_not_connected_on_wrong_product_id():
    i2c = _FakeI2c(product_id=0x00)
    driver = otos.Otos(i2c)
    assert driver.init() is False
    assert driver.connected is False


def test_init_not_connected_on_bus_error():
    i2c = _FakeI2c(connected=False)
    driver = otos.Otos(i2c)
    assert driver.init() is False


def test_init_writes_identity_scale_as_zero_register():
    i2c = _FakeI2c()
    driver = otos.Otos(i2c, linear_scale=1.0, angular_scale=1.0)
    driver.init()
    assert i2c.written_linear_scalar == 0
    assert i2c.written_angular_scalar == 0


def test_init_writes_nonzero_scale_register():
    i2c = _FakeI2c()
    # scale=1.010 -> (1.010 - 1.0) / 0.001 = 10
    driver = otos.Otos(i2c, linear_scale=1.010, angular_scale=0.990)
    driver.init()
    assert i2c.written_linear_scalar == 10
    assert (i2c.written_angular_scalar - 256 if i2c.written_angular_scalar > 127
            else i2c.written_angular_scalar) == -10


def test_scale_register_clamps_to_int8_range():
    assert otos._scale_to_register(2.0) == 127
    assert otos._scale_to_register(0.0) == -127


def test_read_applies_captured_scales():
    i2c = _FakeI2c()
    driver = otos.Otos(i2c)
    driver.init()
    # x=100 raw -> 100 * 0.305 mm; heading raw=1000 -> rad scale.
    i2c.position_velocity_raw = (100, -50, 1000, 200, 0, 500)
    reading = driver.read(now_ms=0)
    assert reading.x == pytest.approx(100 * otos._POS_MM_PER_LSB)
    assert reading.y == pytest.approx(-50 * otos._POS_MM_PER_LSB)
    assert reading.heading == pytest.approx(1000 * otos._HDG_RAD_PER_LSB)
    assert reading.v_x == pytest.approx(200 * otos._VEL_MM_S_PER_LSB)
    assert reading.omega == pytest.approx(500 * otos._OMEGA_RAD_S_PER_LSB)


def test_read_is_gated_by_20ms_period():
    i2c = _FakeI2c()
    driver = otos.Otos(i2c)
    driver.init()
    i2c.position_velocity_raw = (100, 0, 0, 0, 0, 0)
    first = driver.read(now_ms=0)
    assert first.x == pytest.approx(100 * otos._POS_MM_PER_LSB)

    # Change the underlying data but read before the 20 ms period elapses
    # -- the cached reading must not change.
    i2c.position_velocity_raw = (999, 0, 0, 0, 0, 0)
    still_cached = driver.read(now_ms=19)
    assert still_cached.x == pytest.approx(100 * otos._POS_MM_PER_LSB)

    fresh = driver.read(now_ms=20)
    assert fresh.x == pytest.approx(999 * otos._POS_MM_PER_LSB)


def test_read_when_not_connected_returns_cached_reading_no_bus_call():
    i2c = _FakeI2c(connected=False)
    driver = otos.Otos(i2c)
    driver.init()
    calls_before = len(i2c.calls)
    reading = driver.read(now_ms=100)
    assert reading is driver.reading
    assert len(i2c.calls) == calls_before  # no additional bus traffic


def test_read_bus_error_keeps_last_good_reading():
    i2c = _FakeI2c()
    driver = otos.Otos(i2c)
    driver.init()
    i2c.position_velocity_raw = (100, 0, 0, 0, 0, 0)
    good = driver.read(now_ms=0)
    assert good.x == pytest.approx(100 * otos._POS_MM_PER_LSB)

    i2c._connected = False
    still_good = driver.read(now_ms=100)
    assert still_good.x == pytest.approx(100 * otos._POS_MM_PER_LSB)
