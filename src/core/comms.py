"""comms -- v5 protocol engine: dispatch order, ack ring, telemetry
emit policy, scheduled-pump plumbing. Ported from radio-robot's
``core/comms.{cpp,h}``/``core/telemetry.{cpp,h}`` (spec Sec 5/6, same
order/ring-depths/emit arithmetic) -- not a byte-for-byte binary frame
encoder (``msgs.py`` lacks per-verb field tables). Binary verbs are
COBS+CRC-validated (``wire.decode_frame()``) then handed to the
dispatch interface below as opaque bytes.

Dispatch order (``_dispatch_line()``, mirrors ``dispatchLine()``):
    1. Relay control lines (``#``/``!``/``?`` first byte) dropped, not
       even verb-looked-up.
    2. Verb looked up in ``msgs.VERB_BY_NAME``; unknown -> drop.
    3. TLM, SEED, DBG intercepted HERE, before the binary/cleartext
       branch (TLM's REPLY is binary but its inbound name is
       cleartext-mode; SEED/DBG are cleartext-flagged but the generic
       switch has no cases for them).
    4. Else: binary -> COBS+CRC validate, queue; cleartext -> answer
       immediately (HELLO/PING/ID/VER/STATUS/HELP/POSE).

Dispatch interface: comms.py never calls firmware modules directly. A
dispatch object exposes ``handle_command(verb_name, payload, now) ->
(corr_id, err_code) | None`` (``now``: int [ms]) -- a pair pushes an
ack, ``None`` sends none (see ``NullDispatch``); ``motion.py``/
``config.py`` back it for real, tests use a stub.

Transport contract (``Comms.add_transport()`` -- ``radio_shim.RadioLink``,
the loopback test's in-process pipe):
    read_line() -> bytes | None      next line, ``'\\n'`` stripped
    send(data: bytes) -> None        appends its own trailing ``'\\n'``
    send_reliable(text: str | bytes) -> None   same, for cleartext

``PumpTimer`` wires a periodic source to ``micropython.schedule(pump)``
(Sec 5) -- IRQ/fiber execution corrupts the heap, so pumping runs only
from main context. No PEP 604/generic-subscript hints, no f-strings
(CLAUDE.md).
"""

from core import msgs
from core import wire

try:
    import micropython
except ImportError:  # CPython (tests), or a MicroPython build without it
    micropython = None

__all__ = [
    "Comms",
    "TelemetryPolicy",
    "Status",
    "SeedRequest",
    "DbgAction",
    "NullDispatch",
    "PumpTimer",
    "TLM_NONE",
    "TLM_FRAME",
    "TLM_SET_OFF",
    "TLM_SET_AUTO",
    "TLM_SET_ON",
    "TLM_UNRECOGNIZED",
    "TLM_MODE_OFF",
    "TLM_MODE_AUTO",
    "TLM_MODE_ON",
]

# Ring depths / policy constants -- mirror core/comms.h, core/telemetry.h.
CMD_RING_DEPTH = 12  # Core::kCmdRingDepth
PUMP_MAX_LINES = 2 * CMD_RING_DEPTH  # Core::kPumpMaxLines
DBG_RING_DEPTH = 4  # Core::Comms::kDbgRingDepth
MAX_TRANSPORTS = 4  # Core::Comms::kMaxTransports

ACK_RING_DEPTH = 12  # Core::kAckRingDepth
ACK_REPEATS = 3  # Core::kAckRepeats
ACK_ERR_BITS = 4  # Core::telemetry.cpp kAckErrBits
ACK_ERR_MASK = (1 << ACK_ERR_BITS) - 1

PRIMARY_PERIOD_MS = 25  # Core::kPrimaryPeriod
COAST_HOLDOFF_MS = 2000  # Core::kCoastHoldoff

TLM_MODE_OFF = "OFF"
TLM_MODE_AUTO = "AUTO"
TLM_MODE_ON = "ON"

# Core::Comms::TlmAction as plain strings (no `enum` -- host-only import).
TLM_NONE = "NONE"
TLM_FRAME = "FRAME"
TLM_SET_OFF = "SET_OFF"
TLM_SET_AUTO = "SET_AUTO"
TLM_SET_ON = "SET_ON"
TLM_UNRECOGNIZED = "UNRECOGNIZED"


