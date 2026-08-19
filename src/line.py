"""line -- PlanetX 4-channel line sensor driver (I2C 0x1A), M5 (PLAN.md /
``docs/design/specification.md`` Sec 6).

All bus traffic goes through the moddiffdrive I2C broker
(``robotio.i2c_xfer()``, ticket 004) -- never a direct bus access -- so
the shared clearance ledger stays intact (spec Sec 5 "One I2C ledger"),
same discipline as ``otos.py``.

Bus facts as captured (ticket 007's own scope note: "0x1A x4/50 ms"),
verified against radio-robot-elite's current
``src/firm/hardware/planetx/line_sensor.h`` (chip-level protocol, not
touched by that repo's kernel rewrite):

  - Device address 0x1A.
  - Protocol: write one byte (channel index 0-3), then read one byte of
    grayscale data (0 = white, 255 = black, approximately) -- FOUR such
    write/read pairs per full sample (one per channel).
  - Read period 50 ms (``kDefaultLagLine`` = 50) -- ``read()`` below is a
    no-op (returns the cached reading) if called before that much time
    has elapsed since the last real bus read.

Normalization: the schema/`data/*.json` carry no per-channel calibration
(``cal_min``/``cal_max``) fields today -- ``robot_config.schema.json``
has no such group, and the copied per-robot JSON's own ``perception``
block only records mount geometry, not calibration bounds (see
``data/tovez.json``'s own ``perception`` block). Rather than fabricate a
calibration this repo has no source for, ``LineSensor`` normalizes with
the chip's own raw 0-255 span as the identity calibration
(``cal_min=0``, ``cal_max=255``) unless a caller supplies real bounds --
flagged here, not silently invented, matching this codebase's own
"flag rather than fabricate a number" discipline (see e.g.
``data/README.md``)."""

__all__ = ["LINE_ADDR", "READ_PERIOD_MS", "LineReading", "LineSensor"]

LINE_ADDR = 0x1A

READ_PERIOD_MS = 50

_NUM_CHANNELS = 4

_DEFAULT_CAL_MIN = 0
_DEFAULT_CAL_MAX = 255


class LineReading:
    """One 4-channel sample. ``raw``: list[int], 0-255 per channel, left
    to right (matches ``data/tovez.json``'s ``perception.line_array.
    channel_y`` ordering -- channel 0 is left-most). ``normalized``:
    list[float], 0.0-1.0 per channel after ``cal_min``/``cal_max``
    scaling and clamping."""

    def __init__(self, raw=None, normalized=None):
        self.raw = list(raw) if raw is not None else [0] * _NUM_CHANNELS
        self.normalized = list(normalized) if normalized is not None else [0.0] * _NUM_CHANNELS


def _normalize(raw_value, cal_min, cal_max):
    span = cal_max - cal_min
    if span <= 0:
        return 0.0
    value = (raw_value - cal_min) / float(span)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


class LineSensor:
    """Driver over a duck-typed ``i2c`` object exposing the same
    ``i2c_xfer()`` contract ``otos.Otos`` uses -- the real ``robotio``
    module on-device, a fake in ``tests/test_line.py``.

    ``cal_min``/``cal_max``: per-channel calibration bounds (lists of 4
    ints), defaulting to the chip's own raw span (0-255, see module
    docstring) until a real calibration source exists."""

    def __init__(self, i2c, cal_min=None, cal_max=None):
        self._i2c = i2c
        self.cal_min = list(cal_min) if cal_min is not None else [_DEFAULT_CAL_MIN] * _NUM_CHANNELS
        self.cal_max = list(cal_max) if cal_max is not None else [_DEFAULT_CAL_MAX] * _NUM_CHANNELS
        self.connected = False
        self.last_read_ms = None
        self.reading = LineReading()

    def init(self):
        """Probe presence: one full 4-channel raw read must succeed
        (status 0 on every channel) -- mirrors ``LineSensorLeaf::
        beginStep()``'s own "a successful 4-channel raw read means
        present" contract, simplified to a single attempt (this port has
        no fiber-cycle-paced retry loop to drive a multi-attempt
        detection state machine through; a caller that wants retries can
        call ``init()`` again). Never raises on a bus error."""
        raw = self._read_raw()
        self.connected = raw is not None
        if self.connected:
            self.last_read_ms = None  # force a fresh read on the next read()
        return self.connected

    def _read_raw(self):
        raw = []
        for channel in range(_NUM_CHANNELS):
            status, data = self._i2c.i2c_xfer(
                LINE_ADDR, write_data=bytes([channel]), read_len=1, repeated=True
            )
            if status != 0 or not data:
                return None
            raw.append(data[0])
        return raw

    def read(self, now_ms):
        """Read all 4 channels if ``READ_PERIOD_MS`` has elapsed since
        the last real read; otherwise return the cached ``self.reading``
        unchanged (matches the chip's own 50 ms budget -- see module
        docstring). Returns ``self.reading``. A bus error leaves
        ``self.reading`` at its last good value and does not raise."""
        if not self.connected:
            return self.reading
        if self.last_read_ms is not None and (now_ms - self.last_read_ms) < READ_PERIOD_MS:
            return self.reading

        raw = self._read_raw()
        self.last_read_ms = now_ms
        if raw is None:
            return self.reading

        normalized = [
            _normalize(raw[i], self.cal_min[i], self.cal_max[i]) for i in range(_NUM_CHANNELS)
        ]
        self.reading = LineReading(raw=raw, normalized=normalized)
        return self.reading
