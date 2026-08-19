"""comms -- v5 protocol engine: dispatch order, ack ring, telemetry emit
policy, scheduled-pump plumbing.

Ported from radio-robot's ``src/firm/core/comms.cpp``/``comms.h`` (line
dispatch, verb interception, cleartext replies) and
``src/firm/core/telemetry.cpp``/``telemetry.h`` (ack ring, primary-frame
emit policy) -- see those files' own headers for the full firmware-parity
rationale. This port is this repo's own mirror, per PLAN.md M3 /
``docs/design/specification.md`` Sec 5/6: same dispatch ORDER, same ring
depths/packing, same emit-policy arithmetic; NOT a byte-for-byte binary
frame encoder, because ``msgs.py`` has no per-verb protobuf field tables
yet (its own docstring explains why -- that generator work is out of
scope this sprint). Binary verbs are validated (COBS+CRC, via
``wire.decode_frame()``) and handed to the firmware-layer dispatch
interface (below) as opaque payload bytes; a full ``CommandEnvelope``
decode is ticket 007's job once ``msgs.py`` grows field tables.

Dispatch order (mirrors ``Comms::dispatchLine()`` byte-for-byte -- see
``_dispatch_line()`` below):
    1. Relay control-plane lines (first byte ``#``/``!``/``?``) are
       dropped before anything else -- not even verb-looked-up.
    2. The verb name (up to the first ``':'``, or the whole line minus a
       trailing ``'\\r'``) is looked up in ``msgs.VERB_BY_NAME``. Unknown
       verb -> ``malformed_count`` and drop.
    3. TLM, SEED, DBG are intercepted HERE, before the binary/cleartext
       branch below -- even though TLM is flagged ``binary=True`` in
       ``msgs.VERBS`` (a telemetry REPLY frame is binary-framed; the
       INBOUND command name is a cleartext mode verb) and SEED/DBG are
       flagged ``binary=False`` (they still bypass the generic cleartext
       dispatch switch, which has no cases for them).
    4. Otherwise: a binary verb goes through COBS+CRC validation and is
       queued for the firmware-layer dispatch interface; a cleartext verb
       is answered immediately (HELLO/PING/ID/VER/STATUS/HELP/POSE).

Firmware-layer dispatch interface (per the sprint's Architecture Design
Rationale: comms.py must not call ``moddiffdrive``/firmware modules
directly, so THIS ticket's CPython loopback gate never needs the native
module, which cannot load under CPython at all). A dispatch object is
any duck-typed value exposing:

    handle_command(verb_name, payload, now) -> (corr_id, err_code) | None

``verb_name`` is the ASCII verb string (e.g. ``"WHEELS"``); ``payload``
is the COBS+CRC-VALIDATED but still schema-opaque bytes (no envelope
decode -- see the module docstring above); ``now`` is the same [ms]
integer ``Comms.pump()`` was called with. Returning a
``(corr_id, err_code)`` pair pushes that pair onto the ack ring
(``Telemetry.ack()``); returning ``None`` sends no ack for this command
(the only correct choice when a real ``corr_id`` cannot be recovered --
see ``NullDispatch`` below, the default when no dispatch is wired).
Ticket 007's ``motion.py``/``config.py`` back this interface with the
real ``moddiffdrive`` calls once a full envelope decode exists; THIS
ticket's own test backs it with a recording stub.

Transport contract (any object handed to ``Comms.add_transport()`` --
``src/radio_shim.py``'s ``RadioLink`` implements it, as does the
loopback test's own in-process pipe):

    read_line() -> bytes | None
        Non-blocking. Returns the next complete wire LINE's raw content
        (``<COMMAND>[':' <data>]``, trailing ``'\\n'`` delimiter already
        stripped), or ``None`` if none is ready.
    send(data: bytes) -> None
        Send one line's raw content; the transport appends its own
        trailing ``'\\n'`` (mirrors ``Hal::Transport::send()`` --
        ``Comms`` never appends a delimiter itself).
    send_reliable(text: str | bytes) -> None
        Same contract as ``send()`` for a cleartext line (accepts ``str``
        for caller convenience; ``Comms`` always passes ``str`` here).

Scheduled-pump plumbing (spec Sec 5): ``PumpTimer`` below wires a
periodic source to ``micropython.schedule(pump)`` per the landmine
ledger (fiber/IRQ Python execution corrupts the MicroPython heap -- Python
never runs from IRQ/fiber context, only ever from main context between
bytecodes). The REPL's own blocking-stdin-wait patch (so a queued pump
still runs while a student's REPL sits at a blocking read) is a
build-level (C) patch, not something reachable from this module -- see
``PumpTimer``'s own docstring.

MicroPython-only modules (``micropython``) are import-guarded so this
whole module imports and runs unmodified under CPython (this ticket's
own offline gate) -- see the top of the file.

Deviations from the radio-robot source, matching ``wire.py``'s own
precedent: no ``from __future__ import annotations``, no PEP 604/generic-
subscript type hints, no f-strings (project style: CLAUDE.md) -- every
function's shape is documented in its docstring instead.
"""

