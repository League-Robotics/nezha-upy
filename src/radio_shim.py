"""radio_shim -- MicroPython `radio` wrapper + RAW250 fragment
reassembly; implements the `comms.py` Transport contract
(`read_line()`/`send()`/`send_reliable()`), ported from radio-robot's
`microbit_radio_link.{h,cpp}`.

RAW250 frame: `[SEQ:1][FLAGS:1][LEN:1][payload:LEN]`, the raw payload
of one CODAL radio datagram (no MakeCode/PXT header). FLAGS:
START=0x01, MORE=0x02, END=0x04, ACK=0x10. Messages over MTU (247)
split START..END; ACK frames are dropped before the START check.

Config facts: `length=250` must match the relay's on-air MAXLEN;
`group=10` matches the relay; `channel` comes from JSON config;
`queue=4` fixes the old firmware's C++ single-slot RX loss.

`radio` is import-guarded (MicroPython-only) so this file, and
`feed_frame()`/`send()` in particular, run under CPython with no
hardware. No PEP 604/generic-subscript hints, no f-strings (CLAUDE.md).
"""

try:
    import radio
except ImportError:  # CPython tests, or a build without radio
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

# Fragment framing (RadioRelay Sec 5), matches MicroBitRadioLink exactly.
FLAG_START = 0x01
FLAG_MORE = 0x02
FLAG_END = 0x04
FLAG_ACK = 0x10

FRAME_HEADER = 3  # [SEQ][FLAGS][LEN]
MAX_FRAME = 250  # MICROBIT_RADIO_MAX_PACKET_SIZE
MTU = MAX_FRAME - FRAME_HEADER  # 247
REASM_MAX = 512  # v2 GET dump can reach ~290 bytes

_MAX_SEND_CONTENT = 255  # + 1 trailing '\n' = MicroBitRadioLink::send()'s 256-byte buffer


class RadioLink:
    """One RAW250 radio link -- binary-clean, no interpretation beyond
    the [SEQ][FLAGS][LEN] header. Buffers only ONE reassembled message
    at a time -- a second completing before `read_line()` drains the
    first is silently dropped (matches `onData()`)."""

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
        """`radio.on()` + `radio.config(...)`. No-op under CPython."""
        if radio is None:
            return
        radio.on()
        radio.config(channel=self._channel, group=self._group,
                     queue=self._queue, length=self._length)

    def channel(self):
        return self._channel

    def poll(self):
        """Drain queued packets into `feed_frame()`. No-op under CPython."""
        if radio is None:
            return
        while True:
            packet = radio.receive_bytes()
            if packet is None:
                break
            self.feed_frame(packet)

    # --- reassembly ------------------------------------------------------

    def feed_frame(self, frame):
        """Process ONE on-air frame's raw bytes -- mirrors `onData()`;
        callable directly with synthetic/captured bytes, no hardware."""
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
            if self._reasm_active and not self._msg_ready:  # else drop -- previous msg not yet drained
                self._msg = bytes(self._reasm)
                self._msg_ready = True
            self._reasm_active = False
            self._reasm = bytearray()

    def read_line(self):
        """Non-blocking; next message, trailing `'\\n'` stripped (not
        `'\\r'` -- a binary line may carry 0x0D as content), or `None`."""
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
        """Fragment `data` (one wire line, no trailing `'\\n'`) into
        RAW250 frames and transmit via `radio.send_bytes()` (no-op
        under CPython); truncates to 255 content bytes first. Returns
        the frames built, for tests."""
        data = bytes(data)
        n = len(data) if len(data) < _MAX_SEND_CONTENT else _MAX_SEND_CONTENT
        payload = data[:n] + b"\n"
        frames = self._fragment(payload)
        if radio is not None:
            for frame in frames:
                radio.send_bytes(frame)
        return frames

    def send_reliable(self, text):
        """Same as `send()` for a cleartext line; accepts `str`. No
        bounded-wait path -- RAW250 has no backpressure signal."""
        if isinstance(text, str):
            text = text.encode("ascii")
        return self.send(text)

    def _fragment(self, payload):
        """Split `payload` (its trailing `'\\n'` already included) into
        RAW250 frames -- mirrors `sendFragmented()`'s do/while loop."""
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

            # LANDMINE: concatenate, never bytearray slice-assign -- raises
            # TypeError ON DEVICE only; see docs/bench-log-zetuv-2026-08-19.md.
            seq = self._tx_seq & 0xFF
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            frame = bytes((seq, flags, chunk)) + bytes(payload[off:off + chunk])
            frames.append(frame)

            off += chunk
            first = False
            if off >= payload_len:
                break
        return frames
