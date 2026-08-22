"""comms -- v6 protocol engine: transport registration and the
scheduled-pump loop over one ``core.protocol.ProtocolHandler`` instance
PER registered transport, all sharing one ``hardware.protocol_adapter.
ProtocolAdapter`` instance (sprint 007 ticket 006 -- the hard cutover;
sprint.md's Design Rationale is the load-bearing decision this module
implements, not just tidies around -- read that section before
touching this file).

Retired WHOLE by this same ticket, not left dead-code-in-place
(sprint.md's own "RETIRED" component-diagram node): the v5 dispatch
order (``_dispatch_line()``/``_dispatch_cleartext()``), the ack ring,
``TelemetryPolicy``, ``DbgAction``/``SeedRequest``/``Status``, and
every ``_send_*``/``_classify_*``/``_parse_*`` helper that existed
only to serve that binary/cleartext switch. ``src/core/wire.py``/
``src/core/msgs.py`` retire in the same ticket -- nothing below
imports either.

Transport contract (``Comms.add_transport()`` -- ``radio_shim.
RadioLink``, ``wifi_at.WifiAtLink``, the loopback tests' in-process
pipe), unchanged from v5:

    read_line() -> bytes | None      next line, '\\n' stripped
    send_reliable(text: str | bytes) -> None   appends its OWN '\\n'

``_TransportSink`` bridges ``protocol.Sink``'s "one ``write()`` per
line, trailing '\\n' INCLUDED" contract onto ``send_reliable()``'s
"appends its own '\\n'" contract -- stripping the one
``ProtocolHandler`` already added avoids doubling it.

``send_banner()`` iterates every live handler, calling its own
``send_banner()`` (each formats "device NEZHA2 robot <name> <serial>"
from the shared adapter's ``identity()`` on demand -- ``comms.py``
holds no banner string of its own any more, unlike v5). ``send_ready()``
stays a raw, handler-bypassing broadcast of the literal text "READY":
v6's 12-verb scope (``protocol.py``'s own module docstring) defines no
READY verb, and ``ProtocolHandler`` has no unsolicited-emission method
for one (unlike ``send_banner()``) -- READY is v5's boot-handshake
convention, kept working here ONLY because ``wifi_at.pump()``'s
READY-on-new-peer-edge call (``comms.send_ready()``) is a real,
in-scope surface this ticket must not break, not because v6's wire
grammar defines a READY line of its own. Mirrors the old
``_broadcast_reliable()`` shape for exactly this one case.

Telemetry emission on the scheduled cadence iterates every handler
(sprint.md's Design Rationale), gated on the shared adapter's own
``status()``-reported ``tlm`` mode ("off" never emits, "on" always
emits, "auto" emits only while ``status().active`` -- v5's
``TelemetryPolicy``'s 2000 ms post-motion coast-holdoff grace window
is NOT reproduced, a deliberate smallest-choice simplification, not an
oversight) so that ``TLM:OFF`` actually silences the stream (the exact
bench regression class ``clasi/issues/done/tlm-stream-ignores-tlm-off.
md`` names) rather than flipping a mode flag nothing reads. The column
set itself is this ticket's own call -- underspecified above the
ticket level (sprint.md records the one-handler-per-transport/shared-
adapter decision, not a column-projection contract): a small
projection of ``status()``'s own fields, chosen because it is the only
telemetry-shaped data already exposed through the Adapter seam
``protocol.py`` defines. ``src/core/telemetry.py``'s full 22-field
frame builder is a SEPARATE, still-unwired module (built for v5's own
``emit_callback`` contract, which this cutover retires) and is
deliberately left untouched here -- wiring it to v6's
``emit_telemetry(columns)`` contract is future work, not this ticket's.
"""

from core import protocol

try:
    import micropython
except ImportError:  # CPython (tests), or a MicroPython build without it
    micropython = None

__all__ = [
    "Comms",
    "PumpTimer",
]

MAX_TRANSPORTS = 4  # Core::Comms::kMaxTransports -- unchanged from v5


class _TransportSink(protocol.Sink):
    """Bridges one transport's ``send_reliable()`` onto
    ``protocol.Sink``'s ``write(text)`` contract -- see module
    docstring for why the trailing '\\n' is stripped here rather than
    doubled."""

    def __init__(self, transport):
        self._transport = transport

    def write(self, text):
        if text[-1:] == "\n":
            text = text[:-1]
        self._transport.send_reliable(text)


