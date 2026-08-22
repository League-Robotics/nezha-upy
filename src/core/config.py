"""config -- per-robot JSON loader, fail-closed key validation, and the
``wheel_control`` -> ``DiffDrive::Config`` mapping (spec Sec 6/8, UC-011).

Loads one robot's JSON (``data/<robot>.json``, schema in
``data/robot_config.schema.json``) and validates a MINIMAL required-key
set fail-closed: any missing or non-numeric required key raises
``ConfigError`` rather than falling back to a substitute value. This is
deliberately NOT a whole-document ``jsonschema.validate()`` pass -- see
``data/README.md``'s "Known gap" note. ``REQUIRED_KEYS`` below is
exactly the set THIS module's own mapping needs to produce a safe boot
configuration, not an attempt to validate the rest of the document.

``wheel_control`` -> ``DiffDrive::Config`` mapping:

  - The per-robot JSON's ``wheel_control`` group maps FIELD-FOR-FIELD
    onto ``vendor/differential_drive.h``'s ``DiffDrive::Config`` Stage
    A/B/C authority fields -- see ``WHEEL_CONTROL_FIELDS`` below for the
    15-field rename table. No unit conversion, no scaling.
  - ``fullDutyVelocity`` (plant-gain calibration, "[counts/s] wheel rate
    at 100% duty; 0 = uncalibrated") has no direct JSON source; derived
    as ``mean(travel_calib_left, travel_calib_right) x
    _TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY`` (see that constant's comment
    for the multiplier's derivation and its single-bench-anchor caveat).
  - ``maxDuty`` (the authority-rail ceiling, NOT a calibration fact --
    ``vendor/differential_drive.h``: "authority rail (lambda scales to
    this); 0 = ALL modes refused") has no JSON source either. This
    module ships it as a fixed POLICY constant, ``DEFAULT_MAX_DUTY``:
    the real physical safety bounds are enforced elsewhere (lease
    ceiling, VM-hook watchdog, slew/deadband/reversal-dwell shaping in
    ``moddiffdrive.cpp``'s ``configure()``) -- see that constant's
    comment.

Native-binding scope note: ``diffdrive.configure()`` accepts only
``left_port``/``right_port``/``fwd_sign_left``/``fwd_sign_right``/
``max_duty``/``full_duty_velocity``/``cycle_period_ms`` -- no parameter
for the 15 ``wheel_control`` fields this module maps (a future
``diffdrive.set_wheel_control(...)`` binding is still open; see
``native/README.md``'s "Deliberately out of scope" note).
``diffdrive_configure_kwargs()`` targets the existing ``configure()``
surface; ``wheel_control_to_diffdrive_config()`` produces the full
15-field mapping for GET_CONFIG/SET_FIELD wire reporting and for
whichever ticket adds the native call.

``ConfigDispatch`` below backs v6's ``GET``/``SET`` verbs (sprint 007)
through its name-keyed ``get_field()``/``set_field()`` accessors
(ticket 005) -- the JSON-field-name <-> live-value store is the same
one either way, only the wire dispatch on top of it changed. v5's own
binary ``CONFIG``/``SET_FIELD``/``GET_CONFIG`` verb dispatch
(``handle_command()``/``_handle_set_field()``/``_handle_config()``/
``_handle_get_config()``/``build_cfg_reply()``) retired with the v6
cutover (sprint 007 ticket 006) -- their shared dependency on
``wire.encode_frame()``/index-keyed ``WHEEL_CONTROL_FIELDS`` payloads
is gone along with them, not left dead-code-in-place.

MicroPython-only imports are guarded so this module runs under CPython
too.
"""

try:
    import ujson as json
except ImportError:
    import json

__all__ = [
    "ConfigError",
    "REQUIRED_KEYS",
    "WHEEL_CONTROL_FIELDS",
    "DEFAULT_MAX_DUTY",
    "DEFAULT_CYCLE_PERIOD_MS",
    "parse_robot_config",
    "load_robot_config",
    "wheel_control_to_diffdrive_config",
    "diffdrive_configure_kwargs",
    "radio_channel",
    "ConfigDispatch",
]


class ConfigError(ValueError):
    """Raised by ``parse_robot_config()``/``load_robot_config()`` on any
    missing or invalid required key -- fail-closed (spec Sec 6/8,
    UC-011: "missing/invalid key -> motion refused")."""


