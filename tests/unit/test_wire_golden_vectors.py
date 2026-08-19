"""M2 gate: `src/wire.py` against `tests/fixtures/wire_golden_vectors.txt`.

See `docs/design/specification.md` Sec 4/6 (v5 wire contract, M2 gate) and
`clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/
003-wire-codec-msgs-py-golden-vector-suite-m2.md` for the acceptance
criteria this file encodes:

  - all 8 golden vectors decode AND re-encode byte-exact;
  - COBS keyed 0x0A and CRC-16/CCITT-FALSE (over `command + ':' + payload`,
    CRC-then-COBS) match the fixture exactly;
  - encode<->decode round-trip for every binary verb.

Round-trip scope note (ticket 003's own escape hatch, exercised here):
the ticket allows narrowing "against host pb2" to "against the fixture's
own recorded bytes" when a host pb2 cross-check is not available in this
environment, as long as the narrower scope is stated explicitly rather
than silently skipped. It is not available here: `google.protobuf` is not
installed in this repo's Python environment (confirmed at ticket-003
authoring time -- `python3 -c "import google.protobuf"` raises
`ModuleNotFoundError`), and reaching into radio-robot-elite's installed
package to get it would make this repo's own test suite depend on a
sibling repo's environment, breaking the "offline, self-contained under
CPython" discipline `docs/design/specification.md` Sec 9 requires of
every M0-M6 gate. `src/wire.py` is schema-agnostic by design (a payload is
opaque bytes to it -- see its own module docstring), so
`test_round_trip_every_binary_verb` below round-trips real bytes (the
fixture's own `sweep_0x00_0xff` payload, chosen because it exercises
every byte value 0x00-0xff) through `encode_frame()`/`decode_frame()` for
every verb `src/msgs.py` declares binary, without needing an actual
protobuf-encoded message body for any of them.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "wire_golden_vectors.txt"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import msgs  # noqa: E402  (path must be set up first)
import wire  # noqa: E402


class GoldenVector:
    """One parsed row of `wire_golden_vectors.txt`."""

    def __init__(self, name, delimiter, command, payload, expected_wire, source):
        self.name = name
        self.delimiter = delimiter
        self.command = command
        self.payload = payload
        self.expected_wire = expected_wire
        self.source = source


def _load_golden_vectors():
    """Parse `tests/fixtures/wire_golden_vectors.txt` -- pipe-delimited,
    '#'-prefixed and blank lines ignored, per the fixture's own header
    comment (columns: name | delimiter_hex | command | payload_hex |
    expected_wire_hex | source). Do NOT hand-copy vector values out of
    this file elsewhere -- read the fixture directly, every time, so a
    new row is picked up automatically (the fixture's own header's
    explicit warning)."""
    rows = []
    header_seen = False
    with open(FIXTURE_PATH, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not header_seen:
                # First non-comment, non-blank line is the column header.
                header_seen = True
                continue
            parts = line.split("|")
            assert len(parts) == 6, "malformed fixture row: %r" % (line,)
            name, delimiter_hex, command, payload_hex, expected_wire_hex, source = parts
            rows.append(
                GoldenVector(
                    name=name,
                    delimiter=int(delimiter_hex, 16),
                    command=command.encode("ascii"),
                    payload=bytes.fromhex(payload_hex) if payload_hex else b"",
                    expected_wire=bytes.fromhex(expected_wire_hex),
                    source=source,
                )
            )
    return rows


GOLDEN_VECTORS = _load_golden_vectors()


def test_fixture_has_all_eight_vectors():
    """Sanity floor: the fixture this suite is gated against is the 8
    cross-language vectors PLAN.md/specification.md Sec 4 name -- if this
    ever reads a different count, something upstream of this test (the
    fixture itself, or the parser above) changed and needs eyes before
    trusting any of the parametrized results below."""
    assert len(GOLDEN_VECTORS) == 8


def test_crc16_ccitt_false_known_answer_vector():
    """CRC RevEng catalogue known-answer vector, pinned in `wire.py`'s own
    module docstring: crc16_ccitt_false(b"123456789") == 0x29B1. Exercised
    as an exact-value test, not merely "some CRC changed"."""
    assert wire.crc16_ccitt_false(b"123456789") == 0x29B1


@pytest.mark.parametrize(
    "vector", GOLDEN_VECTORS, ids=[v.name for v in GOLDEN_VECTORS]
)
def test_golden_vector_decode(vector):
    """Decode: COBS-decode `expected_wire_hex` (delimiter from the row),
    split off the trailing little-endian CRC-16, and check both the CRC
    and the payload against the fixture's own composition formula
    (its header comment):

        crc      = crc16_ccitt_false(command ? command + ':' + payload : payload)
        combined = payload || crc16_le(crc)
        expected_wire = cobsEncode(combined, delimiter)
    """
    combined = wire.cobs_decode(vector.expected_wire, delimiter=vector.delimiter)
    assert len(combined) >= 2
    payload, crc_bytes = combined[:-2], combined[-2:]
    received_crc = crc_bytes[0] | (crc_bytes[1] << 8)

    if vector.command:
        expected_crc = wire.crc16_ccitt_false(vector.command + b":" + vector.payload)
    else:
        expected_crc = wire.crc16_ccitt_false(vector.payload)

    assert bytes(payload) == vector.payload
    assert received_crc == expected_crc


@pytest.mark.parametrize(
    "vector", GOLDEN_VECTORS, ids=[v.name for v in GOLDEN_VECTORS]
)
def test_golden_vector_encode(vector):
    """Re-encode: COBS-encode(payload || crc16_le(crc), delimiter) must
    reproduce `expected_wire_hex` byte-exact -- the fixture's own
    composition formula run forward instead of backward."""
    if vector.command:
        crc = wire.crc16_ccitt_false(vector.command + b":" + vector.payload)
    else:
        crc = wire.crc16_ccitt_false(vector.payload)
    combined = vector.payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))
    actual_wire = wire.cobs_encode(combined, delimiter=vector.delimiter)
    assert actual_wire == vector.expected_wire


@pytest.mark.parametrize(
    "vector", GOLDEN_VECTORS, ids=[v.name for v in GOLDEN_VECTORS]
)
def test_golden_vector_frame_api_round_trip(vector):
    """The same 8 vectors again, this time entirely through the PRODUCTION
    `encode_frame()`/`decode_frame()` API (not the lower-level primitives
    the two tests above use) -- every fixture row uses delimiter 0x0A,
    which is the only delimiter `encode_frame()`/`decode_frame()` support
    (protocol v5 hardcodes it), so this covers all 8."""
    assert vector.delimiter == 0x0A, (
        "encode_frame()/decode_frame() hardcode delimiter 0x0A; a fixture "
        "row with a different delimiter needs the lower-level cobs_encode/"
        "cobs_decode tests above instead, not this one"
    )
    encoded = wire.encode_frame(vector.payload, command=vector.command)
    assert encoded == vector.expected_wire

    decoded = wire.decode_frame(vector.expected_wire, command=vector.command)
    assert decoded == vector.payload


def test_decode_frame_rejects_mismatched_command():
    """A frame encoded under one command's CRC scope must not decode
    under another -- `decode_frame()`'s documented "never raises, returns
    None on any corruption" contract, exercised for the specific case the
    CRC's command-scope extension exists to catch (Sec 4: "CRC-16/
    CCITT-FALSE over command+':'+payload")."""
    move_vector = next(v for v in GOLDEN_VECTORS if v.name == "crc_scope_move")
    assert wire.decode_frame(move_vector.expected_wire, command=b"STOP") is None


