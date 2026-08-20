"""otos -- SparkFun OTOS optical tracking driver, spec Sec 6.

Bus access only via the moddiffdrive I2C broker (``robotio.i2c_xfer()``)
so the shared per-device clearance ledger (spec Sec 5) stays intact.

Register map (I2C 0x17, vs radio-robot-elite's ``real_otos.h``):
  0x00 product ID (expect 0x5F)  0x04 linear scalar  0x05 angular scalar
  0x20 position (x/y/heading, 3x int16 LE)  0x26 velocity (vx/vy/omega,
  3x int16 LE) -- one 12-byte read from 0x20 covers both.

Scale table: position 0.305 mm/LSB, heading 0.00549 deg/LSB (-> rad
here), velocity 5000/32768 mm/s/LSB, omega 34.9/32768 rad/s/LSB.

Read period 20 ms: ``read()`` is a no-op (cached) if called sooner.
"""

import struct

__all__ = ["OTOS_ADDR", "READ_PERIOD_MS", "OtosReading", "Otos"]

OTOS_ADDR = 0x17

_REG_PRODUCT_ID = 0x00
_REG_LINEAR_SCALAR = 0x04
_REG_ANGULAR_SCALAR = 0x05
_REG_POSITION_XL = 0x20

_EXPECTED_PRODUCT_ID = 0x5F

# scale -> int8 register: raw = round((scale - 1.0) / 0.001), clamped
# to int8 range (real_otos.cpp scaleToRegister()).
_SCALE_REGISTER_STEP = 0.001
_SCALE_REGISTER_MAX = 127
_SCALE_REGISTER_MIN = -127


def _scale_to_register(scale):
    raw = int(round((scale - 1.0) / _SCALE_REGISTER_STEP))
    if raw > _SCALE_REGISTER_MAX:
        raw = _SCALE_REGISTER_MAX
    if raw < _SCALE_REGISTER_MIN:
        raw = _SCALE_REGISTER_MIN
    return raw


_POS_MM_PER_LSB = 0.305
_HDG_RAD_PER_LSB = 0.00549 * (3.14159265 / 180.0)
_VEL_MM_S_PER_LSB = 5000.0 / 32768.0
_OMEGA_RAD_S_PER_LSB = 34.9 / 32768.0

READ_PERIOD_MS = 20


class OtosReading:
    """One sample: x/y [mm], heading [rad], v_x/v_y [mm/s], omega
    [rad/s]. Plain attributes (no ``dataclasses`` -- host-only import)."""

    def __init__(self, x=0.0, y=0.0, heading=0.0, v_x=0.0, v_y=0.0, omega=0.0):
        self.x = x
        self.y = y
        self.heading = heading
        self.v_x = v_x
        self.v_y = v_y
        self.omega = omega


class Otos:
    """Driver over a duck-typed ``i2c`` exposing ``i2c_xfer(address,
    write_data=b'', read_len=0, repeated=False, pre_clear=0,
    post_clear=0) -> int | (int, bytes)`` (real ``robotio`` on-device;
    fake in tests).

    ``linear_scale``/``angular_scale``: config JSON's ``otos`` group,
    default 1.0; ``init()`` writes them via ``_scale_to_register()``."""

    def __init__(self, i2c, linear_scale=1.0, angular_scale=1.0):
        self._i2c = i2c
        self.linear_scale = linear_scale
        self.angular_scale = angular_scale
        self.connected = False
        self.product_id = None
        self.last_read_ms = None
        self.reading = OtosReading()

    def init(self):
        """Probes the product ID register; ``connected`` iff it reads
        back 0x5F. A bus error leaves it False; never raises."""
        status, data = self._i2c.i2c_xfer(
            OTOS_ADDR, write_data=bytes([_REG_PRODUCT_ID]), read_len=1, repeated=True
        )
        if status == 0 and data:
            self.product_id = data[0]
            self.connected = self.product_id == _EXPECTED_PRODUCT_ID
        else:
            self.product_id = None
            self.connected = False

        if self.connected:
            self._i2c.i2c_xfer(
                OTOS_ADDR,
                write_data=bytes([_REG_LINEAR_SCALAR, _scale_to_register(self.linear_scale) & 0xFF]),
            )
            self._i2c.i2c_xfer(
                OTOS_ADDR,
                write_data=bytes([_REG_ANGULAR_SCALAR, _scale_to_register(self.angular_scale) & 0xFF]),
            )
        return self.connected

    def read(self, now_ms):
        """Read position+velocity if ``READ_PERIOD_MS`` elapsed since
        the last read, else return the cached ``self.reading``. A bus
        error leaves it unchanged; never raises."""
        if not self.connected:
            return self.reading
        if self.last_read_ms is not None and (now_ms - self.last_read_ms) < READ_PERIOD_MS:
            return self.reading

        status, data = self._i2c.i2c_xfer(OTOS_ADDR, write_data=bytes([_REG_POSITION_XL]),
                                           read_len=12, repeated=True)
        self.last_read_ms = now_ms
        if status != 0 or not data or len(data) < 12:
            return self.reading

        x_raw, y_raw, h_raw, vx_raw, vy_raw, w_raw = struct.unpack("<6h", bytes(data))
        self.reading = OtosReading(
            x=x_raw * _POS_MM_PER_LSB,
            y=y_raw * _POS_MM_PER_LSB,
            heading=h_raw * _HDG_RAD_PER_LSB,
            v_x=vx_raw * _VEL_MM_S_PER_LSB,
            v_y=vy_raw * _VEL_MM_S_PER_LSB,
            omega=w_raw * _OMEGA_RAD_S_PER_LSB,
        )
        return self.reading