def _parse_float_prefix(text, start):
    """Parse the LONGEST valid float-literal prefix of ``text`` from
    ``start`` -- mirrors C's ``strtof()`` (parses what it can, no
    trailing delimiter required, never raises). Returns ``(value,
    end_index)``; ``(None, start)`` on failure (no digits found)."""
    n = len(text)
    i = start
    if i < n and (text[i] == "+" or text[i] == "-"):
        i += 1
    digits_start = i
    while i < n and "0" <= text[i] <= "9":
        i += 1
    if i < n and text[i] == ".":
        i += 1
        while i < n and "0" <= text[i] <= "9":
            i += 1
    has_digit = False
    for ch in text[digits_start:i]:
        if "0" <= ch <= "9":
            has_digit = True
            break
    if not has_digit:
        return None, start
    if i < n and (text[i] == "e" or text[i] == "E"):
        j = i + 1
        if j < n and (text[j] == "+" or text[j] == "-"):
            j += 1
        exp_digits_start = j
        while j < n and "0" <= text[j] <= "9":
            j += 1
        if j > exp_digits_start:
            i = j
    token = text[start:i]
    try:
        value = float(token)
    except ValueError:
        return None, start
    return value, i


def _parse_leading_uint(text):
    """Leading run of ASCII digits in ``text`` as an int, trailing junk
    ignored -- mirrors ``strtoul(text, nullptr, 10)``. Never raises."""
    i = 0
    n = len(text)
    while i < n and "0" <= text[i] <= "9":
        i += 1
    if i == 0:
        return 0
    return int(text[:i])


def _classify_tlm_arg(data):
    """Mirrors ``classifyTlmArg()`` -- ``data`` (text after ``TLM:``)
    matched case-insensitively against NOW/ON/AUTO/OFF. Returns a
    ``TLM_*`` constant; never raises (non-ASCII -> unrecognized)."""
    if data and data[-1:] == b"\r":
        data = data[:-1]
    try:
        text = bytes(data).decode("ascii") if data else ""
    except UnicodeError:
        return TLM_UNRECOGNIZED
    upper = text.upper()
    if upper == "NOW":
        return TLM_FRAME
    if upper == "ON":
        return TLM_SET_ON
    if upper == "AUTO":
        return TLM_SET_AUTO
    if upper == "OFF":
        return TLM_SET_OFF
    return TLM_UNRECOGNIZED


class DbgAction:
    """``kind``: ``"none"`` (ring-empty sentinel, distinct from
    ``"unrecognized"`` = a DBG line was received but didn't parse),
    ``"mark"``/``"ping"``/``"clear"``/``"otos"``/``"vmin"``/
    ``"asteady"``/``"pos"``/``"gain"``/``"wedge"``/``"unrecognized"``."""

    def __init__(self, kind="none", text="", port=0, duration=0, value=0.0, value2=0.0):
        self.kind = kind
        self.text = text  # "mark": the full original argument text
        self.port = port  # "wedge": 1=left, 2=right, 3=both
        self.duration = duration  # [ms] "wedge" auto-clear; 0 = latched
        self.value = value
        self.value2 = value2

    def __repr__(self):
        return "DbgAction(kind=%r, text=%r, port=%r, duration=%r, value=%r, value2=%r)" % (
            self.kind, self.text, self.port, self.duration, self.value, self.value2,
        )


