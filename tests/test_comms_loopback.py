"""Sprint 007 ticket 006 gate: `src/core/comms.py`'s v6 shape under
CPython, driven via loopback transports against real
`core.protocol.ProtocolHandler`/`hardware.protocol_adapter.
ProtocolAdapter` instances (not stubs standing in for the wire codec --
those are already covered end to end by `tests/unit/
test_protocol_golden_vectors.py` and `tests/test_protocol_adapter.py`).
This file's own job is narrower: prove `comms.py`'s WIRING --

  - `add_transport()` builds and stores that transport's own handler;
  - two transports get two independent handlers sharing one adapter
    (sprint.md's Design Rationale -- not re-covered by ticket 003's
    isolation test, which exercises `protocol.py` alone, not
    `comms.py`'s construction of it);
  - `pump()` feeds each transport's pending line, terminator restored,
    to its own handler, one line per transport per call;
  - `send_banner()`/`send_ready()` broadcast to every live
    handler/transport;
  - the telemetry-emission cadence respects the shared adapter's TLM
    mode (off/auto/on).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import comms  # noqa: E402  (path must be set up first)
from core import protocol  # noqa: E402


# --- a small, self-contained fake Adapter (duck-typed, protocol.py's -----
# Adapter seam) -- this file tests comms.py's WIRING, not protocol.py's
# or protocol_adapter.py's own dispatch logic, so a local fake (matching
# this repo's per-file-fake convention, e.g. tests/test_motion.py's own
# _StubDiffDrive) keeps this test decoupled from those.

class _FakeAdapter(object):
    def __init__(self):
        self.name = "testbot"
        self.serial = "SN001"
        self.drivetrain = "differential"
        self.profile = "tovez"
        self.version = "6.0.0"
        self.now_value = 0
        self.status_ready = False
        self.status_active = False
        self.status_conn_left = False
        self.status_conn_right = False
        self.status_otos = False
        self.status_wedge = False
        self.status_flags = 0
        self.status_tlm = "auto"
        self._values = {}
        self.estop_calls = 0

    def identity(self):
        return (self.name, self.serial, self.drivetrain, self.profile,
                self.version)

    def now(self):
        return self.now_value

    def status(self):
        return (self.status_ready, self.status_active,
                self.status_conn_left, self.status_conn_right,
                self.status_otos, self.status_wedge, self.status_flags,
                self.status_tlm)

    def on_estop(self):
        self.estop_calls += 1

    def on_get(self, name):
        return self._values.get(name)

    def field_count(self):
        return len(self._values)

    def field_name(self, index):
        return sorted(self._values.keys())[index]

    def on_set(self, name, value, reply_id):
        self._values[name] = value
        return protocol.Result.OK

    def on_tlm(self, mode):
        self.status_tlm = mode.lower()
        return protocol.Result.OK

    def on_wheels(self, left, right, duration, reply_id):
        return protocol.Result.OK

    def on_stop(self, reply_id):
        return protocol.Result.OK


class _Pipe(object):
    """Buffers raw bytes and splits on '\\n' -- v6 lines are plain ASCII
    text, so no COBS/wire-codec demuxer is needed here (unlike v5's own
    loopback fixture, which built one over `wire.ByteStreamDemuxer`)."""

    def __init__(self):
        self._buf = b""

    def write_line(self, raw_line_bytes):
        self._buf += raw_line_bytes + b"\n"

    def read_line(self):
        if b"\n" not in self._buf:
            return None
        line, _, rest = self._buf.partition(b"\n")
        self._buf = rest
        return line


class LoopbackTransport(object):
    """Duck-typed Comms Transport (`read_line`/`send_reliable`)."""

    def __init__(self, inbound, outbound):
        self._inbound = inbound
        self._outbound = outbound

    def read_line(self):
        return self._inbound.read_line()

    def send(self, data):
        self._outbound.write_line(bytes(data))

    def send_reliable(self, text):
        if isinstance(text, str):
            text = text.encode("ascii")
        self.send(text)


def make_loopback_pair():
    """Returns (device_transport, host_transport) wired to each other."""
    device_to_host = _Pipe()
    host_to_device = _Pipe()
    device_transport = LoopbackTransport(inbound=host_to_device, outbound=device_to_host)
    host_transport = LoopbackTransport(inbound=device_to_host, outbound=host_to_device)
    return device_transport, host_transport


def make_comms(adapter=None):
    adapter = adapter if adapter is not None else _FakeAdapter()
    c = comms.Comms(adapter)
    device_transport, host_transport = make_loopback_pair()
    assert c.add_transport(device_transport) is True
    return c, host_transport, adapter, device_transport


# --- banner / boot / READY -----------------------------------------------

def test_banner_is_formatted_from_the_shared_adapters_identity():
    c, host, adapter, _device = make_comms()
    c.send_banner()
    assert host.read_line() == b"device NEZHA2 robot testbot SN001"
    assert host.read_line() is None


def test_send_ready_broadcasts_raw_ready_text():
    c, host, _adapter, _device = make_comms()
    c.send_ready()
    assert host.read_line() == b"READY"
    assert host.read_line() is None


def test_hello_replies_with_the_exact_banner():
    c, host, _adapter, _device = make_comms()
    host.send(b"HELLO")
    c.pump(0)
    assert host.read_line() == b"device NEZHA2 robot testbot SN001"


def test_ping_replies_with_pong_and_the_adapters_now_value():
    c, host, adapter, _device = make_comms()
    adapter.now_value = 1234
    host.send(b"PING #1")
    c.pump(0)
    assert host.read_line() == b"ack 1 0"
    assert host.read_line() == b"pong 1234"


def test_id_and_ver_replies():
    c, host, _adapter, _device = make_comms()
    host.send(b"ID #1")
    c.pump(0)
    assert host.read_line() == b"ack 1 0"
    assert host.read_line() == b"id differential tovez 6.0.0"

    host.send(b"VER #2")
    c.pump(0)
    assert host.read_line() == b"ack 2 0"
    assert host.read_line() == b"ver 6.0.0"


# --- add_transport()/pump() wiring ----------------------------------------

def test_add_transport_returns_false_once_max_transports_registered():
    c = comms.Comms(_FakeAdapter())
    for _ in range(comms.MAX_TRANSPORTS):
        _device, _host = make_loopback_pair()
        assert c.add_transport(_device) is True
    one_more, _host = make_loopback_pair()
    assert c.add_transport(one_more) is False
    assert c.transport_count() == comms.MAX_TRANSPORTS


def test_pump_reads_at_most_one_line_per_transport_per_call():
    c, host, _adapter, _device = make_comms()
    host.send(b"PING #1")
    host.send(b"PING #2")
    c.pump(0)
    # Only the FIRST queued line is drained this call -- no bounded
    # multi-line drain loop (module docstring).
    assert host.read_line() == b"ack 1 0"
    assert host.read_line() == b"pong 0"
    assert host.read_line() is None
    c.pump(0)
    assert host.read_line() == b"ack 2 0"
    assert host.read_line() == b"pong 0"
    assert host.read_line() is None


# --- two transports, two independent handlers, one shared adapter --------

def test_two_transports_get_two_independent_handlers_sharing_one_adapter():
    adapter = _FakeAdapter()
    c = comms.Comms(adapter)
    device_a, host_a = make_loopback_pair()
    device_b, host_b = make_loopback_pair()
    assert c.add_transport(device_a) is True
    assert c.add_transport(device_b) is True

    handler_a = c.handler_for(device_a)
    handler_b = c.handler_for(device_b)
    assert handler_a is not None
    assert handler_b is not None
    assert handler_a is not handler_b

    # SET through transport A is visible to a GET through transport B --
    # proof the two handlers share the SAME adapter (one robot, not one
    # per transport). "ok" is gone (protocol.md Sec 8.2, sprint 007
    # ticket 012's reliability-layer retarget) -- the ack alone is the
    # acceptance signal for a successful SET now.
    host_a.send(b"SET v_min 42.0 #1")
    c.pump(0)
    assert host_a.read_line() == b"ack 1 0"

    host_b.send(b"GET v_min #1")
    c.pump(0)
    assert host_b.read_line() == b"ack 1 0"
    assert host_b.read_line() == b"get v_min 42.000000"

    # Each handler's own partial-line buffer is independent: a partial
    # line fed to A (no terminator yet) must not affect B's own,
    # separately-buffered, complete line.
    handler_a.feed(b"PIN")  # no '\n' yet -- buffered, not dispatched
    host_b.send(b"PING #2")
    c.pump(0)
    assert host_b.read_line() == b"ack 2 0"
    assert host_b.read_line() == b"pong 0"
    assert host_a.read_line() is None  # A's partial line never completed


# --- send_banner()/send_ready() broadcast to every live handler ----------

def test_send_banner_and_send_ready_broadcast_to_every_transport():
    adapter = _FakeAdapter()
    c = comms.Comms(adapter)
    device_a, host_a = make_loopback_pair()
    device_b, host_b = make_loopback_pair()
    c.add_transport(device_a)
    c.add_transport(device_b)

    c.send_banner()
    c.send_ready()
    for host in (host_a, host_b):
        assert host.read_line() == b"device NEZHA2 robot testbot SN001"
        assert host.read_line() == b"READY"
        assert host.read_line() is None


# --- telemetry-emission cadence: gated on the shared adapter's TLM mode --
#
# 2026-08-21 retarget (protocol.md Sec 8.5, sprint 007 ticket 012):
# emit_telemetry() now ALSO piggybacks the current reliability line --
# "ack <expected_next-1> <last_done>" (no gap outstanding, always true
# here since none of these tests ever feed() a sequenced command) --
# after the thdr/t frame it accompanies, on every call. Each handler
# below starts a fresh sequence (expected_next=1, last_done=0), so the
# piggybacked line is "ack 0 0" every time.

def test_telemetry_off_emits_nothing_on_the_cadence():
    c, host, adapter, _device = make_comms()
    adapter.status_tlm = "off"
    adapter.status_active = True
    c.pump(0)
    assert host.read_line() is None


def test_telemetry_on_emits_every_cadence_tick_even_while_parked():
    c, host, adapter, _device = make_comms()
    adapter.status_tlm = "on"
    adapter.status_active = False
    c.pump(0)
    assert host.read_line() == b"thdr ready active connL connR otos wedge flags"
    assert host.read_line() == b"t 0 0 0 0 0 0 0"
    assert host.read_line() == b"ack 0 0"
    assert host.read_line() is None


def test_telemetry_auto_is_silent_while_parked_and_emits_while_active():
    c, host, adapter, _device = make_comms()
    adapter.status_tlm = "auto"
    adapter.status_active = False
    c.pump(0)
    assert host.read_line() is None

    adapter.status_active = True
    adapter.status_ready = True
    c.pump(0)
    assert host.read_line() == b"thdr ready active connL connR otos wedge flags"
    assert host.read_line() == b"t 1 1 0 0 0 0 0"
    assert host.read_line() == b"ack 0 0"
    assert host.read_line() is None


def test_telemetry_header_re_emits_once_per_handler_only_on_change():
    c, host, adapter, _device = make_comms()
    adapter.status_tlm = "on"
    c.pump(0)
    assert host.read_line() == b"thdr ready active connL connR otos wedge flags"
    assert host.read_line() == b"t 0 0 0 0 0 0 0"
    assert host.read_line() == b"ack 0 0"

    # Column SET is unchanged next cadence tick -- no repeated thdr.
    c.pump(0)
    assert host.read_line() == b"t 0 0 0 0 0 0 0"
    assert host.read_line() == b"ack 0 0"
    assert host.read_line() is None
