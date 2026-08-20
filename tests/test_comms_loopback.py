"""M3 gate: `src/core/comms.py` under CPython, driven via a loopback transport
against a host-side v5 client built on `src/core/wire.py`/`src/core/msgs.py`.

  - byte-exact banner/ack sequences;
  - dispatch order matches `dispatchLine()`: relay sigils dropped first;
    TLM/SEED/DBG intercepted before the binary branch;
  - ack-ring semantics: depth 12, `corr_id << 4 | err` packing, 3 repeats;
  - telemetry emit-policy defaults: AUTO, silent-while-parked, 25 ms
    period, pending-ack-forces-emission;
  - the comms.py-to-firmware-layer dispatch interface, exercised via a
    stub.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import comms  # noqa: E402  (path must be set up first)
from core import msgs  # noqa: E402
from core import wire  # noqa: E402


BANNER = "DEVICE:NEZHA2:robot:testbot:12345"
ID_LINE = "ID:nezha:testprofile:v0"


# --- loopback transport -----------------------------------------------
#
# Two `LoopbackTransport`s sharing a pair of `wire.ByteStreamDemuxer`s --
# stands in for the real serial/radio transport. Each side's
# `send()`/`send_reliable()` appends the '\n' delimiter itself (matching
# the Transport contract comms.py documents), and `read_line()` demuxes
# whatever the peer wrote.

class _Pipe:
    def __init__(self):
        self._demux = wire.ByteStreamDemuxer()
        self._pending = []

    def write_line(self, raw_line_bytes):
        self._pending.extend(self._demux.feed(raw_line_bytes + b"\n"))

    def read_line(self):
        if not self._pending:
            return None
        return self._pending.pop(0)


class LoopbackTransport:
    """Duck-typed Comms Transport (`read_line`/`send`/`send_reliable`)."""

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


def make_comms(dispatch=None, emit_callback=None):
    c = comms.Comms(BANNER, ID_LINE, dispatch=dispatch, version="test",
                     emit_callback=emit_callback)
    device_transport, host_transport = make_loopback_pair()
    assert c.add_transport(device_transport) is True
    return c, host_transport


# --- banner / boot / READY -- byte-exact -----------------------------

def test_banner_and_ready_are_byte_exact_and_in_order():
    c, host = make_comms()
    c.send_banner()
    c.send_ready()
    assert host.read_line() == BANNER.encode("ascii")
    assert host.read_line() == b"READY"
    assert host.read_line() is None


def test_hello_replies_with_the_exact_banner():
    c, host = make_comms()
    host.send(b"HELLO")
    c.pump(0)
    assert host.read_line() == BANNER.encode("ascii")


def test_ping_replies_with_pong_and_the_now_value():
    c, host = make_comms()
    host.send(b"PING")
    c.pump(1234)
    assert host.read_line() == b"PONG:t=1234"


def test_id_and_ver_cleartext_replies():
    c, host = make_comms()
    host.send(b"ID")
    c.pump(0)
    assert host.read_line() == ID_LINE.encode("ascii")

    host.send(b"VER")
    c.pump(0)
    assert host.read_line() == b"VER:test"


# --- dispatch order: relay sigils dropped first ------------------------

@pytest.mark.parametrize("sigil", [b"#", b"!", b"?"])
def test_relay_control_plane_lines_are_dropped_before_verb_lookup(sigil):
    c, host = make_comms()
    host.send(sigil + b"not-a-real-verb-at-all")
    c.pump(0)
    # Dropped silently -- no reply, and NOT counted as malformed (it is
    # never even looked up as a verb).
    assert host.read_line() is None
    assert c.malformed_count == 0


def test_unknown_verb_is_malformed_not_a_relay_line():
    c, host = make_comms()
    host.send(b"NOTAVERB:xyz")
    c.pump(0)
    assert host.read_line() is None
    assert c.malformed_count == 1


# --- dispatch order: TLM/SEED/DBG intercepted before the binary branch --

def test_tlm_is_intercepted_before_the_binary_branch():
    """TLM is flagged binary=True in msgs.VERBS, but the inbound command
    is intercepted before dispatchLine()'s `if entry.binary` branch --
    non-COBS garbage after `TLM:` must NOT bump malformed_count."""
    assert msgs.VERB_BY_NAME["TLM"].binary is True
    c, host = make_comms()
    host.send(b"TLM:this is not cobs data at all!!")
    c.pump(0)
    assert c.malformed_count == 0
    assert c.pending_command_count() == 0


def test_tlm_now_forces_an_immediate_telemetry_emission():
    emitted = []
    c, host = make_comms(emit_callback=lambda now, acks: emitted.append((now, acks)))
    host.send(b"TLM:NOW")
    c.pump(100)
    assert emitted == [(100, [])]


def test_tlm_on_off_auto_reply_with_status():
    c, host = make_comms()
    host.send(b"TLM:ON")
    c.pump(0)
    line = host.read_line()
    assert line is not None
    assert line.startswith(b"STATUS:")
    assert c.telemetry.mode == comms.TLM_MODE_ON

    host.send(b"TLM:OFF")
    c.pump(0)
    assert host.read_line().startswith(b"STATUS:")
    assert c.telemetry.mode == comms.TLM_MODE_OFF


def test_tlm_unrecognized_arg_replies_with_help():
    c, host = make_comms()
    host.send(b"TLM:bogus")
    c.pump(0)
    line = host.read_line()
    assert line is not None
    assert line.startswith(b"HELP:")


def test_seed_is_intercepted_before_the_binary_branch():
    """SEED is flagged binary=False, but also not routed through the
    generic cleartext dispatch switch -- intercepted earlier still,
    like TLM/DBG."""
    assert msgs.VERB_BY_NAME["SEED"].binary is False
    c, host = make_comms()
    host.send(b"SEED:10,-20,1.5")
    c.pump(0)

    assert c.malformed_count == 0
    assert c.pending_command_count() == 0
    seed = c.take_seed()
    assert seed is not None
    assert seed.x == 10.0
    assert seed.y == -20.0
    assert seed.heading == 1.5
    # A second take (nothing staged) returns None -- take clears it.
    assert c.take_seed() is None


def test_seed_accepts_space_separated_form_too():
    c, host = make_comms()
    host.send(b"SEED:1 2 3")
    c.pump(0)
    seed = c.take_seed()
    assert (seed.x, seed.y, seed.heading) == (1.0, 2.0, 3.0)


def test_seed_malformed_argument_is_counted_and_stages_nothing():
    c, host = make_comms()
    host.send(b"SEED:not,numbers,here")
    c.pump(0)
    assert c.malformed_count == 1
    assert c.take_seed() is None


def test_dbg_is_intercepted_before_the_binary_branch():
    assert msgs.VERB_BY_NAME["DBG"].binary is False
    c, host = make_comms()
    host.send(b"DBG:ping")
    c.pump(0)

    assert c.malformed_count == 0
    assert c.pending_command_count() == 0
    action = c.take_dbg_action()
    assert action.kind == "ping"
    # Ring now empty -- the "no action staged" sentinel is kind="none".
    assert c.take_dbg_action().kind == "none"


def test_dbg_wedge_and_gain_subcommands_parse():
    c, host = make_comms()
    host.send(b"DBG:wedge left 500")
    c.pump(0)
    action = c.take_dbg_action()
    assert action.kind == "wedge"
    assert action.port == 1
    assert action.duration == 500

    host.send(b"DBG:gain 1.5 2.5")
    c.pump(0)
    action = c.take_dbg_action()
    assert action.kind == "gain"
    assert action.value == 1.5
    assert action.value2 == 2.5


# --- binary verbs: COBS+CRC validated, dispatched through the stub -----

def _binary_line(verb, payload):
    command = verb.encode("ascii")
    body = wire.encode_frame(payload, command=command)
    return command + b":" + body


class RecordingDispatch:
    """The firmware-layer dispatch stub this gate backs the interface
    with -- motion.py/config.py back it with the real moddiffdrive
    calls; here it's a recording stub."""

    def __init__(self, ack=None):
        self.calls = []
        self._ack = ack

    def handle_command(self, verb_name, payload, now):
        self.calls.append((verb_name, payload, now))
        return self._ack


