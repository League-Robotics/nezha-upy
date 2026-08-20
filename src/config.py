"""config -- per-robot JSON loader, fail-closed key validation, and the
``wheel_control`` -> ``DiffDrive::Config`` mapping (PLAN.md M5 /
``docs/design/specification.md`` Sec 6/8, UC-011).

Loads one robot's JSON (``data/<robot>.json``, copied from
radio-robot-elite by ticket 002, schema in
``data/robot_config.schema.json``) and validates a MINIMAL required-key
set fail-closed: any missing or non-numeric required key raises
``ConfigError`` rather than falling back to a substitute value. This is
deliberately NOT a whole-document ``jsonschema.validate()`` pass --
``data/README.md``'s own "Known gap" section records that the per-robot
JSON does not yet validate against the full schema (extra groups/notes
the schema's ``additionalProperties: false`` rejects), and ticket 002's
acceptance criteria explicitly allow a hand-rolled required-key check as
the alternative. ``REQUIRED_KEYS`` below is exactly the set THIS
module's own mapping needs to produce a safe boot configuration -- not
an attempt to validate the rest of the (much larger) per-robot document.

``wheel_control`` -> ``DiffDrive::Config`` mapping (PLAN.md/spec/
usecases.md all cite this verbatim: "wheel_control -> DiffDrive::Config
via travel_calib x10"):

  - The per-robot JSON's ``wheel_control`` group maps FIELD-FOR-FIELD
    onto ``vendor/differential_drive.h``'s ``DiffDrive::Config`` Stage
    A/B/C authority fields -- verified directly against that header,
    field by field: ``v_min``/``bias_max``/``tau_adapt``/``a_steady``/
    ``deficit_threshold``/``deficit_window``/``pid_kp``/``pid_ki``/
    ``pid_i_max``/``pid_kaff``/``pid_max``/``pos_err_max``/
    ``stall_speed``/``stall_demand``/``stall_window`` rename 1:1 onto
    ``vMin``/``biasMax``/``tauAdapt``/``aSteady``/``deficitThreshold``/
    ``deficitWindow``/``kp``/``ki``/``iMax``/``kaff``/``pidMax``/
    ``posErrMax``/``stallSpeed``/``stallDemand``/``stallWindow`` -- 15
    fields, no unit conversion, no scaling.
  - ``fullDutyVelocity`` (``DiffDrive::Config``'s plant-gain calibration
    field, "[counts/s] wheel rate at 100% duty; 0 = uncalibrated") has
    NO direct source in ``wheel_control`` -- the one piece of arithmetic
    every source document names is ``travel_calib x10``. This module
    implements that literally: ``fullDutyVelocity = mean(travel_calib_
    left, travel_calib_right) x 10`` (``motors`` group; averaged because
    the kernel's ``fullDutyVelocity`` is ONE scalar, not a left/right
    pair -- both robots copied into ``data/`` today carry equal left/
    right values, so the average recovers the single figure exactly).
    No document in this repo elaborates the multiplier's derivation
    further than "x10" -- flagged here rather than silently
    re-deriving a different constant.
  - ``maxDuty`` (the authority-rail ceiling, NOT a calibration fact --
    ``vendor/differential_drive.h``: "authority rail (lambda scales to
    this); 0 = ALL modes refused") has no JSON source anywhere in the
    schema either. This module ships it as a fixed POLICY constant,
    ``DEFAULT_MAX_DUTY`` (1.0 -- full authority): the real physical
    safety bounds are already enforced elsewhere and do not go through
    this field (the binding's 5000 ms lease ceiling, the VM-hook
    watchdog, and the fixed slew/deadband/reversal-dwell shaping
    ``moddiffdrive.cpp``'s own ``configure()`` already substitutes) --
    see this module's own docstring note next to ``DEFAULT_MAX_DUTY``.

Native-binding scope note (flagged, not silently under-delivered):
``native/README.md``'s own "Deliberately out of scope for this ticket"
section (ticket 004) names exactly this gap: "Full per-robot config
mapping (DiffDrive::Config's remaining ~15 fields ...) -- ticket 007."
``diffdrive.configure()`` (ticket 004's binding) accepts only
``left_port``/``right_port``/``fwd_sign_left``/``fwd_sign_right``/
``max_duty``/``full_duty_velocity``/``cycle_period_ms`` -- it has NO
parameter for the 15 ``wheel_control`` fields this module maps. Wiring
a new native call (e.g. a ``diffdrive.set_wheel_control(...)`` binding
over the kernel's already-safe-to-call-post-construction
``setConfig()``) is real, buildable, low-risk work -- but it is a
``native/`` C++ change needing its own qstr/glue wiring and a verified
``--clean`` rebuild, and is deliberately NOT done in this pass: this
ticket's own acceptance criteria only ask for the MAPPING to be
unit-tested against known input/output pairs (``tests/test_config.py``),
not for a new native call. ``diffdrive_configure_kwargs()`` below
targets the REAL, already-built ``configure()`` surface;
``wheel_control_to_diffdrive_config()`` produces the full 15-field
mapping for GET_CONFIG/SET_FIELD wire reporting and for whichever
ticket adds the native call. Recorded here, not silently dropped, so a
future ticket has a concrete pointer instead of rediscovering the gap.

CONFIG/SET_FIELD/GET_CONFIG wire wiring: see ``ConfigDispatch`` below.
``msgs.py`` has no per-verb protobuf field tables yet (its own
docstring), so this module hand-decodes a small, documented payload
shape for exactly these three verbs -- group id conventions borrowed
from radio-robot-elite's current ``ConfigGroupTarget`` enum
(``src/protos/robot_config.proto``: ``WHEEL_CONTROL = 4``) since that
enum is a stable, non-guessed source even though this port only wires
the WHEEL_CONTROL group's fields this ticket.

MicroPython-only modules are import-guarded so this module imports and
runs unmodified under CPython (this ticket's own offline gate).
"""

