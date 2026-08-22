"""Ticket 007-008: offline tests for `tools/wifi_udp_probe.py`.

Same two-layer split as `tests/test_wifi_tcp_probe.py`: pure report/
timing logic tested with plain data (no socket at all), a duck-typed
`FakeUdpSocket` (`.settimeout()`/`.sendto()`/`.recvfrom()`, same shape
as `socket.socket`) for the send/receive orchestration, and one real
loopback UDP exchange proving the wiring. No test opens a network
connection outside 127.0.0.1, and none binds the real bench port
7655 (each test either uses `FakeUdpSocket` or binds port 0).
"""
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import wifi_udp_probe as probe  # noqa: E402  (path must be set up first)


class FakeUdpSocket:
    """Scripted duck-typed stand-in for a UDP `socket.socket`. `script`
    is consumed in order by `.recvfrom()`; each item is either a
    `(data, addr)` tuple or an exception instance to raise. An
    exhausted script raises `socket.timeout` forever."""

    def __init__(self, script=()):
        self._script = list(script)
        self.sent = []
        self.timeouts = []

    def settimeout(self, t):
        self.timeouts.append(t)

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr))

    def recvfrom(self, n):
        if not self._script:
            raise socket.timeout()
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# -- pure logic -----------------------------------------------------------

def test_make_probe_lines_distinct():
    lines = probe.make_probe_lines(3)
    assert lines == ["PROBE 0", "PROBE 1", "PROBE 2"]
    assert len(set(lines)) == 3


def test_rtt_ms_none_when_no_reply():
    r = probe.RoundTripResult(sent="x", sent_at=1.0, reply=None,
                               reply_at=None)
    assert probe.rtt_ms(r) is None


def test_rtt_ms_computed_from_timestamps():
    r = probe.RoundTripResult(sent="x", sent_at=1.000, reply=b"y",
                               reply_at=1.025)
    assert abs(probe.rtt_ms(r) - 25.0) < 1e-6


def test_format_round_trip_report_counts_replies():
    results = [
        probe.RoundTripResult("a", 0.0, b"A", 0.01),
        probe.RoundTripResult("b", 0.0, None, None),
        probe.RoundTripResult("c", 0.0, b"A", 0.01),
    ]
    text = probe.format_round_trip_report(results)
    assert "round-trip: 2/3 replied, 1 distinct reply payload(s)" in text
    assert "(no reply within timeout)" in text


def test_compute_inter_arrival_gaps_ms():
    arrivals = [
        probe.ArrivalRecord(recv_at=0.000, addr=("h", 1), data=b"1"),
        probe.ArrivalRecord(recv_at=0.010, addr=("h", 1), data=b"2"),
        probe.ArrivalRecord(recv_at=0.060, addr=("h", 1), data=b"3"),
    ]
    gaps = probe.compute_inter_arrival_gaps_ms(arrivals)
    assert len(gaps) == 2
    assert abs(gaps[0] - 10.0) < 1e-6
    assert abs(gaps[1] - 50.0) < 1e-6


def test_format_throttle_report_flags_violations():
    arrivals = [
        probe.ArrivalRecord(recv_at=0.000, addr=("h", 1), data=b"1"),
        probe.ArrivalRecord(recv_at=0.010, addr=("h", 1), data=b"2"),
        probe.ArrivalRecord(recv_at=0.070, addr=("h", 1), data=b"3"),
    ]
    text = probe.format_throttle_report(arrivals, min_interval_ms=50.0)
    lines = text.splitlines()
    assert "**" in lines[1]        # the 10 ms gap (< 50 ms floor)
    assert "**" not in lines[2]    # the 60 ms gap (>= 50 ms floor)
    assert "1 below the 50 ms floor" in text


def test_format_throttle_report_empty():
    assert probe.format_throttle_report([]) == "observe: no datagrams received"


# -- duck-typed socket layer -----------------------------------------------

def test_send_round_trip_reports_each_line():
    target = ("robot", 7654)
    sock = FakeUdpSocket([
        (b"R0", target),
        socket.timeout(),
        (b"R2", target),
    ])
    results = probe.send_round_trip(sock, target, ["PROBE 0", "PROBE 1",
                                                     "PROBE 2"],
                                     timeout=0.05)
    assert [r.reply for r in results] == [b"R0", None, b"R2"]
    assert sock.sent == [
        (b"PROBE 0", target), (b"PROBE 1", target), (b"PROBE 2", target)]


