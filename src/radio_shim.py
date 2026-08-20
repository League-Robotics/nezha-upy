"""radio_shim -- MicroPython `radio` module wrapper + RAW250 fragment
reassembly, implementing the same duck-typed Transport contract
`comms.py` expects (`read_line()`/`send()`/`send_reliable()`).

Ported from radio-robot's
`src/firm/platform/microbit/microbit_radio_link.{h,cpp}` -- RAW250
framing:

    [SEQ:1][FLAGS:1][LEN:1][payload:LEN]

carried as the raw payload of one CODAL/MicroPython radio datagram (no
MakeCode/PXT header). FLAGS: START=0x01, MORE=0x02, END=0x04, ACK=0x10.
A message longer than MTU (247) bytes is split across multiple fragments,
START through END; a single-fragment message is flagged START|END
(0x05). ACK frames (FLAG_ACK set) are never reassembled -- dropped before
even the START check, exactly like `onData()`'s own early return.

`length=250` (`MICROBIT_RADIO_MAX_PACKET_SIZE`) must match the relay's
on-air MAXLEN; `group=10` is fixed to match the relay; `channel` comes
from the robot's JSON config; `queue=4` fixes the C++ single-slot RX
loss the old firmware carried.

MicroPython-only: the `radio` module is import-guarded so this file
imports and the reassembly/fragmentation logic (`feed_frame()`/`send()`)
runs unmodified under CPython, fed synthetic/captured on-air byte
sequences directly with no hardware.

Deviations from the radio-robot source, matching `wire.py`'s own
precedent: no PEP 604/generic-subscript type hints, no f-strings
(project style: CLAUDE.md).
"""

try:
    import radio
except ImportError:  # CPython (tests), or no radio module on this build
    radio = None

__all__ = [
    "RadioLink",
    "FLAG_START",
    "FLAG_MORE",
    "FLAG_END",
    "FLAG_ACK",
    "FRAME_HEADER",
    "MTU",
    "MAX_FRAME",
    "REASM_MAX",
]

# RadioRelay Sec 5 fragment framing -- mirrors
# MicroBitRadioLink's private constants exactly.
FLAG_START = 0x01
FLAG_MORE = 0x02
FLAG_END = 0x04
FLAG_ACK = 0x10

FRAME_HEADER = 3  # [SEQ][FLAGS][LEN]
MAX_FRAME = 250  # MICROBIT_RADIO_MAX_PACKET_SIZE
MTU = MAX_FRAME - FRAME_HEADER  # 247
REASM_MAX = 512  # v2 GET dump can reach ~290 bytes

# The largest raw line content `send()` will fragment -- mirrors
# MicroBitRadioLink::send()'s own 256-byte payload buffer: up to 255
# content bytes, plus the one trailing '\n' delimiter it always appends.
_MAX_SEND_CONTENT = 255