def _classify_dbg_arg(data):
    """Mirrors ``classifyDbgArg()``'s sub-command tokenizer (mark/ping/
    clear/otos/vmin/asteady/pos/gain/wedge). Returns a ``DbgAction``;
    ``kind="unrecognized"`` on any parse failure, empty, or non-ASCII."""
    if not data:
        return DbgAction(kind="unrecognized")
    try:
        text = bytes(data).decode("ascii")
    except UnicodeError:
        return DbgAction(kind="unrecognized")

    tokens = text.split()
    if not tokens:
        return DbgAction(kind="unrecognized")
    sub = tokens[0]
    rest = tokens[1:]

    if sub == "mark":
        return DbgAction(kind="mark", text=text)
    if sub == "ping":
        return DbgAction(kind="ping")
    if sub == "clear":
        return DbgAction(kind="clear")
    if sub == "otos":
        return DbgAction(kind="otos")

    def scalar(idx):
        if idx >= len(rest):
            return None
        token = rest[idx]
        value, end = _parse_float_prefix(token, 0)
        if value is None or end != len(token) or not (value >= 0.0):
            return None
        return value

    if sub == "vmin":
        value = scalar(0)
        return DbgAction(kind="vmin", value=value) if value is not None else DbgAction(kind="unrecognized")
    if sub == "asteady":
        value = scalar(0)
        return DbgAction(kind="asteady", value=value) if value is not None else DbgAction(kind="unrecognized")
    if sub == "pos":
        value = scalar(0)
        return DbgAction(kind="pos", value=value) if value is not None else DbgAction(kind="unrecognized")
    if sub == "gain":
        v1 = scalar(0)
        v2 = scalar(1)
        if v1 is None or v2 is None or v1 <= 0.0 or v2 <= 0.0:
            return DbgAction(kind="unrecognized")
        return DbgAction(kind="gain", value=v1, value2=v2)
    if sub == "wedge":
        if not rest:
            return DbgAction(kind="unrecognized")
        which = rest[0]
        if which == "left":
            port = 1
        elif which == "right":
            port = 2
        elif which == "both":
            port = 3
        else:
            return DbgAction(kind="unrecognized")
        duration = _parse_leading_uint(rest[1]) if len(rest) > 1 else 0
        return DbgAction(kind="wedge", port=port, duration=duration)

    return DbgAction(kind="unrecognized")


class SeedRequest:
    """External world-fix staged by SEED, drained by ``motion.py``.
    ``x``/``y`` [mm], ``heading`` [rad]. ``reply_transport``: SEED's
    transport -- the firmware layer replies on it; comms.py does not."""

    def __init__(self, x, y, heading, reply_transport):
        self.x = x
        self.y = y
        self.heading = heading
        self.reply_transport = reply_transport


class Status:
    """Data the firmware layer publishes each cycle via
    ``Comms.set_status()`` so ``STATUS``/``POSE`` have something to
    format. Note: the ``STATUS`` reply reads ``Comms.telemetry.mode``
    directly, not a field here."""

    def __init__(self):
        self.ready = False
        self.active = False
        self.wheel_left_connected = False
        self.wheel_right_connected = False
        self.otos_present = False
        self.wedged = False
        self.flags = 0
        self.otos_x = 0
        self.otos_y = 0
        self.otos_heading = 0
        self.enc_x = 0
        self.enc_y = 0
        self.enc_heading = 0


class NullDispatch:
    """Default dispatch when ``Comms`` gets no explicit ``dispatch``.
    Produces no ack: a real ``corr_id`` lives inside the still-opaque
    ``payload`` (module docstring), so ``None`` is the only honest
    response with nothing wired up."""

    def handle_command(self, verb_name, payload, now):
        return None


