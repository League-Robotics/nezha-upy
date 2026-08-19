"""otos -- SparkFun OTOS optical tracking chip driver (I2C 0x17), M5
(PLAN.md / ``docs/design/specification.md`` Sec 6).

All bus traffic goes through the moddiffdrive I2C broker
(``robotio.i2c_xfer()``, ticket 004) -- never a direct bus access -- so
the shared clearance ledger (per-device ``lastEnd``/``readyAt`` timers,
spec Sec 5 "One I2C ledger") stays intact between Python sensor code and
the kernel's own Nezha traffic.

Bus facts as captured (ticket 007's own scope note: "0x17 init/scales/
20 ms"), verified against radio-robot-elite's current
``src/firm/hardware/generic/real_otos.h`` (the chip-level register map
and LSB scales are hardware facts, not something the kernel-rewrite the
rest of that repo's telemetry stack went through touched):

  - Device address 0x17.
  - Registers: product ID 0x00 (expected 0x5F), linear scalar 0x04,
    angular scalar 0x05, position block starting at 0x20 (x/y/heading,
    3x int16 LE), velocity block starting at 0x26 (vx/vy/omega, 3x
    int16 LE) -- one contiguous 12-byte read from 0x20 covers both
    blocks.
  - Scales: position 0.305 mm/LSB, heading 0.00549 deg/LSB (converted to
    rad/LSB here), velocity 5000/32768 mm/s/LSB, omega 34.9/32768
    rad/s/LSB.
  - Read period 20 ms (``kReadPeriod`` = 20000 us) -- ``read()`` below is
    a no-op (returns the cached reading) if called before that much time
    has elapsed since the last real bus read, matching the chip's own
    documented budget.

``init()`` probes the product ID and applies the robot's configured
linear/angular scalars (``otos.linear_scale``/``otos.angular_scale``,
``data/*.json``'s ``otos`` group) -- mirrors ``RealOtos::begin()``'s own
two-step (probe, then apply scalars) shape.
"""

import struct

__all__ = ["OTOS_ADDR", "READ_PERIOD_MS", "OtosReading", "Otos"]

OTOS_ADDR = 0x17

_REG_PRODUCT_ID = 0x00
_REG_LINEAR_SCALAR = 0x04
_REG_ANGULAR_SCALAR = 0x05
_REG_POSITION_XL = 0x20

_EXPECTED_PRODUCT_ID = 0x5F

# scale -> int8 register encoding, verified against radio-robot-elite's
# real_otos.cpp scaleToRegister(): raw = round((scale - 1.0) / 0.001),
# clamped to an int8's range. Chip knowledge, not something this repo's
# kernel rewrite touched -- ported here since robotio.i2c_xfer() lets
# this driver actually perform the write, unlike the scale factor itself
# (recorded, not blindly guessed, where no such reference existed).
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
    """One sample -- ``x``/``y`` [mm], ``heading`` [rad], ``v_x``/``v_y``
    [mm/s], ``omega`` [rad/s]. Plain mutable attributes (no
    ``dataclasses`` -- host-only import), matching ``comms.py``'s own
    ``Status`` precedent."""

    def __init__(self, x=0.0, y=0.0, heading=0.0, v_x=0.0, v_y=0.0, omega=0.0):
        self.x = x
        self.y = y
        self.heading = heading
        self.v_x = v_x
        self.v_y = v_y
        self.omega = omega


class Otos:
    """Driver over a duck-typed ``i2c`` object exposing
    ``i2c_xfer(address, write_data=b'', read_len=0, repeated=False,
    pre_clear=0, post_clear=0) -> int | (int, bytes)`` -- the real
    ``robotio`` module on-device, a fake in ``tests/test_otos.py``.

    ``linear_scale``/``angular_scale``: from the robot's config JSON
    (``otos`` group) -- see ``config.py``. Both default to 1.0
    (identity); ``init()`` writes them to the chip's scalar registers
    via ``_scale_to_register()`` (see module docstring for the formula's
    source)."""

    def __init__(self, i2c, linear_scale=1.0, angular_scale=1.0):
        self._i2c = i2c
        self.linear_scale = linear_scale
        self.angular_scale = angular_scale
        self.connected = False
        self.product_id = None
        self.last_read_ms = None
        self.reading = OtosReading()

    def init(self):
        """Probe the product ID register; ``connected`` is True iff it
        reads back ``_EXPECTED_PRODUCT_ID`` (0x5F) -- mirrors
        ``RealOtos::begin()``'s own probe-then-configure shape. Never
        raises on a bus error -- a disconnected/absent OTOS is a normal,
        expected condition (this robot's own ``otos_present`` status
        flag exists for exactly this), not a fault."""
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
        """Read position+velocity if ``READ_PERIOD_MS`` has elapsed since
        the last real read; otherwise return the cached ``self.reading``
        unchanged (matches the chip's own 20 ms budget -- see module
        docstring). Returns ``self.reading``. A bus error leaves
        ``self.reading`` at its last good value and does not raise."""
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
