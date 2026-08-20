"""wire -- v5 protocol wire codec: COBS + CRC-16/CCITT-FALSE framing.

Ported nearly verbatim from radio-robot's
``src/host/robot_radio/io/wire_codec.py`` (same algorithms, same
constants, byte-for-byte compatible output -- see PLAN.md M2 /
``docs/design/specification.md`` Sec 4).

Protocol v5: every wire packet, text or binary, in both directions, is
exactly one line -- ``<COMMAND>[':' <data>]'\\n'``. A binary frame's
``<data>`` is CRC-then-COBS composed (append the little-endian CRC-16 to
the schema payload, THEN COBS-encode the combined bytes), the CRC scoped
over ``COMMAND ':' payload`` (not payload alone), and delimited on the wire
by a single ``0x0A`` (``'\\n'``) byte -- COBS is keyed on 0x0A, not 0x00
(see ``cobs_encode()``'s own docstring for why this makes the terminator
genuinely unconditional).

Every primitive here is a pure function operating on ``bytes`` in,
``bytes`` out (or ``None``/an exception on malformed input) -- no I/O, no
threading, no protobuf-schema knowledge (that lives in ``msgs.py``).
``ByteStreamDemuxer`` is the one stateful piece: it accumulates raw bytes
from a byte-oriented transport and yields complete ``'\\n'``-terminated
lines.

CRC-16/CCITT-FALSE parameters (pinned -- must match byte-for-byte, no
negotiation, no version byte):
    poly   = 0x1021
    init   = 0xFFFF
    refin  = False (no input reflection -- processed MSB-first)
    refout = False (no output reflection)
    xorout = 0x0000 (no final XOR)
Known-answer vector (CRC RevEng catalogue):
``crc16_ccitt_false(b"123456789") == 0x29B1``.

LANDMINE: no ``from __future__ import annotations``, no PEP 604
(``X | None``), and no generic-subscript (``list[bytes]``) type hints --
this file must import and run unmodified under both CPython (host
tests) and MicroPython (on-device), which does not support that
syntax. Every function's parameter/return shape is documented in its
docstring instead.
"""

__all__ = [
    "WireFrameError",
    "crc16_ccitt_false",
    "crc16_init",
    "crc16_update",
    "cobs_encode",
    "cobs_decode",
    "cobs_encoded_max_length",
    "encode_frame",
    "decode_frame",
    "ByteStreamDemuxer",
    "FRAME_DELIMITER",
]

# Every transport appends this after every wire line (protocol v5: '\n').
# COBS is keyed on 0x0A (see cobs_encode()), so a binary line's own
# bytes never contain a literal 0x0A -- this terminator is unconditional.
FRAME_DELIMITER = b"\n"

# COBS block cap: a block of up to this many non-zero bytes gets one
# code byte (0xFF marks a full block that hit the cap before a zero).
_COBS_MAX_BLOCK = 254

# CRC-16/CCITT-FALSE parameters -- see this module's own header comment.
_CRC16_POLY = 0x1021
_CRC16_INIT = 0xFFFF


class WireFrameError(ValueError):
    """Raised by ``cobs_encode()``/``cobs_decode()`` on malformed input.
    ``decode_frame()`` catches this internally and returns ``None``
    instead of raising; callers using the lower-level
    ``cobs_encode()``/``cobs_decode()`` primitives directly still see
    it raised."""


def crc16_init():
    """Initial CRC-16/CCITT-FALSE register value (int) -- the starting
    point for an incremental ``crc16_update()`` chain, so a caller
    composing a CRC over multiple byte ranges (``encode_frame()``/
    ``decode_frame()``) never needs to concatenate them first."""
    return _CRC16_INIT


def crc16_update(crc, data):
    """Continue a running CRC-16/CCITT-FALSE computation with more bytes.

    ``crc``: int, running register value (start from ``crc16_init()``).
    ``data``: bytes. Returns: int, updated register value.

    ``crc16_ccitt_false(data) == crc16_update(crc16_init(), data)`` --
    the incremental primitive the CRC-scope composition in
    ``encode_frame()``/``decode_frame()`` is built on."""
    for byte in data:
        crc = (crc ^ (byte << 8)) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def crc16_ccitt_false(data):
    """CRC-16/CCITT-FALSE over ``data`` (bytes) -- MSB-first, no input/
    output reflection, no final XOR. Returns an int. See this module's
    header for the pinned parameters and the known-answer test vector."""
    return crc16_update(crc16_init(), data)