def test_binary_verb_round_trips_through_wire_py_and_reaches_the_dispatch_stub():
    dispatch = RecordingDispatch(ack=(7, 0))
    c, host = make_comms(dispatch=dispatch)
    payload = b"\x01\x02\x03\x04"
    host.send(_binary_line("WHEELS", payload))
    c.pump(0)

    assert dispatch.calls == [("WHEELS", payload, 0)]
    assert c.malformed_count == 0


def test_binary_verb_with_corrupt_crc_is_malformed_and_never_reaches_dispatch():
    dispatch = RecordingDispatch()
    c, host = make_comms(dispatch=dispatch)
    command = b"WHEELS"
    body = bytearray(wire.encode_frame(b"\x01\x02", command=command))
    body[0] ^= 0xFF  # corrupt the COBS-encoded bytes
    host.send(command + b":" + bytes(body))
    c.pump(0)

    assert dispatch.calls == []
    assert c.malformed_count == 1


def test_dispatch_stub_return_value_pushes_an_ack():
    dispatch = RecordingDispatch(ack=(3, 1))
    emitted = []
    c, host = make_comms(dispatch=dispatch, emit_callback=lambda now, acks: emitted.append(acks))
    host.send(_binary_line("STOP", b""))
    c.pump(0)  # dispatch runs, ack queued; primaryDue() -> first-ever emit
    assert emitted
    assert emitted[-1] == [(3 << 4) | 1]