import msgs
import wire

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

# --- Ring depths / policy constants -- mirror radio-robot's core/comms.h
# and core/telemetry.h byte-for-byte (see this module's own docstring). ---

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

# Core::Comms::TlmAction, as plain strings (no `enum` -- host-only import
# MicroPython does not ship; matches msgs.py's own plain-class precedent).
TLM_NONE = "NONE"
TLM_FRAME = "FRAME"
TLM_SET_OFF = "SET_OFF"
TLM_SET_AUTO = "SET_AUTO"
TLM_SET_ON = "SET_ON"
TLM_UNRECOGNIZED = "UNRECOGNIZED"


def _parse_float_prefix(text, start):
    """Parse the LONGEST valid float-literal prefix of ``text`` starting at
    index ``start`` -- mirrors C's ``strtof()`` scanning contract (parses
    as much as is valid, does not require a delimiter to follow, never
    raises). Returns ``(value, end_index)``; on failure (no digits found)
    returns ``(None, start)`` -- the caller's ``end == start`` check is
    ``strtof``'s own "nothing consumed" signal (``end == cursor`` in the
    C++ source)."""
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
    """Parse the leading run of ASCII digits in ``text`` as an int,
    trailing junk ignored -- mirrors ``strtoul(text, nullptr, 10)``'s
    "parse what you can, 0 if nothing" contract. Never raises."""
    i = 0
    n = len(text)
    while i < n and "0" <= text[i] <= "9":
        i += 1
    if i == 0:
        return 0
    return int(text[:i])