def cobs_encoded_max_length(raw_len):
    """Worst-case COBS-encoded length (int) of ``raw_len`` bytes: one code
    byte per <=254-byte block, exact only when the input has no embedded
    zero bytes."""
    return raw_len + raw_len // _COBS_MAX_BLOCK + 1


def cobs_encode(data, delimiter=0x00):
    """Consistent Overhead Byte Stuffing encode.

    ``data``: bytes. ``delimiter``: int, the byte value to key the
    encoding on (default 0x00, plain COBS). Returns: bytes. Removes
    every occurrence of ``delimiter`` from ``data`` so the result can
    be delimited on the wire by a single instance of that byte -- the
    caller's job; this primitive never appends the trailing delimiter
    itself.

    Protocol v5 uses ``0x0A``: COBS guarantees 0x00-freedom but nothing
    about any other byte value, and a literal 0x0A in the payload would
    corrupt a ``'\\n'``-delimited wire.

    Mechanism: run the standard 0x00-keyed COBS algorithm, XOR-ing
    every output byte (data AND code bytes) with ``delimiter`` at the
    moment it is finalized -- equivalent to computing the 0x00-keyed
    encoding first and XOR-ing every byte after (XOR is position-wise),
    without a second pass. LANDMINE: this never emits a byte equal to
    ``delimiter`` only because the pre-XOR output is 0x00-free by
    construction (code bytes are >=1, data bytes are non-zero) and
    ``b ^ delimiter == delimiter`` iff ``b == 0`` -- preserve that
    invariant if this is ever touched."""
    out = bytearray()
    out.append(0)  # placeholder for the first block's code byte
    code_pos = 0
    code = 1  # distance to the next zero (or block end), inclusive of the code byte itself
    for byte in data:
        if byte == 0:
            out[code_pos] = code ^ delimiter
            code_pos = len(out)
            out.append(0)  # placeholder for the next block
            code = 1
        else:
            out.append(byte ^ delimiter)
            code += 1
            if code == 0xFF:
                # Cap hit before a zero was found: flush as a full
                # block and start fresh, as if a zero had been seen.
                out[code_pos] = code ^ delimiter
                code_pos = len(out)
                out.append(0)
                code = 1
    out[code_pos] = code ^ delimiter
    return bytes(out)


def cobs_decode(data, delimiter=0x00):
    """Reverse of ``cobs_encode()``.

    ``data``: bytes. ``delimiter``: int, must match the value passed to
    ``cobs_encode()``. Returns: bytes.

    Raises ``WireFrameError`` on any malformed or truncated input: a
    literal 0x00 code byte, a literal 0x00 inside a data block (an
    encoder never emits one), or a code byte whose claimed block length
    runs past the end of the input. Never returns a partial result.

    Each byte is XOR-ed with ``delimiter`` at the point of reading (not
    de-XORed as a separate pass) -- this recovers the 0x00-keyed bytes
    the algorithm below already walks, so the malformed-input checks
    need no change for a non-0x00 delimiter: a literal ``delimiter``
    byte inside a frame (impossible from a correct encoder) reads back
    as a literal 0x00 post-XOR, tripping the same rejections."""
    if len(data) == 0:
        # Even a zero-byte payload encodes to one code byte (0x01) --
        # a truly empty input has nothing valid to decode.
        raise WireFrameError("cobs_decode(): empty input")

    out = bytearray()
    read_pos = 0
    n = len(data)
    while read_pos < n:
        code = data[read_pos] ^ delimiter
        if code == 0:
            raise WireFrameError("cobs_decode(): literal 0x00 code byte")
        read_pos += 1
        block_len = code - 1
        if block_len > n - read_pos:
            raise WireFrameError("cobs_decode(): block length exceeds remaining input")
        block = bytes(b ^ delimiter for b in data[read_pos:read_pos + block_len])
        if 0 in block:
            raise WireFrameError("cobs_decode(): literal 0x00 inside data block")
        out.extend(block)
        read_pos += block_len
        # code < 0xFF means a real zero terminated this block (unless
        # this is the frame's last block); a 0xFF-coded block hit the
        # cap with no zero, so never re-emit one for it.
        if code != 0xFF and read_pos < n:
            out.append(0)
    return bytes(out)


