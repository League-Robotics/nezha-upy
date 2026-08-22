"""Host-side bench prober for the robot's WiFi UDP protocol plane
(target `:7654`, host source `:7655`).

Sprint 007 ticket 008 (Track B, WiFi bring-up on tovez). Companion to
`tools/wifi_tcp_probe.py`; see that module's docstring for the shared
rationale (zero import dependency on `src/`, protocol-agnostic raw
lines, replaces radio-robot's now-dark `wifi_bench_gate.py` for this
repo's own bench gates).

`src/core/wifi_at.py` learns its UDP peer from the *source port* of
the first datagram it receives (extended `+IPD`/`CIPDINFO=1` parsing)
-- so the host side must send from a fixed, known port, not an
ephemeral one the OS picks per-run. That fixed port is `7655`
(`wifi_at.DEFAULT_DISCOVERY_PORT`, mirrored here as a literal -- no
import). This tool binds that port by default but takes it as a
parameter so it can be pointed at a local test server without a port
clash (ticket 008 acceptance criteria).

Two observations, both protocol-agnostic (raw lines in, raw lines/
datagrams out -- no v6 verb awareness):

- **round-trip**: send N distinct lines to `<host>:<port>`, report
  whether/what came back for each (ticket 010's basic peer-learning +
  round-trip check).
- **observe**: after that, just listen for `--observe-seconds` and
  report the gaps between successive incoming datagrams -- the
  instrument ticket 010 needs to eyeball the >=50 ms TLM throttle
  (`wifi_at.TLM_MIN_INTERVAL_MS`, mirrored here as a literal) without
  this tool knowing what a TLM frame is.

Testable design: mirrors `wifi_tcp_probe.py` -- pure functions/
namedtuples for framing and report text, a thin duck-typed socket
layer (`.settimeout()`/`.sendto()`/`.recvfrom()`, the same shape as
`socket.socket`), tested with a fake in `tests/
test_wifi_udp_probe.py` plus one real loopback UDP exchange for
end-to-end wiring. No test opens a real network connection to
hardware.

Usage (bench, tovez):
  python3 tools/wifi_udp_probe.py --host 192.168.4.11
  python3 tools/wifi_udp_probe.py --host 192.168.4.11 --observe-seconds 30
  python3 tools/wifi_udp_probe.py --host 192.168.4.11 --line HELLO \
      --observe-seconds 5
      # ticket 010: the v6 engine on the other end only replies to a
      # well-formed protocol line -- HELLO is unsequenced (no #id
      # needed) and always replies with the device banner, making it
      # the natural round-trip probe line against the real engine,
      # unlike the generic 'PROBE N' placeholders --count generates.

Usage (offline, against any local test server):
  python3 tools/wifi_udp_probe.py --host 127.0.0.1 --port 9765 --local-port 0
"""
import argparse
import socket
import sys
import time
from collections import namedtuple

# Robot's well-known UDP protocol-plane port -- mirrors
# src/core/wifi_at.py's DEFAULT_PORT (not imported; see module docstring).
DEFAULT_TARGET_PORT = 7654

# Host's own fixed source port -- mirrors wifi_at.DEFAULT_DISCOVERY_PORT.
# Must be fixed (not ephemeral) so the robot's first-datagram
# peer-learning latches onto a stable, known port.
DEFAULT_LOCAL_PORT = 7655

DEFAULT_COUNT = 3
DEFAULT_INTERVAL_MS = 200.0
DEFAULT_TIMEOUT_S = 2.0
DEFAULT_POLL_INTERVAL_S = 0.2

# Mirrors wifi_at.TLM_MIN_INTERVAL_MS -- the WiFi-plane telemetry
# throttle floor this tool's --observe-seconds report flags against.
DEFAULT_MIN_INTERVAL_MS = 50.0


RoundTripResult = namedtuple(
    "RoundTripResult", ["sent", "sent_at", "reply", "reply_at"])

ArrivalRecord = namedtuple("ArrivalRecord", ["recv_at", "addr", "data"])


# -- pure line-level logic (no socket) -----------------------------------

def make_probe_lines(count, prefix="PROBE"):
    """N distinct lines -- distinct so a round-trip report can tell
    which reply (if any) answered which send."""
    return ["%s %d" % (prefix, i) for i in range(count)]


def rtt_ms(result):
    if result.reply is None:
        return None
    return (result.reply_at - result.sent_at) * 1000.0


def format_round_trip_report(results):
    lines = []
    replied = 0
    distinct_replies = set()
    for r in results:
        if r.reply is None:
            lines.append("  sent %-16r -> (no reply within timeout)" %
                          r.sent)
        else:
            replied += 1
            distinct_replies.add(r.reply)
            lines.append("  sent %-16r -> %r  (%.1f ms)" %
                          (r.sent, r.reply, rtt_ms(r)))
    lines.append("round-trip: %d/%d replied, %d distinct reply payload(s)" %
                 (replied, len(results), len(distinct_replies)))
    return "\n".join(lines)


def compute_inter_arrival_gaps_ms(arrivals):
    """Gaps, in ms, between each arrival and the one before it (empty
    for the first). `arrivals` must already be in arrival order."""
    gaps = []
    for prev, cur in zip(arrivals, arrivals[1:]):
        gaps.append((cur.recv_at - prev.recv_at) * 1000.0)
    return gaps


