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

CONFIG/SET_FIELD/GET_CONFIG wire wiring: see ``ConfigDispatch`` below.
``msgs.py`` has no per-verb protobuf field tables yet, so this module
hand-decodes a small, documented payload shape for exactly these three
verbs -- group id convention borrowed from radio-robot-elite's
``ConfigGroupTarget`` enum (``src/protos/robot_config.proto``:
``WHEEL_CONTROL = 4``); only the WHEEL_CONTROL group is wired.

MicroPython-only imports are guarded so this module runs under CPython
too.
"""

try:
    import ujson as json
except ImportError:
    import json

import struct

from core import wire

__all__ = [
    "ConfigError",
    "REQUIRED_KEYS",
    "WHEEL_CONTROL_FIELDS",
    "DEFAULT_MAX_DUTY",
    "DEFAULT_CYCLE_PERIOD_MS",
    "CONFIG_GROUP_WHEEL_CONTROL",
    "ERR_OK",
    "ERR_UNIMPLEMENTED",
    "ERR_MALFORMED",
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

# ConfigGroupTarget group id this module wires -- borrowed from
# radio-robot-elite's robot_config.proto enum (WHEEL_CONTROL = 4).
CONFIG_GROUP_WHEEL_CONTROL = 4

# Ack err codes this dispatch returns (msgs.py has no generated
# error-code table yet).
ERR_OK = 0
ERR_UNIMPLEMENTED = 1  # a config group other than WHEEL_CONTROL
ERR_MALFORMED = 2  # wrong payload length / out-of-range field index


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
    """Backs ``src/core/comms.py``'s firmware-layer dispatch interface
    (``handle_command(verb_name, payload, now) -> (corr_id, err_code) |
    None``) for the CONFIG/SET_FIELD/GET_CONFIG verbs.

    Payload shapes (hand-decoded convention -- see module docstring for
    why no generated field table exists to decode against instead):

      SET_FIELD: corr_id:u8, group_id:u8, field_index:u8, value:f32-LE
                 (7 bytes). Applies ONE wheel_control field live (RAM
                 only -- spec Sec 8: "No on-flash tuning store").
      CONFIG:    corr_id:u8, group_id:u8, value:f32-LE x 15 (62 bytes).
                 Bulk-applies the WHOLE wheel_control group at once, in
                 ``WHEEL_CONTROL_FIELDS`` order.
      GET_CONFIG: corr_id:u8, group_id:u8 (2 bytes). See below.

    Only ``CONFIG_GROUP_WHEEL_CONTROL`` (4) is wired -- any other group
    id acks ``ERR_UNIMPLEMENTED`` (the native call needed to push other
    groups into the kernel does not exist yet either).

    GET_CONFIG note: ``comms.py``'s ``handle_command`` interface gets no
    requesting transport and offers no reply-frame channel beyond the
    ack ring (``(corr_id, err_code)``). This dispatch therefore keeps
    its own ``transports`` list (``add_transport()``, independent of
    ``comms.Comms``'s own registration) and, on a valid GET_CONFIG,
    broadcasts a ``CFG`` reply frame (``build_cfg_reply()`` below,
    COBS+CRC via ``wire.encode_frame()``) to every registered transport,
    in addition to acking via the ring -- mirroring the
    broadcast-to-all-transports shape ``Comms.send_banner()``/
    telemetry's own frame emission already use. A caller that never
    calls ``add_transport()`` still gets a correct ack, just no CFG
    data frame.
    """

    def __init__(self, robot_config, transports=None):
        self._config = robot_config
        self._wheel_control = dict(robot_config.get("wheel_control") or {})
        self._transports = list(transports) if transports else []

    def add_transport(self, transport):
        self._transports.append(transport)

    def current_wheel_control(self):
        """The live (possibly SET_FIELD/CONFIG-patched) wheel_control
        dict, JSON field names -- what ``build_cfg_reply()`` reads from."""
        return self._wheel_control

    def build_cfg_reply(self, group_id):
        """Pure function: pack the given group's current field values
        into a COBS+CRC-framed ``CFG`` wire frame (group_id:u8 then 15x
        f32-LE), or ``None`` for an unwired group_id."""
        if group_id != CONFIG_GROUP_WHEEL_CONTROL:
            return None
        body = bytearray()
        body.append(group_id & 0xFF)
        for json_field, _kernel_field in WHEEL_CONTROL_FIELDS:
            body.extend(_pack_f32_le(float(self._wheel_control[json_field])))
        return wire.encode_frame(bytes(body), command=b"CFG")

    def handle_command(self, verb_name, payload, now):
        if verb_name == "SET_FIELD":
            return self._handle_set_field(payload)
        if verb_name == "CONFIG":
            return self._handle_config(payload)
        if verb_name == "GET_CONFIG":
            return self._handle_get_config(payload)
        return None

    def _handle_set_field(self, payload):
        if len(payload) != 7:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        group_id = payload[1]
        field_index = payload[2]
        if group_id != CONFIG_GROUP_WHEEL_CONTROL:
            return (corr_id, ERR_UNIMPLEMENTED)
        if field_index >= len(WHEEL_CONTROL_FIELDS):
            return (corr_id, ERR_MALFORMED)
        value = _unpack_f32_le(payload[3:7])
        json_field, _kernel_field = WHEEL_CONTROL_FIELDS[field_index]
        self._wheel_control[json_field] = value
        return (corr_id, ERR_OK)

    def _handle_config(self, payload):
        expected_len = 2 + 4 * len(WHEEL_CONTROL_FIELDS)
        if len(payload) != expected_len:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        group_id = payload[1]
        if group_id != CONFIG_GROUP_WHEEL_CONTROL:
            return (corr_id, ERR_UNIMPLEMENTED)
        offset = 2
        values = []
        for _ in WHEEL_CONTROL_FIELDS:
            values.append(_unpack_f32_le(payload[offset:offset + 4]))
            offset += 4
        for (json_field, _kernel_field), value in zip(WHEEL_CONTROL_FIELDS, values):
            self._wheel_control[json_field] = value
        return (corr_id, ERR_OK)

    def _handle_get_config(self, payload):
        if len(payload) != 2:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        group_id = payload[1]
        frame = self.build_cfg_reply(group_id)
        if frame is None:
            return (corr_id, ERR_UNIMPLEMENTED)
        for transport in self._transports:
            transport.send(frame)
        return (corr_id, ERR_OK)


def _corr_id_or_none(payload):
    """Best-effort ack target for a malformed-length payload -- the
    corr_id byte may still be present. ``None`` only if even that byte
    is missing (matches comms.py's "None = no ack possible" convention)."""
    if payload:
        return payload[0]
    return None


def _pack_f32_le(value):
    """Pack ``value`` as IEEE-754 binary32, little-endian. ``struct``
    ships on both CPython and MicroPython, unlike ``ujson``/
    ``micropython`` elsewhere in this port, so no import guard needed."""
    return struct.pack("<f", value)


def _unpack_f32_le(data):
    return struct.unpack("<f", bytes(data))[0]