# Minimal required-key set: what this module's own mapping (native
# configure() kwargs plus the wheel_control -> kernel Config mapping)
# needs for a safe boot configuration. Each entry is (group, field,
# kind); kind is "num" (int/float, not bool) or "str" (non-empty).
REQUIRED_KEYS = (
    ("identity", "robot_name", "str"),
    ("connection", "radio_channel", "num"),
    ("motors", "left_port", "num"),
    ("motors", "right_port", "num"),
    ("motors", "fwd_sign_left", "num"),
    ("motors", "fwd_sign_right", "num"),
    ("motors", "travel_calib_left", "num"),
    ("motors", "travel_calib_right", "num"),
    ("wheel_control", "v_min", "num"),
    ("wheel_control", "bias_max", "num"),
    ("wheel_control", "tau_adapt", "num"),
    ("wheel_control", "a_steady", "num"),
    ("wheel_control", "deficit_threshold", "num"),
    ("wheel_control", "deficit_window", "num"),
    ("wheel_control", "pid_kp", "num"),
    ("wheel_control", "pid_ki", "num"),
    ("wheel_control", "pid_i_max", "num"),
    ("wheel_control", "pid_kaff", "num"),
    ("wheel_control", "pid_max", "num"),
    ("wheel_control", "pos_err_max", "num"),
    ("wheel_control", "stall_speed", "num"),
    ("wheel_control", "stall_demand", "num"),
    ("wheel_control", "stall_window", "num"),
)

# wheel_control JSON field name -> DiffDrive::Config field name, in
# SET_FIELD/CFG wire field-index order (index 0..14). See
# vendor/differential_drive.h for the kernel-side field names.
WHEEL_CONTROL_FIELDS = (
    ("v_min", "vMin"),
    ("bias_max", "biasMax"),
    ("tau_adapt", "tauAdapt"),
    ("a_steady", "aSteady"),
    ("deficit_threshold", "deficitThreshold"),
    ("deficit_window", "deficitWindow"),
    ("pid_kp", "kp"),
    ("pid_ki", "ki"),
    ("pid_i_max", "iMax"),
    ("pid_kaff", "kaff"),
    ("pid_max", "pidMax"),
    ("pos_err_max", "posErrMax"),
    ("stall_speed", "stallSpeed"),
    ("stall_demand", "stallDemand"),
    ("stall_window", "stallWindow"),
)

# Authority-rail policy default, NOT a calibration fact (see docstring).
DEFAULT_MAX_DUTY = 25.0   # [%] kernel units are percent -- 1.0 here would
                          # collapse the rail below the 3% deadband floor.

# Matches DiffDrive::Config::cyclePeriod's default (vendor/
# differential_drive.h) and moddiffdrive.cpp's configure() default; no
# per-robot JSON field overrides this.
DEFAULT_CYCLE_PERIOD_MS = 24

# travel_calib -> fullDutyVelocity multiplier. Single bench anchor
# (tovez); see docs/bench-log-zetuv-2026-08-19.md Sec 55. Needs a
# proper multi-robot derivation; the old 10.0 was too small -- every
# velocity command railed at max_duty.
_TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY = 10845.0   # [counts/s per mm/deg]


def _get_group(doc, group):
    value = doc.get(group)
    if not isinstance(value, dict):
        raise ConfigError("missing or invalid group: %s" % (group,))
    return value


def parse_robot_config(text):
    """Parse ``text`` (str or bytes, JSON) into a plain dict and validate
    ``REQUIRED_KEYS`` fail-closed. Raises ``ConfigError`` on invalid JSON
    or any missing/wrong-type required key -- never returns a partially
    valid document."""
    try:
        doc = json.loads(text)
    except ValueError:
        raise ConfigError("invalid JSON")
    if not isinstance(doc, dict):
        raise ConfigError("robot config must be a JSON object")

    groups = {}
    for group, field, kind in REQUIRED_KEYS:
        if group not in groups:
            groups[group] = _get_group(doc, group)
        value = groups[group].get(field)
        if kind == "num":
            # bool is a subclass of int -- excluded explicitly, since a
            # JSON true/false is never a valid numeric config value.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError("missing or non-numeric key: %s.%s" % (group, field))
        else:
            if not isinstance(value, str) or not value:
                raise ConfigError("missing or empty key: %s.%s" % (group, field))

    return doc


def load_robot_config(path):
    """Read and parse the robot config JSON file at ``path`` (device
    filesystem path, e.g. ``"/tovez.json"``, or a host path for tests).
    Same fail-closed contract as ``parse_robot_config()`` -- a missing
    file raises ``ConfigError`` too (no silent fallback to defaults)."""
    try:
        with open(path, "r") as f:
            text = f.read()
    except OSError:
        raise ConfigError("robot config file not found: %s" % (path,))
    return parse_robot_config(text)


