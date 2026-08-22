"""M4 gate (offline legs): `src/core/wifi_at.py`'s AT state machine against a
scripted fake serial object -- the mock-serial oracle sequences mirror
`reference/modrobot/wifi_stdio.cpp`'s own AT dialogue (join/CIPMUX/UDP
setup):

  - `CIPMUX=1` sequencing (issued, in order, before the join completes);
  - one-`CIPSEND`-per-datagram, never per-character;
  - the >=50 ms TLM-throttle timer logic;
  - READY-on-new-peer-edge handling.

No hardware, no radio, no WiFi module required -- `FakeSerial` below is
a scripted software stand-in.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import wifi_at  # noqa: E402  (path must be set up first)


SSID = "testssid"
PASSWORD = "testpass"


class FakeSerial:
    """Scripted fake WiFi module -- the wifi_stdio.cpp AT-sequence
    oracle, driven by a lookup table keyed on each command's own prefix
    (before the first '='), default reply "OK" for anything unlisted.
    Records every write() call's raw bytes (`self.writes`) so tests can
    assert command ordering and per-call granularity."""

    def __init__(self, replies=None):
        self._replies = dict(replies or {})
        self._rx = bytearray()
        self.writes = []
        self._awaiting_payload = False
        self.baudrate = None

    # -- WifiAtLink's AT byte-pipe contract --------------------------
    def init(self, baudrate):
        self.baudrate = baudrate

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        self._handle_write(data)
        return len(data)

    def any(self):
        return len(self._rx)

    def read(self, n):
        n = min(n, len(self._rx))
        chunk = bytes(self._rx[:n])
        del self._rx[:n]
        return chunk

    # -- test/scripting helpers --------------------------------------
    def queue(self, text_or_bytes):
        if isinstance(text_or_bytes, str):
            text_or_bytes = text_or_bytes.encode("ascii")
        self._rx.extend(text_or_bytes)

    def _handle_write(self, data):
        if self._awaiting_payload:
            # Payload write following a '>' prompt -- one SEND OK per
            # payload write.
            self._awaiting_payload = False
            self.queue("SEND OK\r\n")
            return
        text = data.decode("ascii", "replace")
        line = text.strip("\r\n")
        if line.startswith("AT+CIPSEND="):
            self._awaiting_payload = True
            self.queue(">")
            return
        key = line.split("=", 1)[0]
        if line in self._replies:
            reply = self._replies[line]
        else:
            reply = self._replies.get(key, "OK")
        if reply is None:
            return  # simulated no-reply (timeout path)
        self.queue(reply + "\r\n")


def default_replies():
    return {
        "AT+RST": "ready",
        "AT+CWJAP?": "+CWJAP:\"%s\"" % SSID,  # already-joined, auto-rejoin path
    }


def make_link(replies=None, repl_hook=None):
    serial = FakeSerial(default_replies() if replies is None else replies)
    link = wifi_at.WifiAtLink(serial, SSID, PASSWORD, repl_hook=repl_hook)
    return link, serial


def run_ticks(link, start_now=0, count=200, step_ms=5):
    now = start_now
    for _ in range(count):
        link.service(now)
        now += step_ms
    return now


def run_until_ready(link, start_now=0, max_ticks=500, step_ms=5):
    now = start_now
    for _ in range(max_ticks):
        link.service(now)
        if link.state() == "ready":
            return now
        now += step_ms
    raise AssertionError("link never reached READY within %d ticks" % max_ticks)


def build_ipd(link_id, ip, port, payload):
    header = "+IPD,%d,%d,\"%s\",%d:" % (link_id, len(payload), ip, port)
    return header.encode("ascii") + payload


# --- CIPMUX=1 sequencing -------------------------------------------------

def test_configure_sequence_issues_cipmux_1_before_join_and_server():
    link, serial = make_link()
    run_until_ready(link)

    # Extract AT command lines only (drop CIPSEND payload writes).
    commands = [w.split(b"\r\n")[0] for w in serial.writes if w.startswith(b"AT")]

    assert b"AT+CIPMUX=1" in commands
    assert b"AT+CWJAP?" in commands
    assert b"AT+CIPSERVER=1,7654" in commands

    cipmux_index = commands.index(b"AT+CIPMUX=1")
    join_index = commands.index(b"AT+CWJAP?")
    server_index = commands.index(b"AT+CIPSERVER=1,7654")

    # CIPMUX=1 must precede the join query and the server/UDP bring-up
    # -- mirrors wifi_stdio.cpp's own ordering.
    assert cipmux_index < join_index < server_index

    # Full step order matches _CONFIGURE_STEPS (RST first).
    assert commands[0] == b"AT+RST"
    assert commands.index(b"AT+CIPMUX=1") > commands.index(b"AT+CWMODE=1")


def test_reaches_ready_and_opens_v5_udp_socket():
    link, serial = make_link()
    run_until_ready(link)
    assert link.state() == "ready"
    commands = [w.split(b"\r\n")[0] for w in serial.writes if w.startswith(b"AT")]
    assert any(cmd.startswith(b"AT+CIPSTART=4,\"UDP\"") for cmd in commands)


def test_debug_trace_records_last_command_and_raw_reply_lines():
    """Bench-diagnostic AT trace (sprint 007 ticket 009): `state()`
    alone did not explain a live divergence hit on tovez (link reports
    "ready" yet the bench Mac never sees the device on the network) --
    `debug_trace()` is the fallback that exposes the module's own raw
    words. Confirm it actually captures the CWJAP query and its reply."""
    link, serial = make_link()
    run_until_ready(link)
    last_command, lines = link.debug_trace()
    assert last_command is not None
    assert any("CWJAP" in line for line in lines)


def test_no_at_command_is_ever_sent_one_byte_at_a_time():
    """Landmine: per-char AT sends flood the module. Every write() call
    during bring-up must carry a whole command/payload, never a single
    byte."""
    link, serial = make_link()
    run_until_ready(link)
    for chunk in serial.writes:
        assert len(chunk) > 1, "a write() call sent only %r -- per-character send" % (chunk,)


# --- one CIPSEND per datagram, never per-character -----------------------

def test_one_cipsend_per_datagram_never_per_character():
    link, serial = make_link()
    run_until_ready(link)

    # An inbound +IPD frame on the v5 link teaches WifiAtLink the peer
    # address.
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"HELLO"))
    run_ticks(link, count=5)
    assert link.read_line() == b"HELLO"

    writes_before = len(serial.writes)
    payload = b"TLM:" + (b"X" * 40)  # a representative multi-byte v5 line
    link.send(payload)
    run_ticks(link, count=20)

    new_writes = serial.writes[writes_before:]
    # Exactly two write() calls per datagram: AT+CIPSEND, then payload.
    assert len(new_writes) == 2, "expected exactly 2 write() calls for one datagram, got %r" % (new_writes,)
    command_write, payload_write = new_writes
    assert command_write.startswith(b"AT+CIPSEND=4,%d,\"10.0.0.5\",9999" % len(payload))
    assert payload_write == payload
    assert len(command_write) > 1
    assert len(payload_write) == len(payload) > 1


def test_send_with_no_known_peer_is_dropped_not_queued():
    link, serial = make_link()
    run_until_ready(link)
    writes_before = len(serial.writes)
    link.send(b"SHOULD:NOT:SEND")
    run_ticks(link, count=10)
    assert serial.writes[writes_before:] == []


def test_multiple_sends_each_get_their_own_single_cipsend():
    link, serial = make_link()
    run_until_ready(link)
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"HI"))
    run_ticks(link, count=5)
    link.read_line()

    writes_before = len(serial.writes)
    link.send(b"FIRST")
    run_ticks(link, count=20)
    link.send(b"SECOND")
    run_ticks(link, count=20)

    new_writes = serial.writes[writes_before:]
    assert len(new_writes) == 4  # 2 datagrams x (command, payload)
    assert new_writes[1] == b"FIRST"
    assert new_writes[3] == b"SECOND"


# --- >=50 ms TLM-throttle timer logic ------------------------------------

def test_tlm_throttle_allows_first_call():
    throttle = wifi_at.TlmThrottle()
    assert throttle.allow(0) is True


def test_tlm_throttle_blocks_within_window():
    throttle = wifi_at.TlmThrottle()
    assert throttle.allow(1000) is True
    assert throttle.allow(1010) is False
    assert throttle.allow(1049) is False


def test_tlm_throttle_allows_at_exactly_the_floor():
    throttle = wifi_at.TlmThrottle()
    assert throttle.allow(1000) is True
    assert throttle.allow(1050) is True  # exactly 50ms later


def test_tlm_throttle_resets_window_on_each_allowed_call():
    throttle = wifi_at.TlmThrottle()
    assert throttle.allow(0) is True
    assert throttle.allow(50) is True
    assert throttle.allow(60) is False  # only 10ms since the last ALLOWED call
    assert throttle.allow(100) is True  # 50ms since the last allowed call (50)


def test_tlm_throttle_custom_interval():
    throttle = wifi_at.TlmThrottle(min_interval_ms=100)
    assert throttle.allow(0) is True
    assert throttle.allow(99) is False
    assert throttle.allow(100) is True


def test_send_telemetry_drops_when_throttled():
    link, serial = make_link()
    run_until_ready(link)
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"HI"))
    run_ticks(link, count=5)
    link.read_line()

    throttle = wifi_at.TlmThrottle()
    writes_before = len(serial.writes)

    link.send_telemetry(b"TLM:FRAME1", throttle, now=0)
    run_ticks(link, start_now=0, count=20)
    first_batch = len(serial.writes) - writes_before
    assert first_batch == 2  # command + payload, one datagram sent

    writes_before2 = len(serial.writes)
    link.send_telemetry(b"TLM:FRAME2", throttle, now=10)  # only 10ms later -- throttled
    run_ticks(link, start_now=100, count=20)
    assert serial.writes[writes_before2:] == []

    link.send_telemetry(b"TLM:FRAME3", throttle, now=60)  # >=50ms since the allowed send at 0
    run_ticks(link, start_now=200, count=20)
    assert len(serial.writes) - writes_before2 == 2


# --- READY-on-new-peer-edge handling --------------------------------------

class _StubComms:
    def __init__(self):
        self.ready_count = 0

    def send_ready(self):
        self.ready_count += 1


def test_poll_new_peer_edge_fires_once_for_a_new_peer():
    link, serial = make_link()
    run_until_ready(link)

    assert link.poll_new_peer_edge() is False  # no peer yet

    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"HELLO"))
    run_ticks(link, count=5)

    assert link.poll_new_peer_edge() is True
    # The edge is consumed -- a second poll with no NEW peer is False.
    assert link.poll_new_peer_edge() is False


def test_poll_new_peer_edge_fires_again_for_a_different_peer():
    link, serial = make_link()
    run_until_ready(link)

    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"A"))
    run_ticks(link, count=5)
    assert link.poll_new_peer_edge() is True

    # A second datagram from the SAME peer is not a new edge.
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"B"))
    run_ticks(link, count=5)
    assert link.poll_new_peer_edge() is False

    # A datagram from a DIFFERENT peer address IS a new edge.
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.7", 1234, b"C"))
    run_ticks(link, count=5)
    assert link.poll_new_peer_edge() is True


def test_pump_sends_ready_on_new_peer_edge_via_comms():
    link, serial = make_link()
    run_until_ready(link)
    comms = _StubComms()

    # No peer yet -- pump does nothing extra.
    wifi_at.pump(link, 0, comms=comms)
    assert comms.ready_count == 0

    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"HELLO"))
    # Drain via pump itself (service() calls _pump_incoming()).
    now = 5
    for _ in range(10):
        wifi_at.pump(link, now, comms=comms)
        now += 5

    assert comms.ready_count == 1

    # No further READY sends for the same peer's continued traffic.
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"AGAIN"))
    for _ in range(10):
        wifi_at.pump(link, now, comms=comms)
        now += 5
    assert comms.ready_count == 1


# --- Transport contract (feeds comms.py's SAME engine) --------------------

def test_read_line_returns_v5_payload_without_trailing_newline_stripping():
    link, serial = make_link()
    run_until_ready(link)
    payload = b"WHEELS:\x01\x02\x03"
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, payload))
    run_ticks(link, count=5)
    assert link.read_line() == payload
    assert link.read_line() is None


# --- load_secrets() -------------------------------------------------------

def test_load_secrets_missing_file_returns_none_none():
    ssid, password = wifi_at.load_secrets(path="/nonexistent/wifi_secrets.json")
    assert (ssid, password) == (None, None)


def test_load_secrets_reads_ssid_and_password(tmp_path):
    secrets_path = tmp_path / "wifi_secrets.json"
    secrets_path.write_text('{"ssid": "myssid", "password": "mypass"}')
    ssid, password = wifi_at.load_secrets(path=str(secrets_path))
    assert (ssid, password) == ("myssid", "mypass")


def test_load_secrets_malformed_json_returns_none_none(tmp_path):
    secrets_path = tmp_path / "wifi_secrets.json"
    secrets_path.write_text("not valid json {{{")
    ssid, password = wifi_at.load_secrets(path=str(secrets_path))
    assert (ssid, password) == (None, None)


def test_send_reliable_accepts_str_and_encodes_ascii():
    link, serial = make_link()
    run_until_ready(link)
    serial.queue(build_ipd(wifi_at.V5_LINK, "10.0.0.5", 9999, b"X"))
    run_ticks(link, count=5)
    link.read_line()

    writes_before = len(serial.writes)
    link.send_reliable("PONG:t=123")
    run_ticks(link, count=20)
    new_writes = serial.writes[writes_before:]
    assert new_writes[1] == b"PONG:t=123"