class TelemetryPolicy:
    """Ack ring + primary-frame emit-policy, decoupled from frame
    CONTENT -- mirrors ``Core::Telemetry`` but does not build the real
    22-field TLM wire frame (``src/core/telemetry.py``, pending field
    tables). ``emit_callback(now, acks)``, if given, fires exactly
    when a primary frame would be sent (``acks``: packed ``corr_id <<
    4 | err_code`` ints, oldest first); the caller builds/broadcasts
    the wire bytes."""

    def __init__(self, emit_callback=None):
        self.mode = TLM_MODE_AUTO
        self.emit_count = 0
        self._active = False
        self._ever_moved = False
        self._last_activity = 0
        self._ack_ring = [0] * ACK_RING_DEPTH
        self._ack_sends = [0] * ACK_RING_DEPTH
        self._ack_head = 0
        self._ack_count = 0
        self._ever_emitted = False
        self._last_emit = 0
        self._emit_callback = emit_callback

    def set_active(self, active, now):
        """``True`` marks "moving now" and refreshes the coast window;
        ``False`` alone does not clear activity (holdoff still applies)."""
        self._active = active
        if active:
            self._ever_moved = True
            self._last_activity = now

    def ack(self, corr_id, err_code):
        """Push ``(corr_id, err_code)`` onto the ack ring, packed as
        ``corr_id << 4 | (err_code & 0xF)``; depth 12, oldest evicted
        once full."""
        packed = (corr_id << ACK_ERR_BITS) | (err_code & ACK_ERR_MASK)
        if self._ack_count < ACK_RING_DEPTH:
            tail = (self._ack_head + self._ack_count) % ACK_RING_DEPTH
            self._ack_count += 1
        else:
            tail = self._ack_head
            self._ack_head = (self._ack_head + 1) % ACK_RING_DEPTH
        self._ack_ring[tail] = packed
        self._ack_sends[tail] = 0

    def apply_action(self, action):
        """Mirrors ``applyAction()``: SET_OFF/SET_AUTO/SET_ON update
        ``mode``; returns True iff ``action`` is ``TLM_FRAME``."""
        if action == TLM_SET_OFF:
            self.mode = TLM_MODE_OFF
        elif action == TLM_SET_AUTO:
            self.mode = TLM_MODE_AUTO
        elif action == TLM_SET_ON:
            self.mode = TLM_MODE_ON
        return action == TLM_FRAME

    def _primary_due(self, now):
        if not self._ever_emitted:
            return True
        return (now - self._last_emit) >= PRIMARY_PERIOD_MS

    def _pending_ack_deliveries(self):
        for i in range(self._ack_count):
            idx = (self._ack_head + i) % ACK_RING_DEPTH
            if self._ack_sends[idx] < ACK_REPEATS:
                return True
        return False

    def _activity(self, now):
        return self._active or (self._ever_moved and (now - self._last_activity) < COAST_HOLDOFF_MS)

    def emit(self, now, force=False):
        """Mirrors ``Telemetry::emit()``: AUTO emits unsolicited frames
        only while ``_activity()``; OFF never, ON always. A pending
        ack or ``force=True`` (TLM "NOW") forces emission regardless --
        all still gated by ``_primary_due()`` (the 25 ms floor)."""
        activity = self._activity(now)
        if self.mode == TLM_MODE_OFF:
            unsolicited = False
        elif self.mode == TLM_MODE_ON:
            unsolicited = True
        else:
            unsolicited = activity
        if self._primary_due(now) and (force or unsolicited or self._pending_ack_deliveries()):
            self._emit_primary(now)

    def _emit_primary(self, now):
        acks = []
        for i in range(self._ack_count):
            idx = (self._ack_head + i) % ACK_RING_DEPTH
            acks.append(self._ack_ring[idx])
            if self._ack_sends[idx] < ACK_REPEATS:
                self._ack_sends[idx] += 1
        self._ever_emitted = True
        self._last_emit = now
        self.emit_count += 1
        if self._emit_callback is not None:
            self._emit_callback(now, acks)