def test_send_round_trip_sends_line_bytes_verbatim():
    """`--line` (ticket 010) must reach `send_round_trip()` as the
    EXACT text given -- no numeric suffix -- so a real protocol verb
    like `HELLO` is sent unmodified. `make_probe_lines()`'s own
    `PROBE %d` shape is arity-bearing content the v6 engine cannot
    parse as any known verb, so it never replies to it directly; this
    is what makes `--line HELLO` necessary for a genuine round-trip
    check against the real engine (see module docstring)."""
    target = ("robot", 7654)
    sock = FakeUdpSocket([(b"device NEZHA2 robot fake fake", target)])
    results = probe.send_round_trip(sock, target, ["HELLO"], timeout=0.05)
    assert sock.sent == [(b"HELLO", target)]  # NOT b"HELLO 0"
    assert results[0].sent == "HELLO"


def test_listen_for_datagrams_collects_until_deadline():
    sock = FakeUdpSocket([
        (b"one", ("h", 1)),
        (b"two", ("h", 1)),
    ])
    arrivals = probe.listen_for_datagrams(sock, duration_s=0.05,
                                           poll_interval=0.01)
    assert [a.data for a in arrivals] == [b"one", b"two"]
    # recv_at timestamps are non-decreasing
    assert all(a.recv_at <= b.recv_at
               for a, b in zip(arrivals, arrivals[1:]))


# -- real loopback socket wiring check ------------------------------------

def _echo_server(server, replies_target):
    """Reply ECHO:<payload> to whoever sends us a datagram -- this is
    the peer-learning behavior under test: the server only learns the
    client's address from the first datagram it receives."""
    while True:
        data, addr = server.recvfrom(4096)
        replies_target.append(addr)
        server.sendto(b"ECHO:" + data, addr)
        if data == b"PROBE 1":
            break


def test_loopback_real_socket_round_trip():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server_addr = server.getsockname()

    learned_peers = []
    thread = threading.Thread(target=_echo_server,
                               args=(server, learned_peers), daemon=True)
    thread.start()
    try:
        client = probe.bind_socket(0)  # ephemeral port for the test
        try:
            results = probe.send_round_trip(
                client, server_addr, ["PROBE 0", "PROBE 1"], timeout=2.0)
        finally:
            client.close()
    finally:
        thread.join(timeout=2.0)
        server.close()

    assert results[0].reply == b"ECHO:PROBE 0"
    assert results[1].reply == b"ECHO:PROBE 1"
    # the server learned one stable peer address across both datagrams
    assert len(set(learned_peers)) == 1


def test_loopback_real_socket_listen_observes_arrivals():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server_addr = server.getsockname()

    def send_a_few(client_addr_holder):
        # wait for the client's kickoff datagram so the server (here,
        # this thread) learns the client's address, then push three
        # datagrams spaced ~20 ms apart.
        data, addr = server.recvfrom(4096)
        client_addr_holder.append(addr)
        for i in range(3):
            time.sleep(0.02)
            server.sendto(b"T%d" % i, addr)

    holder = []
    thread = threading.Thread(target=send_a_few, args=(holder,), daemon=True)
    thread.start()
    try:
        client = probe.bind_socket(0)
        try:
            client.sendto(b"KICKOFF", server_addr)
            arrivals = probe.listen_for_datagrams(client, duration_s=0.3)
        finally:
            client.close()
    finally:
        thread.join(timeout=2.0)
        server.close()

    assert [a.data for a in arrivals] == [b"T0", b"T1", b"T2"]


def test_cli_line_flag_overrides_count_and_preserves_order(monkeypatch):
    """CLI-level check (ticket 010): `--line` (repeatable) drives what
    `main()` actually sends, in the given order, ignoring `--count`
    entirely -- exercised through a real loopback socket, same as the
    other `test_loopback_real_socket_*` checks in this file."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server_addr = server.getsockname()

    received = []

    def echo_two():
        for _ in range(2):
            data, addr = server.recvfrom(4096)
            received.append(data)
            server.sendto(b"ok", addr)

    thread = threading.Thread(target=echo_two, daemon=True)
    thread.start()
    try:
        argv = ["wifi_udp_probe.py",
                "--host", server_addr[0], "--port", str(server_addr[1]),
                "--local-port", "0", "--count", "5",  # must be ignored
                "--line", "HELLO", "--line", "PING #1"]
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            probe.main()
        assert exc.value.code == 0
    finally:
        thread.join(timeout=2.0)
        server.close()

    assert received == [b"HELLO", b"PING #1"]
