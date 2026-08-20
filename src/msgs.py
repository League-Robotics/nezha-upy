"""msgs -- v5 wire verb registry.

GENERATED -- do not edit (hand-seeded pending gen_messages.py's
``--emit-upy`` mode -- spec Sec 10.3 open item 3).

Source of truth, mirrored here by hand, byte-for-byte:
``src/protos/commands.proto``'s ``Verb`` enum (the same schema
``wire_commands.py`` is generated from). Only a verb's name and its
``(binary)`` option are recorded here -- direction, dispatch, and a
binary verb's payload SHAPE are explicitly NOT this registry's concern
(commands.proto's own scope note). Verified against radio-robot-elite's
generated ``wire_commands.py`` at seed time.

Deliberately NOT included: per-message protobuf field tables for the
13 binary verbs' payload bodies. ``src/wire.py``'s COBS+CRC framing is
schema-agnostic -- it only needs a verb's ASCII name and whether it's
binary or cleartext, so this registry is already everything wire-level
framing requires; a payload's own field layout needs a real generated
reference (protoc-compiled pb2, or a device-side decode) to verify
against, which is not available offline in this repo yet.
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

    A plain class, not ``typing.NamedTuple`` (MicroPython has no
    ``typing``) -- construction stays positional-compatible with a
    2-tuple."""

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
