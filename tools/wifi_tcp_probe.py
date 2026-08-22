"""Host-side bench prober for the robot's WiFi TCP REPL mirror (`:7654`).

Sprint 007 ticket 008 (Track B, WiFi bring-up on tovez). The v6
cutover retires radio-robot's own `wifi_bench_gate.py` against this
firmware -- this tool is the self-contained replacement instrument for
this repo's own bench gates (tickets 009-011), not a drop-in
replacement for that tooling project-wide.

**Zero import dependency on `src/`** -- deliberately protocol-agnostic.
It proves socket-level mechanics (connect, get an interactive REPL
prompt, round-trip an expression, hold the session open) the same way
`nc 192.168.4.11 7654` does (the issue's own reference baseline,
`clasi/sprints/007-.../issues/wifi-bring-up-on-tovez-tcp-repl-udp-
protocol.md`); it does not know or care about the v5/v6 wire grammar.

Testable design: the line-level logic (prompt detection, response
framing, report formatting) is plain functions/namedtuples operating
on bytes, independent of any real socket -- `tests/
test_wifi_tcp_probe.py` drives it with a duck-typed fake object
(`.settimeout()`/`.recv()`/`.sendall()`, same shape as `socket.socket`
and the same convention `tests/test_wifi_at.py`'s `FakeSerial` uses for
`wifi_at.WifiAtLink`) plus a real loopback TCP server for one
end-to-end wiring check. No test opens a real network connection to
hardware.

Usage (bench, tovez):
  python3 tools/wifi_tcp_probe.py --host 192.168.4.11
  python3 tools/wifi_tcp_probe.py --host 192.168.4.11 --hold-seconds 300
  python3 tools/wifi_tcp_probe.py --host 192.168.4.11 --hold-seconds -1   # until Ctrl-C

Usage (offline, against any local test server):
  python3 tools/wifi_tcp_probe.py --host 127.0.0.1 --port 8765
"""
import argparse
import socket
import sys
import time
from collections import namedtuple

# Well-known TCP REPL mirror port -- mirrors src/core/wifi_at.py's
# DEFAULT_PORT. Not imported (this tool has zero import dependency on
# src/); kept here as a literal, with this comment as the tie-back.
DEFAULT_PORT = 7654

DEFAULT_EVAL_EXPR = "2+2"
DEFAULT_EXPECT = "4"
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_POLL_INTERVAL_S = 0.2

# MicroPython's normal interactive prompt. The TCP mirror is a raw
# pipe onto the same stdout stream the USB REPL sees -- no login
# banner of its own, so "expect a prompt" means exactly this.
PROMPT = b">>> "


TcpProbeResult = namedtuple(
    "TcpProbeResult",
    ["banner", "prompt_ok", "eval_expr", "eval_reply", "expect", "eval_ok"])


# -- pure line-level logic (no socket) -----------------------------------

def has_prompt(buf):
    """True once `buf` ends with the interactive prompt."""
    return buf.endswith(PROMPT)


def contains_token(buf, token):
    """True if `token` (str) appears anywhere in `buf` (bytes)."""
    if token is None:
        return False
    return token.encode("ascii") in buf


def format_tcp_report(result):
    """Render a `TcpProbeResult` as the bench operator's report text."""
    lines = []
    lines.append("connect      OK")
    lines.append("prompt       %s  (%d bytes received)" % (
        "OK" if result.prompt_ok else "FAIL", len(result.banner)))
    if result.expect is not None:
        lines.append("eval  %r -> expect %r   %s" % (
            result.eval_expr, result.expect,
            "OK" if result.eval_ok else "FAIL"))
        lines.append("  reply bytes: %r" % result.eval_reply)
    else:
        lines.append("eval  skipped (--no-eval)")
    return "\n".join(lines)


# -- thin socket-handling layer (duck-typed: settimeout/recv/sendall) ----

def recv_until(sock, predicate, timeout, bufsize=4096,
               poll_interval=DEFAULT_POLL_INTERVAL_S):
    """Accumulate bytes from `sock` until `predicate(buf)` is true.

    `sock` need only support `.settimeout(s)` and `.recv(n)` -- real
    `socket.socket` objects and duck-typed fakes both qualify. Polls in
    small slices (`poll_interval`) so the overall `timeout` deadline is
    honored even when the underlying object raises `socket.timeout` on
    every call (as a real non-blocking socket would with no data).
    """
    buf = b""
    deadline = time.time() + timeout
    while not predicate(buf):
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(
                "timed out after %.1fs waiting for expected data; "
                "got %r" % (timeout, buf))
        sock.settimeout(min(poll_interval, remaining))
        try:
            chunk = sock.recv(bufsize)
        except socket.timeout:
            continue
        if not chunk:
            raise ConnectionError(
                "connection closed while waiting; got %r" % buf)
        buf += chunk
    return buf


