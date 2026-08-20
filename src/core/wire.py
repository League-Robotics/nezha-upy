"""wire -- v5 protocol wire codec: COBS + CRC-16/CCITT-FALSE framing.

Ported from radio-robot's ``wire_codec.py``, byte-for-byte compatible
(PLAN.md M2 / ``docs/design/specification.md`` Sec 4).

Wire line: ``<COMMAND>[':' <data>]'\\n'``. A binary frame's ``<data>``
is CRC-then-COBS: append the little-endian CRC-16 (scoped over
``COMMAND ':' payload``) to the payload, THEN COBS-encode the result.
COBS is keyed on 0x0A (not 0x00), so a binary line's own bytes never
contain a literal ``'\\n'`` and the terminator is unconditional.

``ByteStreamDemuxer`` is the one stateful piece here; every other
function is pure (``bytes`` in, ``bytes``/``None``/exception out).

CRC-16/CCITT-FALSE parameters (pinned, no negotiation, no version
byte): poly=0x1021 init=0xFFFF refin=False refout=False xorout=0x0000.
Known-answer vector: ``crc16_ccitt_false(b"123456789") == 0x29B1``.

LANDMINE: no ``from __future__ import annotations``, no PEP 604, no
generic-subscript type hints -- must import and run unmodified under
both CPython (host tests) and MicroPython, which lacks that syntax.
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

# Terminator every transport appends after a wire line (protocol v5).
FRAME_DELIMITER = b"\n"

_COBS_MAX_BLOCK = 254  # 0xFF marks a full block that hit the cap before a zero

_CRC16_POLY = 0x1021  # see module docstring for the full parameter set
_CRC16_INIT = 0xFFFF


class WireFrameError(ValueError):
    """Raised by ``cobs_encode()``/``cobs_decode()`` on malformed input;
    ``decode_frame()`` catches it internally and returns ``None``."""


def crc16_init():
    """Initial CRC-16/CCITT-FALSE register value (int)."""
    return _CRC16_INIT


def crc16_update(crc, data):
    """Continue a running CRC-16/CCITT-FALSE computation. ``crc``: int
    register (start from ``crc16_init()``). ``data``: bytes. Returns
    int."""
    for byte in data:
        crc = (crc ^ (byte << 8)) & 0xFFFF
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def crc16_ccitt_false(data):
    """CRC-16/CCITT-FALSE over ``data`` (bytes). Returns an int. See
    module docstring for parameters and the known-answer vector."""
    return crc16_update(crc16_init(), data)


def cobs_encoded_max_length(raw_len):
    """Worst-case COBS-encoded length (int) of ``raw_len`` bytes; exact
    only when the input has no embedded zero bytes."""
    return raw_len + raw_len // _COBS_MAX_BLOCK + 1


def cobs_encode(data, delimiter=0x00):
    """Consistent Overhead Byte Stuffing encode. ``delimiter``: int,
    byte to key on (default 0x00, plain COBS; v5 passes 0x0A so a
    literal ``'\\n'`` never appears). Returns bytes with every
    ``delimiter`` occurrence removed; caller appends the trailing one.

    Runs standard 0x00-keyed COBS, XOR-ing each output byte with
    ``delimiter`` at write time (one pass). LANDMINE: relies on the
    pre-XOR output being 0x00-free (code bytes >=1, data non-zero), so
    ``b ^ delimiter == delimiter`` iff ``b == 0`` -- preserve on touch."""
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
                # Cap hit before a zero: flush as a full block, as if a zero had been seen.
                out[code_pos] = code ^ delimiter
                code_pos = len(out)
                out.append(0)
                code = 1
    out[code_pos] = code ^ delimiter
    return bytes(out)


def cobs_decode(data, delimiter=0x00):
    """Reverse of ``cobs_encode()``; ``delimiter`` must match. Raises
    ``WireFrameError`` on malformed/truncated input (0x00 code byte,
    0x00 inside a data block, or a block length past the end) --
    never partial. Each byte is XOR-ed with ``delimiter`` at read time
    (one pass), so a literal ``delimiter`` in a frame reads back as
    0x00 post-XOR and trips the same rejections."""
    if len(data) == 0:
        raise WireFrameError("cobs_decode(): empty input")  # a 0-byte payload still encodes to 1 code byte

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
        if code != 0xFF and read_pos < n:  # 0xFF-coded block hit the cap; never re-emit its zero
            out.append(0)
    return bytes(out)


def _crc_over_scope(command, payload):
    """``crc16(COMMAND ':' payload)`` if ``command`` (bytes) is
    non-empty, else ``crc16(payload)`` alone (byte-identical to
    protocol v4's CRC). Built on ``crc16_update()`` so the two are
    never concatenated just to hash them together. Returns an int."""
    crc = crc16_init()
    if command:
        crc = crc16_update(crc, command)
        crc = crc16_update(crc, b":")
    return crc16_update(crc, payload)


def encode_frame(payload, command=b""):
    """Encode ``payload`` (bytes) into a COBS+CRC frame body (bytes,
    no trailing ``'\\n'`` or ``<COMMAND>':'`` prefix -- caller's job).

    LANDMINE: CRC-then-COBS, not COBS-then-append-CRC -- append the
    little-endian CRC-16 to ``payload``, THEN COBS-encode (delimiter
    0x0A); the reverse order risks a literal 0x0A escaping inside the
    CRC bytes.

    ``command``: bytes, ASCII verb name the CRC scope extends over,
    never concatenated with ``payload`` before COBS-encoding. Default
    empty -> ``crc16(payload)`` alone."""
    crc = _crc_over_scope(command, payload)
    combined = payload + bytes((crc & 0xFF, (crc >> 8) & 0xFF))
    return cobs_encode(combined, delimiter=0x0A)


def decode_frame(frame, command=b""):
    """Reverse of ``encode_frame()``: COBS-decode (delimiter 0x0A),
    verify the trailing 2-byte little-endian CRC (scoped over
    ``command`` too) against the payload, return the payload.
    ``frame``: COBS body only (no ``<COMMAND>':'`` prefix). Returns
    ``None`` on any malformed/corrupt input; never raises."""
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
    """Buffers raw transport bytes and demuxes them into complete
    ``'\\n'``-terminated wire lines. Splitting unconditionally on 0x0A
    is safe because COBS keys on that byte (see module docstring)."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data):
        """Append ``data`` (bytes); return every complete line now
        available, in order, as a list of bytes (``'\\n'`` stripped).
        Leftover undelimited bytes stay buffered. Caller classifies
        each line as cleartext/binary via its own ``<COMMAND>`` prefix
        (``msgs.VERB_BY_NAME``)."""
        self._buf.extend(data)
        out = []
        while True:
            idx = self._buf.find(0x0A)
            if idx == -1:
                break
            out.append(bytes(self._buf[:idx]))
            del self._buf[:idx + 1]
        return out