class Comms:
    """v5 protocol engine -- mirrors ``Core::Comms``. Owns the
    transports (registration order is dispatch-tie-break order), the
    command ring, DBG/SEED staging, and ``self.telemetry``."""

    def __init__(self, banner, id_line, dispatch=None, version="dev", emit_callback=None):
        self._banner = banner
        self._id_line = id_line
        self._version = version
        self._dispatch = dispatch if dispatch is not None else NullDispatch()
        self._transports = []

        self._cmd_ring = [None] * CMD_RING_DEPTH
        self._cmd_head = 0
        self._cmd_count = 0

        self.malformed_count = 0
        self.commands_dropped_count = 0

        self._tlm_action = TLM_NONE
        self._tlm_reply_transport = None

        self._seed = None

        self._dbg_ring = [None] * DBG_RING_DEPTH
        self._dbg_head = 0
        self._dbg_count = 0

        self._status = Status()
        self.telemetry = TelemetryPolicy(emit_callback=emit_callback)

    # --- transport registration -------------------------------------

    def add_transport(self, transport):
        """Register one more transport, in order. Returns False (never
        raises) once ``MAX_TRANSPORTS`` are registered."""
        if len(self._transports) >= MAX_TRANSPORTS:
            return False
        self._transports.append(transport)
        return True

    def transport_count(self):
        return len(self._transports)

    # --- status / boot sequence ---------------------------------------

    def set_status(self, status):
        """Replace the ``Status`` snapshot ``STATUS``/``POSE`` read from."""
        self._status = status

    def send_banner(self):
        self._broadcast_reliable(self._banner)

    def send_ready(self):
        """Boot sequence is always ``send_banner()`` then ``send_ready()``."""
        self._broadcast_reliable("READY")

    def _broadcast_reliable(self, text):
        for transport in self._transports:
            transport.send_reliable(text)

    # --- staged-action drains (SEED / DBG) -----------------------------

    def take_seed(self):
        """Pop and clear the pending SEED request, or ``None``."""
        seed = self._seed
        self._seed = None
        return seed

    def take_dbg_action(self):
        """Pop the oldest staged DBG action, or ``DbgAction(kind="none")``."""
        if self._dbg_count == 0:
            return DbgAction(kind="none")
        action = self._dbg_ring[self._dbg_head]
        self._dbg_head = (self._dbg_head + 1) % DBG_RING_DEPTH
        self._dbg_count -= 1
        return action

    def _push_dbg_action(self, action):
        if self._dbg_count >= DBG_RING_DEPTH:
            return  # drop-newest, matches pushDbgAction()
        slot = (self._dbg_head + self._dbg_count) % DBG_RING_DEPTH
        self._dbg_ring[slot] = action
        self._dbg_count += 1

    def _stage_seed(self, data, transport):
        """``"<x>,<y>,<heading>"`` (commas or spaces, all three
        required, signed). Any parse failure -> ``malformed_count``."""
        if not data or len(data) >= 64:
            self.malformed_count += 1
            return
        try:
            text = bytes(data).decode("ascii")
        except UnicodeError:
            self.malformed_count += 1
            return

        parsed = [0.0, 0.0, 0.0]
        cursor = 0
        n = len(text)
        for i in range(3):
            while cursor < n and (text[cursor] == "," or text[cursor] == " "):
                cursor += 1
            value, end = _parse_float_prefix(text, cursor)
            if value is None or end == cursor:
                self.malformed_count += 1
                return
            parsed[i] = value
            cursor = end

        self._seed = SeedRequest(parsed[0], parsed[1], parsed[2], transport)

    # --- command ring (binary verbs) ------------------------------------

    def pending_command_count(self):
        return self._cmd_count

    def _push_command(self, verb_name, payload):
        if self._cmd_count >= CMD_RING_DEPTH:
            self.commands_dropped_count += 1
            return
        slot = (self._cmd_head + self._cmd_count) % CMD_RING_DEPTH
        self._cmd_ring[slot] = (verb_name, payload)
        self._cmd_count += 1

    def _take_command(self):
        if self._cmd_count == 0:
            return None
        cmd = self._cmd_ring[self._cmd_head]
        self._cmd_head = (self._cmd_head + 1) % CMD_RING_DEPTH
        self._cmd_count -= 1
        return cmd

    # --- line dispatch ---------------------------------------------------

    def _dispatch_line(self, transport, line, now):
        """Mirrors ``dispatchLine()`` -- see the module docstring for the
        load-bearing ordering this implements."""
        if line[:1] in (b"#", b"!", b"?"):
            return  # relay control-plane line -- dropped, not even looked up

        colon = line.find(b":")
        if colon == -1:
            cmd_bytes = line
            if cmd_bytes[-1:] == b"\r":
                cmd_bytes = cmd_bytes[:-1]
            data_bytes = None
        else:
            cmd_bytes = line[:colon]
            data_bytes = line[colon + 1:]

        try:
            cmd_name = cmd_bytes.decode("ascii")
        except UnicodeError:
            cmd_name = None
        entry = msgs.VERB_BY_NAME.get(cmd_name) if cmd_name is not None else None
        if entry is None:
            self.malformed_count += 1
            return

        if entry.name == "TLM":
            self._tlm_reply_transport = transport
            self._tlm_action = TLM_FRAME if data_bytes is None else _classify_tlm_arg(data_bytes)
            return

        if entry.name == "SEED":
            self._stage_seed(data_bytes, transport)
            return

        if entry.name == "DBG":
            self._push_dbg_action(_classify_dbg_arg(data_bytes))
            return

        if entry.binary:
            frame = data_bytes if data_bytes is not None else b""
            payload = wire.decode_frame(frame, command=cmd_bytes)
            if payload is None:
                self.malformed_count += 1
                return
            self._push_command(entry.name, payload)
        else:
            self._dispatch_cleartext(entry.name, transport, now)

    def _dispatch_cleartext(self, verb_name, transport, now):
        if verb_name == "HELLO":
            transport.send_reliable(self._banner)
        elif verb_name == "PING":
            transport.send_reliable("PONG:t=%d" % (now,))
        elif verb_name == "ID":
            transport.send_reliable(self._id_line)
        elif verb_name == "VER":
            transport.send_reliable("VER:" + self._version)
        elif verb_name == "STATUS":
            self._send_status(transport)
        elif verb_name == "HELP":
            self._send_help(transport)
        elif verb_name == "POSE":
            self._send_pose(transport)
        else:
            self.malformed_count += 1

    def _send_status(self, transport):
        s = self._status
        tlm_str = {TLM_MODE_OFF: "off", TLM_MODE_AUTO: "auto", TLM_MODE_ON: "on"}.get(
            self.telemetry.mode, "auto"
        )
        transport.send_reliable(
            "STATUS:ready=%d:active=%d:connL=%d:connR=%d:otos=%d:wedge=%d:flags=0x%x:tlm=%s"
            % (
                1 if s.ready else 0,
                1 if s.active else 0,
                1 if s.wheel_left_connected else 0,
                1 if s.wheel_right_connected else 0,
                1 if s.otos_present else 0,
                1 if s.wedged else 0,
                s.flags,
                tlm_str,
            )
        )

    def _send_help(self, transport):
        tokens = []
        for entry in msgs.VERBS:
            if entry.binary and entry.name != "TLM":
                continue
            tokens.append("TLM[:NOW|ON|AUTO|OFF]" if entry.name == "TLM" else entry.name)
        transport.send_reliable("HELP:" + " ".join(tokens))

    def _send_pose(self, transport):
        s = self._status
        transport.send_reliable(
            "POSE:%d:%d:%d:%d:%d:%d:%d"
            % (s.otos_x, s.otos_y, s.otos_heading, s.enc_x, s.enc_y, s.enc_heading,
               1 if s.otos_present else 0)
        )

    def _send_tlm_reply(self, action):
        if self._tlm_reply_transport is None:
            return
        if action in (TLM_SET_OFF, TLM_SET_AUTO, TLM_SET_ON):
            self._send_status(self._tlm_reply_transport)
        elif action == TLM_UNRECOGNIZED:
            self._send_help(self._tlm_reply_transport)
        # TLM_NONE/TLM_FRAME: no reply here -- FRAME's reply is the emission pump() already triggered.

    # --- the pump ----------------------------------------------------------

    def _pump_once(self, now):
        for transport in self._transports:
            line = transport.read_line()
            if line is not None:
                self._dispatch_line(transport, line, now)
                return True
        return False

    def pump(self, now):
        """Bounded per-call work: mirrors ``Comms::pump()`` plus the
        ring-drain/TLM-reply/telemetry-emit sequence ``RobotLoop`` runs
        right after it in C++ (no separate module here). ``now``: int
        [ms], monotonic, caller-supplied."""
        for _ in range(PUMP_MAX_LINES):
            if not self._pump_once(now):
                break

        cmd = self._take_command()
        while cmd is not None:
            verb_name, payload = cmd
            result = self._dispatch.handle_command(verb_name, payload, now)
            if result is not None:
                corr_id, err_code = result
                self.telemetry.ack(corr_id, err_code)
            cmd = self._take_command()

        action = self._tlm_action
        self._tlm_action = TLM_NONE
        force = self.telemetry.apply_action(action)
        self.telemetry.emit(now, force)
        self._send_tlm_reply(action)


class PumpTimer:
    """Scheduled-pump plumbing (Sec 5): ``tick()`` only ever queues via
    ``micropython.schedule()``, never runs directly -- IRQ/fiber
    execution corrupts the heap (the REPL's stdin-wait patch is a
    separate C-level build patch, ``patches/``). On CPython ``tick()``
    calls ``pump()`` immediately and synchronously."""

    def __init__(self, comms, now_fn):
        self._comms = comms
        self._now_fn = now_fn

    def tick(self):
        if micropython is not None:
            micropython.schedule(self._pump_now, 0)
        else:
            self._pump_now(0)

    def _pump_now(self, _arg):
        self._comms.pump(self._now_fn())