def wheel_control_to_diffdrive_config(robot_config):
    """Map ``robot_config`` (a parsed, validated document -- see
    ``load_robot_config()``) to a ``DiffDrive::Config``-shaped dict:
    the 15 ``wheel_control`` fields renamed per ``WHEEL_CONTROL_FIELDS``,
    plus ``fullDutyVelocity`` (``travel_calib`` x multiplier) and
    ``maxDuty``/``cyclePeriod`` (policy defaults -- see module
    docstring). Pure function, no I/O."""
    wheel_control = _get_group(robot_config, "wheel_control")
    motors = _get_group(robot_config, "motors")

    out = {}
    for json_field, kernel_field in WHEEL_CONTROL_FIELDS:
        out[kernel_field] = float(wheel_control[json_field])

    travel_calib_left = float(motors["travel_calib_left"])
    travel_calib_right = float(motors["travel_calib_right"])
    mean_travel_calib = (travel_calib_left + travel_calib_right) / 2.0
    out["fullDutyVelocity"] = mean_travel_calib * _TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY

    out["maxDuty"] = DEFAULT_MAX_DUTY
    out["cyclePeriod"] = DEFAULT_CYCLE_PERIOD_MS
    return out


def diffdrive_configure_kwargs(robot_config):
    """Build the kwargs dict for the native ``diffdrive.configure(
    left_port, right_port, fwd_sign_left, fwd_sign_right, max_duty,
    full_duty_velocity, cycle_period_ms)`` call (``native/
    moddiffdrive.cpp``) -- boot code does ``diffdrive.configure(
    **config.diffdrive_configure_kwargs(robot_config))``. Sources
    ``max_duty``/``full_duty_velocity``/``cycle_period_ms`` from
    ``wheel_control_to_diffdrive_config()`` so both call sites agree."""
    motors = _get_group(robot_config, "motors")
    mapped = wheel_control_to_diffdrive_config(robot_config)
    return {
        "left_port": int(motors["left_port"]),
        "right_port": int(motors["right_port"]),
        "fwd_sign_left": int(motors["fwd_sign_left"]),
        "fwd_sign_right": int(motors["fwd_sign_right"]),
        "max_duty": mapped["maxDuty"],
        "full_duty_velocity": mapped["fullDutyVelocity"],
        "cycle_period_ms": mapped["cyclePeriod"],
    }


def radio_channel(robot_config):
    """``connection.radio_channel`` as an int -- boot code passes this to
    ``radio_shim.RadioLink(channel=config.radio_channel(robot_config))``
    (``group`` is left at ``RadioLink``'s own fixed default)."""
    connection = _get_group(robot_config, "connection")
    return int(connection["radio_channel"])


class ConfigDispatch:
    """The live ``wheel_control`` name/value store -- backs v6's
    ``GET``/``SET`` verbs through the name-keyed ``get_field()``/
    ``set_field()`` accessors below (sprint 007 ticket 005), which
    ``src/hardware/protocol_adapter.py``'s ``ProtocolAdapter.on_get()``/
    ``on_set()`` delegate to exclusively.

    v5's binary ``CONFIG``/``SET_FIELD``/``GET_CONFIG`` verb dispatch
    (index-keyed payloads, a ``transports`` list of its own for
    broadcasting a COBS+CRC ``CFG`` reply frame) retired with the v6
    cutover (sprint 007 ticket 006) -- see module docstring. This class
    is now just the field store; it owns no transport of its own."""

    def __init__(self, robot_config):
        # Deliberately does NOT retain robot_config. Only wheel_control is
        # ever read (see current_wheel_control/get_field/set_field), and the
        # parsed document costs ~6.9 KB of a ~16.7 KB heap -- measured on
        # tovez. Holding it here kept it alive for the whole session.
        self._wheel_control = dict(robot_config.get("wheel_control") or {})

    def current_wheel_control(self):
        """The live (possibly ``set_field()``-patched) wheel_control
        dict, JSON field names."""
        return self._wheel_control

    def get_field(self, name):
        """Name-keyed read accessor (sprint 007 ticket 005: v6's
        ``GET``/``SET`` are by-name, not by-index). ``name`` is a JSON
        ``wheel_control`` field name (``WHEEL_CONTROL_FIELDS``'s left
        column, e.g. ``"v_min"``) -- returns its current live value, or
        ``None`` if ``name`` is not one of the 15 known fields."""
        for json_field, _kernel_field in WHEEL_CONTROL_FIELDS:
            if json_field == name:
                return self._wheel_control.get(json_field)
        return None

    def set_field(self, name, value):
        """Name-keyed write accessor, the ``SET`` counterpart to
        ``get_field()`` above (sprint 007 ticket 005). Applies ``value``
        to ``name`` live, RAM only -- no on-flash persistence
        (``protocol.md`` Sec 7: "the library stores none"). Returns
        ``True`` on success, ``False`` if ``name`` is not one of the 15
        known ``WHEEL_CONTROL_FIELDS`` names -- the caller
        (``ProtocolAdapter.on_set()``) maps a ``False`` onto the wire's
        ``Result.UNKNOWN``."""
        for json_field, _kernel_field in WHEEL_CONTROL_FIELDS:
            if json_field == name:
                self._wheel_control[json_field] = value
                return True
        return False
