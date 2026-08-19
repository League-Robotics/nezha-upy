"""msgs -- v5 wire verb registry.

GENERATED -- do not edit (hand-seeded pending gen_messages.py --emit-upy).

This is a STOPGAP. `docs/design/specification.md` Sec 10.3 (spec open
item 3) and this repo's sprint 001 architecture (`clasi/sprints/
001-python-first-firmware-image-m0-m6/sprint.md`, "Codec generated, not
hand-written") both say the real source of this file is radio-robot's
`src/scripts/gen_messages.py` growing a third emission mode
(`--emit-upy --out <path>`) over the SAME `src/protos/*.proto`
field-descriptor walk that already emits `src/firm/messages/*.h`
(C++, firmware) and `src/host/robot_radio/io/wire_commands.py`
(Python, host). That generator change is radio-robot-side and explicitly
out of scope for this sprint (sprint.md "Out of Scope"; this repo only
consumes its output) -- so this file is hand-seeded to match what the
generator's `--emit-upy` mode would walk for the ONE schema `src/wire.py`
and this ticket's golden-vector suite actually need: the closed verb set
and each verb's binary/cleartext framing.

Source of truth mirrored here, by hand, byte-for-byte:
`src/protos/commands.proto`'s `Verb` enum (the SAME schema
`wire_commands.py` is generated from -- see that file's own header for
why a verb's name and its `(binary)` option are the ONE piece of
generated metadata a wire-level consumer needs; direction, dispatch, and
a binary verb's data SHAPE are explicitly NOT this registry's concern,
per commands.proto's own scope note). Verified against radio-robot-elite
`src/host/robot_radio/io/wire_commands.py` (also generated from the same
enum) at seed time.

Deliberately NOT included here (also deferred to the real generator, for
the same out-of-scope-this-sprint reason): per-message protobuf field
tables for the 13 binary verbs' payload bodies (`Move`, `Config`,
`Stop`, `Wheels`, `Estop`, `Tlm`, `Ok`, `Err`, `GetConfig`, `Cfg`,
`SetField`, `GoTo`, `Calibrate` -- `src/protos/envelope.proto`,
`robot_config.proto`, `telemetry.proto`). `src/wire.py`'s COBS+CRC
framing is schema-agnostic -- it only ever needs a verb's ASCII name (for
the CRC's command scope) and whether that verb is binary or cleartext, so
this registry is already everything the M2 gate's wire-level round-trip
requires; a payload's own protobuf field layout is msgs.py's next
generation's job, once `--emit-upy` lands and there is a real reference
(protoc-compiled host pb2, or a device-side decode) to hand-verify a
field table against -- fabricating one now, with no such reference
available offline in this repo, would be a guess wearing a generated-file
header.
"""

__all__ = [
    "VerbEntry",
    "VERBS",
    "VERB_BY_NAME",
    "BINARY_VERBS",
    "CLEARTEXT_VERBS",
]


class VerbEntry:
    """One row of the closed v5 wire verb set.

    ``name``: str, the ASCII wire verb (e.g. ``"MOVE"``).
    ``binary``: bool -- True: COBS+CRC-framed binary ``<data>``; False:
    cleartext.

    A plain class, not ``typing.NamedTuple`` (host-only `typing` import;
    MicroPython does not ship it) -- construction is positional-compatible
    with a 2-tuple so call sites read the same either way."""

    def __init__(self, name, binary):
        self.name = name
        self.binary = binary

    def __repr__(self):
        return "VerbEntry(%r, %r)" % (self.name, self.binary)

    def __eq__(self, other):
        if not isinstance(other, VerbEntry):
            return NotImplemented
        return self.name == other.name and self.binary == other.binary


# The closed v5 wire verb set -- src/protos/commands.proto's Verb enum,
# VERB_UNSPECIFIED (proto3 zero value, never a real wire verb) excluded,
# in ascending enum-value order.
VERBS = (
    VerbEntry("HELLO", False),
    VerbEntry("PING", False),
    VerbEntry("ID", False),
    VerbEntry("VER", False),
    VerbEntry("DEVICE", False),
    VerbEntry("PONG", False),
    VerbEntry("MOVE", True),
    VerbEntry("CONFIG", True),
    VerbEntry("STOP", True),
    VerbEntry("TLM", True),
    VerbEntry("OK", True),
    VerbEntry("ERR", True),
    VerbEntry("WHEELS", True),
    VerbEntry("ESTOP", True),
    VerbEntry("READY", False),
    VerbEntry("STATUS", False),
    VerbEntry("HELP", False),
    VerbEntry("DBG", False),
    VerbEntry("GET_CONFIG", True),
    VerbEntry("CFG", True),
    VerbEntry("SET_FIELD", True),
    VerbEntry("SEED", False),
    VerbEntry("POSE", False),
    VerbEntry("GO_TO", True),
    VerbEntry("CALIBRATE", True),
)

VERB_BY_NAME = dict((v.name, v) for v in VERBS)

BINARY_VERBS = frozenset(v.name for v in VERBS if v.binary)
CLEARTEXT_VERBS = frozenset(v.name for v in VERBS if not v.binary)