def format_throttle_report(arrivals, min_interval_ms=DEFAULT_MIN_INTERVAL_MS):
    if not arrivals:
        return "observe: no datagrams received"
    gaps = compute_inter_arrival_gaps_ms(arrivals)
    lines = []
    lines.append("  [0] %r from %r" % (arrivals[0].data, arrivals[0].addr))
    violations = 0
    for i, gap in enumerate(gaps):
        flag = ""
        if gap < min_interval_ms:
            flag = "  ** below %.0f ms floor **" % min_interval_ms
            violations += 1
        lines.append("  [%d] %r from %r  (+%.1f ms)%s" %
                     (i + 1, arrivals[i + 1].data, arrivals[i + 1].addr,
                      gap, flag))
    lines.append("observe: %d datagram(s), min gap %.1f ms, "
                 "%d below the %.0f ms floor" %
                 (len(arrivals), min(gaps) if gaps else float("nan"),
                  violations, min_interval_ms))
    return "\n".join(lines)


# -- thin socket-handling layer (duck-typed: settimeout/sendto/recvfrom) -

def bind_socket(local_port, timeout=None):
    """The one function that creates a real socket -- everything else
    in this module operates on a duck-typed `sock` and is testable
    without a network."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", local_port))
    if timeout is not None:
        sock.settimeout(timeout)
    return sock


def send_round_trip(sock, target, lines, timeout=DEFAULT_TIMEOUT_S,
                     inter_send_delay_s=0.0):
    """Send each of `lines` to `target`, waiting up to `timeout` for a
    reply datagram after each send. `sock` needs `.sendto()`,
    `.settimeout()`, `.recvfrom()` (raising `socket.timeout` on no
    data) -- real and duck-typed fakes both qualify."""
    results = []
    for i, line in enumerate(lines):
        if i and inter_send_delay_s:
            time.sleep(inter_send_delay_s)
        sent_at = time.time()
        sock.sendto(line.encode("ascii"), target)
        sock.settimeout(timeout)
        try:
            data, _addr = sock.recvfrom(4096)
            reply_at = time.time()
        except socket.timeout:
            data, reply_at = None, None
        results.append(RoundTripResult(sent=line, sent_at=sent_at,
                                        reply=data, reply_at=reply_at))
    return results


def listen_for_datagrams(sock, duration_s, bufsize=4096,
                          poll_interval=DEFAULT_POLL_INTERVAL_S):
    """Passively collect every datagram `sock` receives for
    `duration_s` seconds -- the throttle-observation mode ticket 010
    needs to eyeball inter-arrival timing."""
    deadline = time.time() + duration_s
    arrivals = []
    while time.time() < deadline:
        remaining = deadline - time.time()
        sock.settimeout(min(poll_interval, remaining) if remaining > 0
                         else poll_interval)
        try:
            data, addr = sock.recvfrom(bufsize)
        except socket.timeout:
            continue
        arrivals.append(ArrivalRecord(recv_at=time.time(), addr=addr,
                                       data=data))
    return arrivals


# -- CLI ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Probe the robot's WiFi UDP protocol plane (:7654).")
    ap.add_argument("--host", required=True,
                     help="robot IP, e.g. 192.168.4.11 (tovez), or a "
                          "local test server for offline exercise")
    ap.add_argument("--port", type=int, default=DEFAULT_TARGET_PORT)
    ap.add_argument("--local-port", type=int, default=DEFAULT_LOCAL_PORT,
                     help="host's own fixed source port; must stay fixed "
                          "for the robot's peer-learning on real hardware, "
                          "but is parameterized (e.g. 0) for local tests")
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT,
                     help="number of distinct probe lines to send "
                          "(0 to skip the round-trip phase); ignored "
                          "if --line is given")
    ap.add_argument("--line", action="append", default=None,
                     help="send this EXACT line instead of a generated "
                          "'PROBE N' placeholder -- repeatable, sent in "
                          "the order given. Needed to exercise a real "
                          "protocol verb (e.g. 'HELLO') against the v6 "
                          "engine, which only replies to well-formed "
                          "lines (ticket 010) -- 'PROBE N' is content the "
                          "engine cannot parse as any verb, so it never "
                          "answers it directly, unlike a bare loopback "
                          "echo server")
    ap.add_argument("--interval-ms", type=float, default=DEFAULT_INTERVAL_MS,
                     help="delay between successive sends")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                     help="seconds to wait for each reply")
    ap.add_argument("--observe-seconds", type=float, default=0.0,
                     help="after the round-trip phase, passively listen "
                          "this many seconds and report inter-arrival "
                          "gaps (throttle observation)")
    ap.add_argument("--min-interval-ms", type=float,
                     default=DEFAULT_MIN_INTERVAL_MS,
                     help="floor used to flag short gaps in the observe "
                          "report")
    a = ap.parse_args()

    try:
        sock = bind_socket(a.local_port)
    except OSError as exc:
        sys.exit("wifi_udp_probe: could not bind local port %d -- %s" %
                  (a.local_port, exc))

    target = (a.host, a.port)
    ok = True
    try:
        lines = a.line if a.line else (
            make_probe_lines(a.count) if a.count > 0 else None)
        if lines:
            results = send_round_trip(
                sock, target, lines, timeout=a.timeout,
                inter_send_delay_s=a.interval_ms / 1000.0)
            print(format_round_trip_report(results))
            ok = any(r.reply is not None for r in results)

        if a.observe_seconds > 0:
            print("\nobserving for %.0fs ..." % a.observe_seconds)
            arrivals = listen_for_datagrams(sock, a.observe_seconds)
            print(format_throttle_report(
                arrivals, min_interval_ms=a.min_interval_ms))
    finally:
        sock.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
