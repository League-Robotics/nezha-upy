"""demo_util -- config-scan + duty-balance helpers split out of
demo_square (OOP bench session 2026-08-19): demo_square outgrew this
port's on-device compile-heap ceiling (~11-13 KB stripped source), so
the shared helpers live here and compile separately. Pure-Python,
CPython+MicroPython clean, no hardware access at import."""

ROBOT_CONFIG_PATH = "robot.json"
MAX_DUTY_PERCENT = 25.0   # [%] duty clamp; MUST match demo_square's rail


def _scan_number(text, key):
    """Return the numeric value following ``"key":`` in ``text``, or
    ``None`` if the key is absent or its value does not parse as a
    float. Whitespace after the colon is tolerated; the value ends at
    the first ``,``, ``}``, or ``]``."""
    i = text.find('"' + key + '"')
    if i < 0:
        return None
    i = text.find(":", i)
    if i < 0:
        return None
    j = i + 1
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    k = j
    while k < len(text) and text[k] not in ",}]":
        k += 1
    try:
        return float(text[j:k])
    except ValueError:
        return None

def geometry_from_robot_config(path=ROBOT_CONFIG_PATH):
    """Sprint 006 ticket 001: narrow, fail-SOFT read of ONLY
    ``wheels.wheel_diameter_mm``/``wheels.ticks_per_rev`` from the robot
    config JSON at ``path`` -- see module docstring's "Config-driven
    geometry" section for why this is a dedicated lightweight parse
    rather than ``config.load_robot_config()`` (two independent,
    bench-grounded, concrete reasons stated there). Returns
    ``(wheel_diameter_mm, ticks_per_rev)`` as floats on success;
    ``None`` on ANY problem -- missing/unreadable file, either key not
    found, non-numeric value, or non-positive. NEVER raises; the caller
    falls back to the hardcoded constants below.

    Implementation is a dependency-free string scan, not a JSON parse:
    this image ships no json/ujson module (bench-confirmed), and both
    keys appear exactly once in the deployed compact config (their only
    JSON home is the wheels group)."""
    try:
        with open(path, "r") as f:
            text = f.read()
        wheel_diameter_mm = _scan_number(text, "wheel_diameter_mm")
        ticks_per_rev = _scan_number(text, "ticks_per_rev")
    except OSError:
        return None
    if wheel_diameter_mm is None or ticks_per_rev is None:
        return None
    if wheel_diameter_mm <= 0.0 or ticks_per_rev <= 0.0:
        return None
    return wheel_diameter_mm, ticks_per_rev

def _wiring_from_robot_config(path=ROBOT_CONFIG_PATH):
    """Fail-soft read of motors.left_port/right_port/fwd_sign_left/
    fwd_sign_right from the deployed compact config. Returns a 4-tuple
    of ints, or None on any missing/non-integer value. NEVER raises."""
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        return None
    vals = []
    for key in ("left_port", "right_port", "fwd_sign_left",
                "fwd_sign_right"):
        v = _scan_number(text, key)
        if v is None or v != int(v):
            return None
        vals.append(int(v))
    return tuple(vals)

BALANCE_GAIN = 0.02      # [%/tick] P-gain: duty trim per tick of

BALANCE_TRIM_MAX = 8.0   # [%] trim authority cap per wheel

BALANCE_KI = 0.004       # [%/tick per poll] integral: kills the P-only

BALANCE_BIAS_MAX = 8.0   # [%] integral wind-up clamp

BALANCE_BIAS_SEED = -3.5   # [%]

def balanced_duties(duty_left, duty_right, delta_left, delta_right,
                    gain=BALANCE_GAIN, trim_max=BALANCE_TRIM_MAX,
                    bias=0.0):
    """Encoder-balancing P-controller: returns ``(duty_left, duty_right)``
    trimmed so the wheel whose |tick progress| leads is slowed and the
    laggard sped up, keeping legs straight and pivots symmetric. Signs
    of the commanded duties are preserved (works for pivots' opposed
    duties); a zero commanded duty stays zero; trimmed magnitudes are
    clamped to [0, MAX_DUTY_PERCENT]. Pure function -- offline-testable."""
    err = abs(delta_left) - abs(delta_right)   # [ticks] >0: left ahead
    trim = gain * err + bias
    if trim > trim_max:
        trim = trim_max
    elif trim < -trim_max:
        trim = -trim_max

    def _apply(duty, t):
        if duty == 0.0:
            return 0.0
        sign = 1.0 if duty > 0.0 else -1.0
        mag = abs(duty) + t
        if mag < 0.0:
            mag = 0.0
        elif mag > MAX_DUTY_PERCENT:
            mag = MAX_DUTY_PERCENT
        return sign * mag

    return _apply(duty_left, -trim), _apply(duty_right, trim)