def _telemetry_columns(adapter):
    """A minimal projection of ``adapter.status()`` into
    ``protocol.ProtocolHandler.emit_telemetry()``'s ``(name, value,
    hex)`` column shape -- see module docstring for why this, and not
    ``telemetry.py``'s full frame, is what this ticket wires. ``tlm``
    (a string) is not itself a column -- it already gates whether this
    function is even called (see ``Comms._emit_telemetry_cadence()``)."""
    (ready, active, conn_left, conn_right, otos, wedge, flags,
     _tlm) = adapter.status()
    return (
        ("ready", 1 if ready else 0, False),
        ("active", 1 if active else 0, False),
        ("connL", 1 if conn_left else 0, False),
        ("connR", 1 if conn_right else 0, False),
        ("otos", 1 if otos else 0, False),
        ("wedge", 1 if wedge else 0, False),
        ("flags", flags, True),
    )


class Comms(object):
    """Owns the registered transports (registration order is dispatch-
    tie-break order, unchanged from v5) and, per transport, one
    ``protocol.ProtocolHandler`` sharing ``adapter`` -- the SAME
    ``ProtocolAdapter`` instance for every transport (sprint.md's
    Design Rationale: "one robot, not one per transport")."""

    def __init__(self, adapter):
        self._adapter = adapter
        self._handlers = []  # [(transport, ProtocolHandler), ...]

    # --- transport registration -------------------------------------

    def add_transport(self, transport):
        """Register one more transport, in order, and construct its
        OWN ``ProtocolHandler`` right here, sharing ``self._adapter`` --
        this is what replaces v5's single shared dispatch switch.
        Returns ``False`` (never raises) once ``MAX_TRANSPORTS`` are
        registered."""
        if len(self._handlers) >= MAX_TRANSPORTS:
            return False
        handler = protocol.ProtocolHandler(self._adapter, _TransportSink(transport))
        self._handlers.append((transport, handler))
        return True

    def transport_count(self):
        return len(self._handlers)

    def handler_for(self, transport):
        """The ``ProtocolHandler`` ``add_transport()`` built for
        ``transport``, or ``None`` if it was never registered -- lets a
        caller (a test, or a future per-transport diagnostic) reach a
        specific handler's own state directly."""
        for registered_transport, handler in self._handlers:
            if registered_transport is transport:
                return handler
        return None

    # --- unsolicited emissions --------------------------------------

    def send_banner(self):
        for _transport, handler in self._handlers:
            handler.send_banner()

    def send_ready(self):
        """Boot sequence is always ``send_banner()`` then
        ``send_ready()`` (unchanged from v5) -- see module docstring
        for why this one broadcasts raw text instead of going through
        a handler."""
        for transport, _handler in self._handlers:
            transport.send_reliable("READY")

    # --- the pump ----------------------------------------------------

    def pump(self, now):
        """One line per transport per call (mirrors the ticket's own
        "for each (transport, handler) pair" wiring -- no bounded
        multi-line drain loop the way v5's ``PUMP_MAX_LINES`` needed,
        since ``handler.feed()`` has no ring of its own to overflow),
        then the telemetry-emission cadence. ``now``: int [ms] --
        accepted for ``PumpTimer``'s call-shape compatibility
        (unchanged by this ticket); nothing below currently needs it,
        since ``ProtocolAdapter.now()`` is what ``PING`` actually
        reads."""
        for transport, handler in self._handlers:
            line = transport.read_line()
            if line is not None:
                handler.feed(line + b"\n")
        self._emit_telemetry_cadence()

    def _emit_telemetry_cadence(self):
        (_ready, active, _conn_left, _conn_right, _otos, _wedge,
         _flags, tlm) = self._adapter.status()
        if tlm == "off":
            return
        if tlm == "auto" and not active:
            return
        columns = _telemetry_columns(self._adapter)
        for _transport, handler in self._handlers:
            handler.emit_telemetry(columns)


class PumpTimer(object):
    """Scheduled-pump plumbing (unchanged from v5, Sec 5): ``tick()``
    only ever queues via ``micropython.schedule()``, never runs
    directly -- IRQ/fiber execution corrupts the heap (the REPL's
    stdin-wait patch is a separate C-level build patch, ``patches/``).
    On CPython ``tick()`` calls ``pump()`` immediately and
    synchronously."""

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