def _crc_over_scope(command, payload):
    """CRC-scope composition protocol v5 needs: ``crc16(COMMAND ':'
    payload)`` when ``command`` (bytes) is non-empty, ``crc16(payload)``
    alone (byte-identical to protocol v4's CRC) otherwise. Built on
    ``crc16_init()``/``crc16_update()`` so ``command``/``payload`` are
    never concatenated into one ``bytes`` object just to hash them
    together. Returns an int."""
    crc = crc16_init()
    if command:
        crc = crc16_update(crc, command)
        crc = crc16_update(crc, b":")
    return crc16_update(crc, payload)


def encode_frame(payload, command=b""):
    """Encode ``payload`` (bytes -- a schema-encoded message's raw
    bytes) into a COBS+CRC frame body. Returns bytes.

    LANDMINE: CRC-then-COBS composition, not COBS-then-append-CRC --
    append the little-endian CRC-16 to ``payload``, THEN COBS-encode
    the combined bytes with delimiter ``0x0A``. Appending the CRC after
    COBS would risk emitting a literal delimiter byte if the CRC bytes
    happen to contain one.

    ``command``: bytes, the ASCII command-name bytes (no ``':'``
    separator) the CRC's input is scoped to extend over -- a SEPARATE
    argument, never concatenated with ``payload`` before COBS-encoding
    (the command is not part of the COBS input, only its CRC scope).
    Defaults to empty, which extends nothing: ``crc16(payload)`` alone.

    Returns the COBS-encoded frame body -- 0x0A-free by construction,
    not including the trailing ``'\\n'`` wire delimiter (append
    ``FRAME_DELIMITER`` yourself) and not including the leading
    ``<COMMAND>':'`` prefix either (the caller's job)."""
    crc = _crc_over_scope(command, payload)
    combined = payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))
    return cobs_encode(combined, delimiter=0x0A)


def decode_frame(frame, command=b""):
    """Reverse of ``encode_frame()``: COBS-decode (delimiter 0x0A),
    split off the trailing 2-byte little-endian CRC, verify it
    (CRC-scoped over ``command`` too, per ``encode_frame()``) against
    the leading payload bytes, and return the payload on success.

    ``frame``: bytes, the COBS body ONLY -- the wire line's leading
    ``<COMMAND>':'`` prefix must already be stripped off by the caller.
    ``command``: bytes, must match what ``encode_frame()`` was called
    with.

    Returns the decoded payload (bytes) on success, or ``None`` on ANY
    malformed/corrupt input (malformed COBS, a combined-bytes length
    under 2, or a CRC mismatch -- including a ``command`` that does not
    match what the frame was actually encoded with). Never raises."""
    try:
        combined = cobs_decode(frame, delimiter=0x0A)
    except WireFrameError:
        return None
    if len(combined) < 2:
        return None
    payload, crc_bytes = bytes(combined[:-2]), combined[-2:]
    received_crc = crc_bytes[0] | (crc_bytes[1] << 8)
    if _crc_over_scope(command, payload) != received_crc:
        return None
    return payload


class ByteStreamDemuxer:
    """Accumulates raw bytes from a byte-oriented transport and demuxes
    them into complete ``'\\n'``-terminated wire lines. Protocol v5's
    ``'\\n'`` (0x0A) terminator is unconditional in both directions --
    safe because COBS is keyed on 0x0A, so a binary line's own bytes
    never contain a literal 0x0A and a plain split-on-``'\\n'`` never
    misfires."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        """Append ``data`` (bytes) to the internal buffer; return every
        complete line now available, in wire order, as a list of bytes
        (``'\\n'`` consumed, not included). Never partially delivers a
        line; leftover undelimited bytes stay buffered for the next
        ``feed()`` call. A caller classifies each returned line as
        cleartext or binary via its own ``<COMMAND>`` prefix
        (``msgs.VERB_BY_NAME``) -- this class has no opinion."""
        self._buf.extend(data)
        out = []
        while True:
            idx = self._buf.find(0x0A)
            if idx == -1:
                break
            out.append(bytes(self._buf[:idx]))
            del self._buf[:idx + 1]
        return out