try:
    import ujson as json
except ImportError:
    import json

import struct

import wire

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
    missing or invalid required key -- fail-closed per spec Sec 6/8 and
    UC-011's own error flow ("missing/invalid key -> motion refused")."""


# Minimal required-key set: exactly what THIS module's own mapping (the
# native `configure()` call-arg kwargs plus the wheel_control -> kernel
# Config mapping) needs to produce a safe boot configuration. Each entry
# is (group, field, kind) where kind is "num" (int or float, not bool)
# or "str" (non-empty string).
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

# wheel_control JSON field name -> DiffDrive::Config field name, in the
# group's own SET_FIELD/CFG wire field-index order (index 0..14) -- see
# this module's docstring for the field-by-field verification against
# vendor/differential_drive.h.
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

# Authority-rail policy default -- see this module's own docstring
# ("maxDuty ... NOT a calibration fact").
DEFAULT_MAX_DUTY = 25.0   # [%] kernel units are PERCENT (bench-established
                          # sprint 002; the old 1.0 was a fraction-era value
                          # that collapsed the rail below the 3% deadband floor)

# Matches DiffDrive::Config::cyclePeriod's own default (vendor/
# differential_drive.h) and moddiffdrive.cpp's configure() default
# (cycle_period_ms=24) -- no per-robot JSON field overrides this.
DEFAULT_CYCLE_PERIOD_MS = 24

# The "x10" travel_calib -> fullDutyVelocity multiplier -- see this
# module's docstring; no source in this repo elaborates it further.
_TRAVEL_CALIB_TO_FULL_DUTY_VELOCITY = 10845.0   # [counts/s per mm/deg]
# Derived from ONE bench anchor (tovez, 2026-08-19): travel_calib 0.7837
# -> measured ~8500 counts/s at 100% duty (duty->speed extrapolation,
# docs/bench-log-zetuv-2026-08-19.md Sec 55). Single data point -- needs a
# proper multi-robot derivation ticket; the old 10.0 produced a
# fullDutyVelocity so small every velocity command railed at max_duty.

# ConfigGroupTarget group id this module wires (see docstring) --
# borrowed from radio-robot-elite's current robot_config.proto enum
# (WHEEL_CONTROL = 4) as a stable, non-guessed numbering convention.
CONFIG_GROUP_WHEEL_CONTROL = 4

