"""M3 gate (radio_shim.py slice): `src/radio_shim.py`'s RAW250 fragment
reassembly against synthetic/captured on-air byte sequences, offline --
no radio hardware required (the `radio` module is import-guarded in
`radio_shim.py`; these tests call `RadioLink.feed_frame()` directly).

See `docs/design/specification.md` Sec 4/5 (`[SEQ][FLAGS][LEN]` framing,
MTU 247, `microbit_radio_link.cpp` as the framing reference) and
`clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/
005-v5-protocol-engine-comms-py-radio-shim-py-m3.md` for the acceptance
criterion this file encodes: "`src/radio_shim.py`'s fragment reassembly
is unit-tested offline against synthetic/captured on-air byte sequences
... without requiring radio hardware."
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import radio_shim  # noqa: E402  (path must be set up first)


def _build_frame(seq, flags, payload):
    """Hand-build one on-air frame -- independent of `RadioLink._fragment()`
    so these tests don't just check the shim against itself."""
    return bytes([seq & 0xFF, flags, len(payload)]) + payload


def test_constants_match_the_oracle():
    """AC: MTU 247, [SEQ][FLAGS][LEN] (3-byte) header -- per
    microbit_radio_link.h (FRAME_HEADER=3, MAX_FRAME=250, MTU=247)."""
    assert radio_shim.FRAME_HEADER == 3
    assert radio_shim.MAX_FRAME == 250
    assert radio_shim.MTU == 247
    assert radio_shim.FLAG_START == 0x01
    assert radio_shim.FLAG_MORE == 0x02
    assert radio_shim.FLAG_END == 0x04
    assert radio_shim.FLAG_ACK == 0x10


def test_single_fragment_message_reassembles():
    link = radio_shim.RadioLink(channel=3)
    frame = _build_frame(0, radio_shim.FLAG_START | radio_shim.FLAG_END, b"HELLO\n")
    link.feed_frame(frame)
    assert link.read_line() == b"HELLO"
    # Consumed -- a second read before another message arrives is empty.
    assert link.read_line() is None


def test_multi_fragment_message_reassembles_across_mtu_boundary():
    payload = (b"A" * 300) + b"\n"  # exceeds MTU (247) -- must span 2 frames
    link = radio_shim.RadioLink(channel=3)

    first_chunk = payload[:radio_shim.MTU]
    second_chunk = payload[radio_shim.MTU:]
    assert len(first_chunk) == radio_shim.MTU
    assert 0 < len(second_chunk) < radio_shim.MTU

    link.feed_frame(_build_frame(0, radio_shim.FLAG_START | radio_shim.FLAG_MORE, first_chunk))
    # Not complete yet.
    assert link.read_line() is None
    link.feed_frame(_build_frame(1, radio_shim.FLAG_END, second_chunk))

    assert link.read_line() == (b"A" * 300)


def test_send_then_peer_feed_frame_round_trips():
    """TX one `RadioLink.send()`, RX the frames it built into a SEPARATE
    `RadioLink.feed_frame()` -- self-consistency between fragmentation
    and reassembly, without touching the `radio` module (unavailable
    under CPython, exercised only via the returned frame list)."""
    tx = radio_shim.RadioLink(channel=3)
    rx = radio_shim.RadioLink(channel=3)

    # 250 bytes: > MTU (247, forces 2 fragments) but <= 255 (send()'s own
    # truncation cap), so the round trip is lossless.
    content = bytes(range(250))
    frames = tx.send(content)
    assert len(frames) > 1  # exceeds one MTU-sized fragment

    for frame in frames:
        rx.feed_frame(frame)

    assert rx.read_line() == content


def test_send_reliable_accepts_str_and_round_trips():
    tx = radio_shim.RadioLink(channel=3)
    rx = radio_shim.RadioLink(channel=3)
    frames = tx.send_reliable("PONG:t=123")
    for frame in frames:
        rx.feed_frame(frame)
    assert rx.read_line() == b"PONG:t=123"


def test_send_truncates_content_to_255_bytes_before_delimiter():
    """Mirrors MicroBitRadioLink::send()'s 256-byte payload buffer: up to
    255 content bytes, plus the appended '\\n' delimiter."""
    tx = radio_shim.RadioLink(channel=3)
    rx = radio_shim.RadioLink(channel=3)
    oversized = b"X" * 400
    frames = tx.send(oversized)
    for frame in frames:
        rx.feed_frame(frame)
    assert rx.read_line() == b"X" * 255


def test_ack_frame_is_never_reassembled():
    """An ACK frame (FLAG_ACK set) is dropped before even the START
    check -- mid-reassembly state of an IN-PROGRESS message must be
    completely unaffected by one arriving in between fragments."""
    link = radio_shim.RadioLink(channel=3)
    link.feed_frame(_build_frame(0, radio_shim.FLAG_START | radio_shim.FLAG_MORE, b"AB"))
    # An ACK frame arrives mid-message -- must be ignored outright, even
    # though it happens to carry FLAG_START too.
    link.feed_frame(_build_frame(1, radio_shim.FLAG_ACK | radio_shim.FLAG_START, b"ZZZZZZZZZZ"))
    link.feed_frame(_build_frame(2, radio_shim.FLAG_END, b"CD\n"))

    assert link.read_line() == b"ABCD"


def test_second_message_dropped_while_first_unconsumed():
    """Only one reassembled message is buffered at a time -- a second
    completing before read_line() drains the first is silently dropped,
    per RadioLink's own documented contract (mirrors onData())."""
    link = radio_shim.RadioLink(channel=3)
    link.feed_frame(_build_frame(0, radio_shim.FLAG_START | radio_shim.FLAG_END, b"FIRST\n"))
    # Second message completes before FIRST is read.
    link.feed_frame(_build_frame(1, radio_shim.FLAG_START | radio_shim.FLAG_END, b"SECOND\n"))

    assert link.read_line() == b"FIRST"
    assert link.read_line() is None  # SECOND was dropped, not queued


def test_short_frame_below_header_size_is_ignored():
    link = radio_shim.RadioLink(channel=3)
    link.feed_frame(b"\x00\x05")  # 2 bytes -- shorter than FRAME_HEADER (3)
    assert link.read_line() is None


def test_oversized_len_byte_is_clamped_to_remaining_bytes():
    """The LEN byte claims 10, but only 3 bytes of payload actually follow
    in the frame -- `feed_frame()` must clamp to what is actually present
    (`n - FRAME_HEADER`), not read past the end of `frame`."""
    link = radio_shim.RadioLink(channel=3)
    frame = bytes([0, radio_shim.FLAG_START | radio_shim.FLAG_END, 10]) + b"OK\n"
    link.feed_frame(frame)
    assert link.read_line() == b"OK"


def test_begin_and_poll_are_safe_no_ops_under_cpython():
    """`radio` is unavailable under CPython -- begin()/poll() must not
    raise, and must do nothing observable."""
    link = radio_shim.RadioLink(channel=3, group=10, queue=4, length=250)
    link.begin()  # no-op: radio_shim.radio is None in this test environment
    link.poll()  # no-op, same reason
    assert link.read_line() is None