def _classify_tlm_arg(data):
    """Mirrors ``classifyTlmArg()`` -- ``data`` (bytes, the text after
    ``TLM:``) case-insensitively matched against NOW/ON/AUTO/OFF, a
    trailing ``'\\r'`` stripped first. Returns one of the ``TLM_*``
    action constants; never raises (a non-ASCII argument is simply
    unrecognized)."""
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
    """Mirrors ``Core::Comms::DbgAction``. ``kind`` is one of: ``"none"``
    (the ring-empty sentinel ``take_dbg_action()`` returns -- distinct
    from ``"unrecognized"``, which means a DBG line WAS received but its
    sub-command didn't parse), ``"mark"``, ``"ping"``, ``"clear"``,
    ``"otos"``, ``"vmin"``, ``"asteady"``, ``"pos"``, ``"gain"``,
    ``"wedge"``, ``"unrecognized"``."""

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
    clear/otos/vmin/asteady/pos/gain/wedge). Returns a ``DbgAction``,
    ``kind="unrecognized"`` on any parse failure or empty/non-ASCII
    input -- matches the C++ default-constructed-to-kUnrecognized
    behavior for a received-but-unparseable DBG line."""
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
    """Mirrors ``Core::Comms::SeedRequest`` -- an external world-fix
    staged by a SEED command, drained by the firmware layer (ticket 007's
    ``motion.py``, mirroring ``RobotLoop::applySeed()``). ``x``/``y`` are
    [mm], ``heading`` is [rad] (matches the C++ struct's own units
    exactly). ``reply_transport`` is the transport the SEED command
    arrived on -- the firmware layer echoes an accepted seed back on it,
    same as ``RobotLoop::applySeed()``'s ``seed.reply->sendReliable()``;
    comms.py itself never sends that reply (it does not own odometry)."""

    def __init__(self, x, y, heading, reply_transport):
        self.x = x
        self.y = y
        self.heading = heading
        self.reply_transport = reply_transport


class Status:
    """Mirrors ``Core::Comms::Status`` -- data the firmware layer publishes
    each cycle via ``Comms.set_status()`` so ``STATUS``/``POSE`` replies
    have something to format. Plain mutable attributes (no ``dataclasses``
    -- host-only import); every field defaults exactly as the C++ struct
    does. ``tlm_mode`` is NOT read by ``Comms``'s own ``STATUS`` reply --
    that reads ``Comms.telemetry.mode`` directly (the two are always the
    same live value in this port, since ``Comms`` owns ``telemetry``
    itself; the C++ source keeps a synchronized COPY here only because
    ``Comms``/``Telemetry`` are separate peer objects there)."""

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
    """Default firmware-layer dispatch -- installed automatically when
    ``Comms`` is constructed without an explicit ``dispatch`` (this
    ticket's own CPython gate: no moddiffdrive, no motion.py/config.py
    exist yet). Every binary command is accepted onto the wire (COBS+CRC
    already validated before ``handle_command()`` is ever called) but
    produces NO ack: an ack needs a real ``corr_id``, which lives inside
    the still-opaque envelope bytes ``payload`` carries (see the module
    docstring -- ``msgs.py`` has no per-verb protobuf field tables yet),
    so there is nothing correct to ack with. Returning ``None`` is
    exactly ``Comms.pump()``'s 'skip the ack' signal -- the only honest
    behavior available with no firmware layer wired."""

    def handle_command(self, verb_name, payload, now):
        return None


class TelemetryPolicy:
    """Ack ring + primary-frame emit-policy decision, decoupled from
    frame CONTENT -- mirrors ``Core::Telemetry``'s ack ring
    (``pushAckRing``/``emitPrimary``'s ack half) and emit policy
    (``primaryDue``/``pendingAckDeliveries``/``emit``) exactly, but does
    NOT build a real 22-field TLM wire frame (that is ticket 007's
    ``src/telemetry.py`` -- see this module's own docstring for why: no
    protobuf field tables exist yet in ``msgs.py``). Named ``TelemetryPolicy``
    rather than ``Telemetry`` specifically to avoid colliding with that
    future module's name.

    Activity tracking is a deliberately simplified slice of
    ``Telemetry::update()``: the real C++ source derives ``kFlagActive``
    from a full ``RobotState``; this port exposes ``set_active(active,
    now)`` directly so the CPython loopback gate can drive "silent while
    parked" / "unsolicited while moving" without needing the firmware
    layer's state model (per the ticket's own "stubbed telemetry source"
    acceptance wording).

    ``emit_callback(now, acks)``, if given, is called exactly when a
    primary frame WOULD be sent -- ``acks`` is the list of currently-live
    packed ack ints (``corr_id << 4 | err_code``, oldest first). Building
    and broadcasting the real wire bytes for that frame is left to the
    caller (ticket 007+; see the module docstring) -- this class only
    decides WHEN and WHAT acks ride along.
    """

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
        """Simplified stand-in for ``Telemetry::update()``'s activity
        latch: ``active=True`` marks "moving now" and refreshes the coast
        window; ``active=False`` alone does not clear activity (the coast
        holdoff below still applies) -- matches ``kFlagActive`` /
        ``everMoved_`` / ``lastActivity_`` semantics exactly."""
        self._active = active
        if active:
            self._ever_moved = True
            self._last_activity = now

    def ack(self, corr_id, err_code):
        """Push one ``(corr_id, err_code)`` pair onto the ack ring, packed
        as ``corr_id << 4 | (err_code & 0xF)`` -- mirrors
        ``pushAckRing()``: depth 12, oldest entry evicted (ring advances)
        once full, new entry's resend counter starts at 0."""
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
        ``mode``; returns True iff ``action`` is ``TLM_FRAME`` (a forced
        immediate emission is owed)."""
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
        """Mirrors ``Telemetry::emit()``: default mode AUTO emits
        unsolicited frames only while ``_activity()`` is true (silent
        while parked); mode OFF never emits unsolicited; mode ON always
        does. Regardless of mode, a pending (not-yet-``ACK_REPEATS``-
        delivered) ack, or ``force=True`` (the TLM "NOW" verb), forces an
        emission -- but ALL of that is still gated by
        ``_primary_due()`` (the 25 ms floor)."""
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
    """v5 protocol engine -- mirrors ``Core::Comms``. Owns a set of
    transports (registration order is dispatch-tie-break order, exactly
    like ``addTransport()``'s own doc comment), the command ring, DBG/SEED
    staging, and a ``TelemetryPolicy`` instance (``self.telemetry``)."""

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
        """Register one more transport, in order. Returns False (does NOT
        raise) if ``MAX_TRANSPORTS`` are already registered -- a caller
        that ignores the return value silently loses a link, matching
        the C++ source's own ``[[nodiscard]]`` warning-not-error
        contract."""
        if len(self._transports) >= MAX_TRANSPORTS:
            return False
        self._transports.append(transport)
        return True

    def transport_count(self):
        return len(self._transports)

    # --- status / boot sequence ---------------------------------------

    def set_status(self, status):
        """Replace the ``Status`` snapshot ``STATUS``/``POSE`` read from --
        mirrors ``setStatus()``/``updateStatus()``, called by the firmware
        layer once per cycle."""
        self._status = status

    def send_banner(self):
        """Broadcast the (already-formatted) banner string to every
        registered transport -- mirrors ``sendBanner()``. Byte-frozen per
        spec Sec 6: whatever banner text the caller passes in, this sends
        it unmodified."""
        self._broadcast_reliable(self._banner)

    def send_ready(self):
        """Broadcast the literal ``"READY"`` -- mirrors ``sendReady()``.
        The boot sequence is always ``send_banner()`` then
        ``send_ready()``, matching ``RobotLoop``'s own boot preamble."""
        self._broadcast_reliable("READY")

    def _broadcast_reliable(self, text):
        for transport in self._transports:
            transport.send_reliable(text)

    # --- staged-action drains (SEED / DBG) -----------------------------

    def take_seed(self):
        """Pop and clear the pending SEED request, or ``None`` if none is
        staged -- mirrors ``takeSeed()``."""
        seed = self._seed
        self._seed = None
        return seed

    def take_dbg_action(self):
        """Pop the oldest staged DBG action, or ``DbgAction(kind="none")``
        if the ring is empty -- mirrors ``takeDbgAction()``."""
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
        """Mirrors ``stageSeed()``: ``"<x>,<y>,<heading>"``, commas or
        spaces, all three required and signed. Any parse failure (empty,
        oversized, non-ASCII, or an unparseable float) increments
        ``malformed_count`` and stages nothing."""
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
        # TLM_NONE / TLM_FRAME: no reply here -- kFrame's reply IS the
        # forced telemetry emission `pump()` already triggered.

    # --- the pump ----------------------------------------------------------

    def _pump_once(self, now):
        for transport in self._transports:
            line = transport.read_line()
            if line is not None:
                self._dispatch_line(transport, line, now)
                return True
        return False

    def pump(self, now):
        """Bounded per-call work, mirrors ``Comms::pump()`` PLUS the
        command-ring-drain / TLM-reply / telemetry-emit sequence
        ``RobotLoop`` runs immediately after it in the C++ source (there
        is no separate RobotLoop-equivalent module in this sprint's
        Python layer -- see the sprint architecture's module table:
        comms.py owns "dispatch order, ack ring, telemetry emit policy").

        ``now``: int [ms], monotonic, caller-supplied (this module has no
        clock of its own -- see ``PumpTimer`` for the MicroPython-side
        timer wiring)."""
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
    """MicroPython-only scheduled-pump plumbing (spec Sec 5): a periodic
    source calls ``tick()`` -- a hardware timer IRQ (deliberately NOT
    hard-coded to a specific peripheral API here; ticket 004's native
    module or a future ``machine.Timer`` may supply it, whichever a later
    ticket wires up) -- and ``tick()`` ONLY EVER queues the real work via
    ``micropython.schedule()``, never runs it directly: per PLAN.md's
    landmine ledger, Python execution from IRQ/fiber context corrupts the
    MicroPython heap, so ``pump()`` must always run later, from main
    context, between bytecodes. That is also what keeps the USB REPL
    live -- ``micropython.schedule()`` callbacks run between bytecodes
    regardless of what the foreground REPL is doing.

    The other half of Sec 5's contract -- patching the REPL's blocking
    stdin-wait loop so a queued callback still runs while a student's
    REPL sits at a blocking read -- is a C-level build patch
    (``patches/``), not something reachable from this Python class; see
    CLAUDE.md's build-machinery note.

    On CPython (``micropython`` unavailable) ``tick()`` degrades to
    calling ``pump()`` immediately and synchronously -- deterministic,
    no scheduler queue to drain, exactly what the offline loopback test
    wants."""

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