def test_null_dispatch_is_the_default_and_sends_no_ack():
    """No firmware layer wired -- NullDispatch must not crash, and must
    not fabricate an ack."""
    emitted = []
    c, host = make_comms(emit_callback=lambda now, acks: emitted.append(acks))
    host.send(_binary_line("STOP", b""))
    c.pump(0)
    assert c.malformed_count == 0
    assert emitted == []  # nothing forced an emission -- and definitely no ack

    # Force TLM:NOW to inspect the ack list NullDispatch leaves behind:
    # still empty.
    host.send(b"TLM:NOW")
    c.pump(1)
    assert emitted == [[]]


# --- ack-ring semantics: depth 12, corr_id<<4|err packing, 3 repeats ---

def test_ack_packing_formula_is_corr_id_shifted_4_or_err():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(acks))
    tp.ack(corr_id=5, err_code=2)
    tp.emit(now=0, force=True)
    assert emitted == [[(5 << 4) | 2]]


def test_ack_ring_depth_is_12_oldest_evicted():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(acks))
    for corr_id in range(15):  # 15 > depth (12)
        tp.ack(corr_id=corr_id, err_code=0)
    tp.emit(now=0, force=True)
    assert len(emitted[-1]) == 12
    # Oldest 3 (corr_id 0, 1, 2) were evicted -- the ring holds 3..14.
    expected = [(cid << 4) for cid in range(3, 15)]
    assert emitted[-1] == expected


def test_ack_repeats_exactly_3_then_stops_forcing_unsolicited_emission():
    """mode OFF, never active -- a pending ack forces exactly
    ACK_REPEATS emissions, then stops forcing them."""
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append((now, acks)))
    tp.mode = comms.TLM_MODE_OFF
    tp.ack(corr_id=9, err_code=0)

    now = 0
    for _ in range(comms.ACK_REPEATS):  # 3 forced-by-pending-ack emissions
        tp.emit(now=now, force=False)
        now += comms.PRIMARY_PERIOD_MS

    assert len(emitted) == comms.ACK_REPEATS
    for _, acks in emitted:
        assert acks == [9 << 4]

    # 4th call: repeats exhausted, nothing forces this emission -- silent.
    tp.emit(now=now, force=False)
    assert len(emitted) == comms.ACK_REPEATS  # unchanged


# --- telemetry emit policy: AUTO default, silent-while-parked, 25 ms ---

def test_default_mode_is_auto():
    tp = comms.TelemetryPolicy()
    assert tp.mode == comms.TLM_MODE_AUTO


def test_auto_mode_is_silent_while_parked():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(now))
    # Never set_active(True) -- robot has never moved.
    tp.emit(now=0)
    assert emitted == []


def test_auto_mode_emits_unsolicited_while_active():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(now))
    tp.set_active(True, now=0)
    tp.emit(now=0)
    assert emitted == [0]


def test_primary_period_is_25ms_between_unsolicited_emissions():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(now))
    tp.set_active(True, now=0)
    tp.emit(now=0)
    assert emitted == [0]

    # Still active, but inside the 25 ms floor -- must not re-emit.
    tp.emit(now=24)
    assert emitted == [0]

    # At exactly 25 ms, due again.
    tp.emit(now=25)
    assert emitted == [0, 25]


def test_pending_ack_forces_emission_even_when_off_and_parked():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(now))
    tp.mode = comms.TLM_MODE_OFF
    tp.ack(corr_id=1, err_code=0)
    tp.emit(now=0)
    assert emitted == [0]  # forced by the pending (unsent) ack


def test_force_true_bypasses_mode_and_activity_but_not_the_period_floor():
    emitted = []
    tp = comms.TelemetryPolicy(emit_callback=lambda now, acks: emitted.append(now))
    tp.mode = comms.TLM_MODE_OFF
    tp.emit(now=0, force=True)
    assert emitted == [0]
    # Still inside the 25 ms floor -- even force=True must respect it.
    tp.emit(now=1, force=True)
    assert emitted == [0]


# --- pump() bounded work / dispatch-interface stub, end to end ---------

def test_pump_processes_multiple_queued_lines_in_one_call():
    c, host = make_comms()
    host.send(b"PING")
    host.send(b"ID")
    c.pump(0)
    assert host.read_line() == b"PONG:t=0"
    assert host.read_line() == ID_LINE.encode("ascii")
    assert host.read_line() is None