def test_decode_frame_rejects_truncated_frame():
    """A frame with the trailing CRC byte chopped off must fail closed
    (`None`), never raise and never return a payload that never had a
    valid CRC behind it."""
    move_vector = next(v for v in GOLDEN_VECTORS if v.name == "crc_scope_move")
    truncated = move_vector.expected_wire[:-1]
    assert wire.decode_frame(truncated, command=move_vector.command) is None


def test_round_trip_every_binary_verb():
    """Encode<->decode round-trip for every binary verb `src/msgs.py`
    declares (module docstring above explains why this is scoped to
    `src/wire.py`'s own opaque-bytes framing rather than real
    protobuf-encoded message bodies, and why: no host pb2 cross-check is
    available in this environment).

    Payload: the fixture's own `sweep_0x00_0xff` vector's payload (all 256
    byte values, including 0x00 and 0x0A -- the two bytes COBS and the
    frame delimiter care about) -- reusing a fixture-recorded byte string
    rather than fabricating a new one, so this exercises the same
    adversarial input the golden-vector suite already trusts, once per
    binary verb's own CRC scope.
    """
    sweep_vector = next(v for v in GOLDEN_VECTORS if v.name == "sweep_0x00_0xff")
    payload = sweep_vector.payload
    assert len(payload) == 256

    binary_verbs = sorted(msgs.BINARY_VERBS)
    assert len(binary_verbs) == 13, (
        "expected 13 binary verbs per src/protos/commands.proto's Verb "
        "enum -- if this changed, msgs.py's VERBS table changed too and "
        "this count should be updated deliberately, not silently"
    )

    for verb_name in binary_verbs:
        command = verb_name.encode("ascii")
        frame = wire.encode_frame(payload, command=command)
        # 0x0A-free by construction (encode_frame()'s own contract).
        assert 0x0A not in frame
        decoded = wire.decode_frame(frame, command=command)
        assert decoded == payload, "round-trip failed for binary verb %s" % verb_name


def test_binary_and_cleartext_verb_sets_partition_all_verbs():
    """Every declared verb is exactly one of binary or cleartext, and the
    two sets don't overlap -- msgs.py's own internal consistency, cheap to
    check and load-bearing for `test_round_trip_every_binary_verb` above
    (which trusts `BINARY_VERBS` to enumerate the right set)."""
    all_names = set(v.name for v in msgs.VERBS)
    assert msgs.BINARY_VERBS | msgs.CLEARTEXT_VERBS == all_names
    assert msgs.BINARY_VERBS & msgs.CLEARTEXT_VERBS == set()
    assert len(msgs.VERBS) == 25