# Ack err codes this dispatch returns (small, local convention -- msgs.py
# has no generated error-code table yet; kept to the two cases this
# module's own dispatch can actually distinguish).
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
            # bool is a subclass of int in Python -- explicitly excluded,
            # a JSON `true`/`false` is never a valid numeric config value.
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
    plus ``fullDutyVelocity`` (``travel_calib`` x10) and ``maxDuty``/
    ``cyclePeriod`` (policy defaults -- see this module's docstring).
    Pure function, no I/O -- this is what ``tests/test_config.py``'s
    "known input/output pairs" acceptance criterion exercises directly."""
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
    """Build the kwargs dict for the REAL, already-built native
    ``diffdrive.configure(left_port, right_port, fwd_sign_left,
    fwd_sign_right, max_duty, full_duty_velocity, cycle_period_ms)``
    call (``native/moddiffdrive.cpp``, ticket 004) -- boot code does
    ``diffdrive.configure(**config.diffdrive_configure_kwargs(robot_config))``.
    Sources ``max_duty``/``full_duty_velocity``/``cycle_period_ms`` from
    ``wheel_control_to_diffdrive_config()`` so both call sites agree on
    the same three shared fields."""
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
    (``group`` is left at ``RadioLink``'s own fixed default, already
    matching the relay -- see ``src/radio_shim.py``)."""
    connection = _get_group(robot_config, "connection")
    return int(connection["radio_channel"])


class ConfigDispatch:
    """Backs ``src/comms.py``'s firmware-layer dispatch interface
    (``handle_command(verb_name, payload, now) -> (corr_id, err_code) |
    None``) for the CONFIG/SET_FIELD/GET_CONFIG verbs -- see this
    module's docstring for the payload shapes and the GET_CONFIG
    limitation note below.

    Payload shapes (this ticket's own hand-decoded, documented
    convention -- see module docstring for why no generated field table
    exists yet to decode against instead):

      SET_FIELD: corr_id:u8, group_id:u8, field_index:u8, value:f32-LE
                 (7 bytes). Applies ONE wheel_control field live (RAM
                 only -- spec Sec 8: "No on-flash tuning store").
      CONFIG:    corr_id:u8, group_id:u8, value:f32-LE x 15 (62 bytes).
                 Bulk-applies the WHOLE wheel_control group at once, in
                 ``WHEEL_CONTROL_FIELDS`` order.
      GET_CONFIG: corr_id:u8, group_id:u8 (2 bytes). See below.

    Only ``CONFIG_GROUP_WHEEL_CONTROL`` (4) is wired this ticket -- any
    other group id acks ``ERR_UNIMPLEMENTED`` (matches this module's own
    docstring: the native call needed to push these fields into the
    kernel does not exist yet either, so wiring more groups than the one
    this ticket's mapping actually targets would be dead plumbing).

    GET_CONFIG limitation (flagged, not silently dropped): ``comms.py``'s
    dispatch interface (``handle_command``) is NOT given the requesting
    transport, and offers no reply-frame channel beyond the ack ring
    (``(corr_id, err_code)``) -- by design, per that module's own
    docstring, since a full ``CommandEnvelope`` decode was explicitly
    ticket 007's job. This dispatch therefore ALSO accepts its own
    ``transports`` list (``add_transport()``, independent of
    ``comms.Comms``'s own registration) and, on a valid GET_CONFIG,
    BROADCASTS a ``CFG`` reply frame (``build_cfg_reply()`` below,
    COBS+CRC framed via ``wire.encode_frame()``) to every transport
    registered here, in addition to acking via the ring -- mirroring the
    broadcast-to-all-transports shape ``Comms.send_banner()``/telemetry's
    own primary-frame emission already use, and requiring zero changes
    to ``comms.py`` (a ticket 005 module, out of this ticket's file
    scope). A caller that never calls ``add_transport()`` here still
    gets a correct ack; it just does not receive the CFG data frame --
    documented, not a crash.
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
    """A malformed-length payload may still carry a recoverable corr_id
    in its first byte -- best-effort ack target, ``None`` only if even
    that byte is missing (matches comms.py's own "None = no ack possible"
    convention)."""
    if payload:
        return payload[0]
    return None


def _pack_f32_le(value):
    """Pack ``value`` as IEEE-754 binary32, little-endian. ``struct``
    ships on both CPython and MicroPython (microbit's port included), so
    this needs no import guard -- unlike ``ujson``/``micropython``
    elsewhere in this port, which do not exist on both sides."""
    return struct.pack("<f", value)


def _unpack_f32_le(data):
    return struct.unpack("<f", bytes(data))[0]