def send_line(sock, text):
    sock.sendall((text + "\n").encode("ascii"))


def hold_open(sock, duration_s, bufsize=4096,
              poll_interval=DEFAULT_POLL_INTERVAL_S, on_chunk=None):
    """Keep reading from `sock` for `duration_s` seconds, doing nothing
    but observe -- the 5-minute-idle and dual-plane-concurrency bench
    cases just need the TCP session to stay open and responsive while
    other traffic happens elsewhere. `duration_s` may be `float('inf')`
    for "until interrupted" (the CLI's `--hold-seconds -1`).

    Returns the concatenation of everything received (for a caller that
    wants it), and calls `on_chunk(chunk)` for each chunk as it arrives
    (the CLI uses this to print observed traffic live).
    """
    deadline = time.time() + duration_s
    received = []
    while time.time() < deadline:
        remaining = deadline - time.time()
        sock.settimeout(min(poll_interval, remaining) if remaining > 0
                         else poll_interval)
        try:
            chunk = sock.recv(bufsize)
        except socket.timeout:
            continue
        if not chunk:
            break  # peer closed
        received.append(chunk)
        if on_chunk is not None:
            on_chunk(chunk)
    return b"".join(received)


def connect(host, port, timeout):
    """The one function that creates a real socket -- everything else
    in this module operates on a duck-typed `sock` and is testable
    without a network."""
    return socket.create_connection((host, port), timeout=timeout)


# -- probe orchestration (still duck-typed on sock; no real I/O here) ---

def run_repl_probe(sock, eval_expr=DEFAULT_EVAL_EXPR,
                    expect=DEFAULT_EXPECT, timeout=DEFAULT_TIMEOUT_S):
    """Wake the prompt (nc-style: send a blank line, since a freshly
    connected TCP client sees no historic output), confirm it, then
    send `eval_expr` and confirm `expect` shows up somewhere in the
    reply before the next prompt.
    """
    send_line(sock, "")
    banner = recv_until(sock, has_prompt, timeout)
    prompt_ok = has_prompt(banner)

    eval_reply = b""
    eval_ok = False
    if expect is not None:
        send_line(sock, eval_expr)
        eval_reply = recv_until(sock, has_prompt, timeout)
        eval_ok = contains_token(eval_reply, expect)

    return TcpProbeResult(
        banner=banner, prompt_ok=prompt_ok, eval_expr=eval_expr,
        eval_reply=eval_reply, expect=expect, eval_ok=eval_ok)


# -- CLI ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Probe the robot's WiFi TCP REPL mirror (:7654).")
    ap.add_argument("--host", required=True,
                     help="robot IP, e.g. 192.168.4.11 (tovez), or a "
                          "local test server for offline exercise")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--eval-expr", default=DEFAULT_EVAL_EXPR,
                     help="expression to send once the prompt is up")
    ap.add_argument("--expect", default=DEFAULT_EXPECT,
                     help="substring expected in the eval reply")
    ap.add_argument("--no-eval", action="store_true",
                     help="skip the send-expression step entirely")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                     help="seconds to wait for the prompt/reply")
    ap.add_argument("--hold-seconds", type=float, default=0.0,
                     help="after the probe, hold the session open this "
                          "many seconds (-1 = until Ctrl-C); use for the "
                          "5-minute-idle / dual-plane-concurrency bench "
                          "cases")
    a = ap.parse_args()

    expect = None if a.no_eval else a.expect

    try:
        sock = connect(a.host, a.port, a.timeout)
    except OSError as exc:
        sys.exit("wifi_tcp_probe: could not connect to %s:%d -- %s" %
                  (a.host, a.port, exc))

    try:
        try:
            result = run_repl_probe(
                sock, eval_expr=a.eval_expr, expect=expect,
                timeout=a.timeout)
        except (TimeoutError, ConnectionError) as exc:
            sys.exit("wifi_tcp_probe: %s" % exc)

        print(format_tcp_report(result))

        ok = result.prompt_ok and (expect is None or result.eval_ok)

        if a.hold_seconds:
            duration = float("inf") if a.hold_seconds < 0 else a.hold_seconds
            print("\nholding session open for %s -- Ctrl-C to stop early" %
                  ("indefinitely" if duration == float("inf")
                   else "%.0fs" % duration))

            def report_chunk(chunk):
                print("  << %r" % chunk)

            try:
                hold_open(sock, duration, on_chunk=report_chunk)
            except KeyboardInterrupt:
                print("\ninterrupted -- closing")
    finally:
        sock.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