class RadioLink:
    """One RAW250 radio link -- binary-clean, no wire-line interpretation
    beyond the [SEQ][FLAGS][LEN] fragment header (Core::Comms decides
    cleartext-vs-binary from the parsed `<COMMAND>` prefix once it has a
    complete line -- see `comms.py`'s own docstring, same division of
    responsibility as the C++ source).

    Only ONE reassembled message is buffered at a time -- a second
    message completing before `read_line()` drains the first is silently
    dropped, exactly matching `MicroBitRadioLink::onData()`'s own
    documented behavior."""

    def __init__(self, channel, group=10, queue=4, length=MAX_FRAME):
        self._channel = channel
        self._group = group
        self._queue = queue
        self._length = length

        self._reasm = bytearray()
        self._reasm_active = False
        self._msg = None
        self._msg_ready = False
        self._tx_seq = 0

    # --- MicroPython radio setup / polling ------------------------------

    def begin(self):
        """`radio.on()` + `radio.config(...)` with this link's
        channel/group/queue/length. No-op under CPython (`radio`
        unavailable) -- tests drive `feed_frame()`/inspect `send()`'s
        return value directly instead."""
        if radio is None:
            return
        radio.on()
        radio.config(channel=self._channel, group=self._group,
                     queue=self._queue, length=self._length)

    def channel(self):
        return self._channel

    def poll(self):
        """Drain any MicroPython-queued packets into `feed_frame()`.
        No-op under CPython."""
        if radio is None:
            return
        while True:
            packet = radio.receive_bytes()
            if packet is None:
                break
            self.feed_frame(packet)

    # --- reassembly ------------------------------------------------------

    def feed_frame(self, frame):
        """Process ONE on-air frame's raw bytes -- mirrors `onData()`
        exactly: binary-clean (no interpretation beyond the 3-byte
        header), safe to call directly with synthetic/captured on-air
        byte sequences, no radio hardware required."""
        frame = bytes(frame)
        n = len(frame)
        if n < FRAME_HEADER:
            return

        flags = frame[1]
        plen = frame[2]
        if plen > n - FRAME_HEADER:
            plen = n - FRAME_HEADER

        if flags & FLAG_ACK:
            return  # ACK frame: nothing to assemble

        if flags & FLAG_START:
            self._reasm = bytearray()
            self._reasm_active = True

        if self._reasm_active and plen > 0:
            space = REASM_MAX - 1 - len(self._reasm)
            copy = plen if plen < space else space
            if copy > 0:
                self._reasm.extend(frame[FRAME_HEADER:FRAME_HEADER + copy])

        if flags & FLAG_END:
            # Publish only if the previous message has been consumed;
            # otherwise drop -- matches onData()'s own "second message
            # completing before readLine() drains the first" behavior.
            if self._reasm_active and not self._msg_ready:
                self._msg = bytes(self._reasm)
                self._msg_ready = True
            self._reasm_active = False
            self._reasm = bytearray()

    def read_line(self):
        """Non-blocking. Returns the next complete reassembled message's
        raw content (a single trailing `'\\n'` stripped, matching
        `readLine()`'s own contract -- NOT `'\\r'`-stripping: a binary
        line may legitimately carry 0x0D as content, only classified as
        cleartext once `comms.py` has parsed the `<COMMAND>` prefix), or
        `None` if none is ready."""
        if not self._msg_ready:
            return None
        content = self._msg
        if content[-1:] == b"\n":
            content = content[:-1]
        self._msg_ready = False
        self._msg = None
        return content

    # --- fragmentation / send --------------------------------------------

    def send(self, data):
        """Fragment `data` (one wire line's raw content, no trailing
        `'\\n'` -- matches the Transport contract) into RAW250 frames and
        transmit each via `radio.send_bytes()` (no-op under CPython).
        Truncates to 255 content bytes before appending the trailing
        `'\\n'` delimiter, matching `MicroBitRadioLink::send()`'s
        256-byte payload buffer exactly. Returns the list of frames
        actually built (bytes each) -- lets tests verify fragmentation
        without live hardware; harmless to ignore on-device."""
        data = bytes(data)
        n = len(data) if len(data) < _MAX_SEND_CONTENT else _MAX_SEND_CONTENT
        payload = data[:n] + b"\n"
        frames = self._fragment(payload)
        if radio is not None:
            for frame in frames:
                radio.send_bytes(frame)
        return frames

    def send_reliable(self, text):
        """Same contract as `send()` for a cleartext line -- accepts
        `str` for caller convenience (mirrors `sendReliable(const char*)`
        forwarding straight to `send()`, no separate bounded-wait path:
        RAW250 fragmentation has no backpressure signal to wait on)."""
        if isinstance(text, str):
            text = text.encode("ascii")
        return self.send(text)

    def _fragment(self, payload):
        """Split `payload` (already including its trailing `'\\n'`) into
        RAW250 frames -- mirrors `sendFragmented()`'s do/while loop
        exactly (a zero-length payload would still emit one START|END
        frame; never occurs in practice since `send()` always appends
        the `'\\n'` first)."""
        frames = []
        off = 0
        first = True
        payload_len = len(payload)
        while True:
            chunk = payload_len - off
            if chunk > MTU:
                chunk = MTU

            flags = 0
            if first:
                flags |= FLAG_START
            if off + chunk < payload_len:
                flags |= FLAG_MORE
            else:
                flags |= FLAG_END

            # Built by concatenation, never mutation: this port compiles
            # out MICROPY_PY_ARRAY_SLICE_ASSIGN, so bytearray slice-store
            # raises TypeError ON DEVICE only (see docs/bench-log-
            # zetuv-2026-08-19.md).
            seq = self._tx_seq & 0xFF
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            frame = bytes((seq, flags, chunk)) + bytes(payload[off:off + chunk])
            frames.append(frame)

            off += chunk
            first = False
            if off >= payload_len:
                break
        return frames
