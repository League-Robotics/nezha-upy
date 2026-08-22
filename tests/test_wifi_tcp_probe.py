"""Ticket 007-008: offline tests for `tools/wifi_tcp_probe.py`.

Two layers, matching the module's own split:

- pure line-level logic (`has_prompt`/`contains_token`/`recv_until`/
  `run_repl_probe`/`format_tcp_report`/`hold_open`) driven by a
  duck-typed `FakeSocket` (`.settimeout()`/`.recv()`/`.sendall()`,
  same shape as `socket.socket` -- the convention `tests/
  test_wifi_at.py`'s `FakeSerial` uses for `wifi_at.WifiAtLink`);
- one real loopback TCP exchange (`socket`/`threading`, no hardware)
  proving the duck-typed logic also works wired to an actual socket.

No test opens a network connection outside 127.0.0.1.
"""
import socket
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import wifi_tcp_probe as probe  # noqa: E402  (path must be set up first)


class FakeSocket:
    """Scripted duck-typed stand-in for `socket.socket`. `script` is a
    list consumed in order by `.recv()`; each item is either bytes (a
    chunk to return) or an exception instance to raise. An exhausted
    script raises `socket.timeout` forever, mirroring a real
    non-blocking socket with no data pending."""

    def __init__(self, script=()):
        self._script = list(script)
        self.sent = []
        self.timeouts = []
        self.closed = False

    def settimeout(self, t):
        self.timeouts.append(t)

    def sendall(self, data):
        self.sent.append(bytes(data))

    def recv(self, n):
        if not self._script:
            raise socket.timeout()
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


# -- pure logic -----------------------------------------------------------

def test_has_prompt():
    assert probe.has_prompt(b"hello\r\n>>> ")
    assert not probe.has_prompt(b"hello\r\n>>>")  # missing trailing space
    assert not probe.has_prompt(b"")


def test_contains_token():
    assert probe.contains_token(b"2+2\r\n4\r\n>>> ", "4")
    assert not probe.contains_token(b"2+2\r\n5\r\n>>> ", "4")
    assert not probe.contains_token(b"anything", None)


def test_recv_until_accumulates_across_chunks():
    sock = FakeSocket([b"hello ", b">>> "])
    buf = probe.recv_until(sock, probe.has_prompt, timeout=1.0)
    assert buf == b"hello >>> "


def test_recv_until_times_out():
    sock = FakeSocket([])  # every recv() raises socket.timeout
    try:
        probe.recv_until(sock, probe.has_prompt, timeout=0.05,
                          poll_interval=0.01)
        assert False, "expected TimeoutError"
    except TimeoutError:
        pass


def test_recv_until_raises_on_connection_closed():
    sock = FakeSocket([b""])  # empty chunk == peer closed
    try:
        probe.recv_until(sock, probe.has_prompt, timeout=1.0)
        assert False, "expected ConnectionError"
    except ConnectionError:
        pass


def test_send_line_terminates_with_crlf_not_bare_lf():
    """Sprint 007 ticket 009: on real tovez hardware, a bare `\n` line
    to the WiFi REPL mirror got zero bytes back within 15s -- the same
    blank line sent as `\r\n` got an immediate `\r\n>>> ` reply. The
    offline FakeSocket/loopback fixtures both reply unconditionally, so
    neither would have caught a regression back to bare-`\n`; this
    test pins the wire bytes directly."""
    sock = FakeSocket([b"\r\n>>> "])
    probe.send_line(sock, "")
    assert sock.sent == [b"\r\n"]

    sock2 = FakeSocket([b"2+2\r\n4\r\n>>> "])
    probe.send_line(sock2, "2+2")
    assert sock2.sent == [b"2+2\r\n"]


def test_run_repl_probe_success():
    sock = FakeSocket([b"\r\n>>> ", b"2+2\r\n4\r\n>>> "])
    result = probe.run_repl_probe(sock, eval_expr="2+2", expect="4",
                                   timeout=1.0)
    assert result.prompt_ok
    assert result.eval_ok
    assert result.eval_reply == b"2+2\r\n4\r\n>>> "
    # wake blank line, then the eval expression -- both CRLF-terminated
    # (sprint 007 ticket 009: bare LF alone never got a reply from the
    # real firmware -- see send_line's own docstring)
    assert sock.sent == [b"\r\n", b"2+2\r\n"]


def test_run_repl_probe_eval_mismatch():
    sock = FakeSocket([b"\r\n>>> ", b"2+2\r\n4\r\n>>> "])
    result = probe.run_repl_probe(sock, eval_expr="2+2", expect="9",
                                   timeout=1.0)
    assert result.prompt_ok
    assert not result.eval_ok


def test_run_repl_probe_no_eval():
    sock = FakeSocket([b"\r\n>>> "])
    result = probe.run_repl_probe(sock, expect=None, timeout=1.0)
    assert result.prompt_ok
    assert not result.eval_ok
    assert result.eval_reply == b""
    assert sock.sent == [b"\r\n"]  # no eval line sent


def test_format_tcp_report_ok():
    result = probe.TcpProbeResult(
        banner=b"\r\n>>> ", prompt_ok=True, eval_expr="2+2",
        eval_reply=b"2+2\r\n4\r\n>>> ", expect="4", eval_ok=True)
    text = probe.format_tcp_report(result)
    assert "connect      OK" in text
    assert "prompt       OK" in text
    assert "eval  '2+2' -> expect '4'   OK" in text


def test_format_tcp_report_skipped_eval():
    result = probe.TcpProbeResult(
        banner=b"\r\n>>> ", prompt_ok=True, eval_expr="2+2",
        eval_reply=b"", expect=None, eval_ok=False)
    text = probe.format_tcp_report(result)
    assert "eval  skipped" in text


def test_hold_open_collects_chunks_and_calls_back():
    sock = FakeSocket([b"a", b"b"])
    chunks = []
    received = probe.hold_open(sock, duration_s=0.05, poll_interval=0.01,
                                on_chunk=chunks.append)
    assert received == b"ab"
    assert chunks == [b"a", b"b"]


def test_hold_open_stops_early_on_peer_close():
    sock = FakeSocket([b"x", b""])
    received = probe.hold_open(sock, duration_s=5.0, poll_interval=0.01)
    assert received == b"x"


# -- real loopback socket wiring check ------------------------------------

def _read_line(conn):
    buf = b""
    while b"\n" not in buf:
        chunk = conn.recv(256)
        if not chunk:
            break
        buf += chunk
    return buf.strip(b"\r\n")


def _serve_one_repl_session(server):
    conn, _addr = server.accept()
    try:
        _read_line(conn)  # the wake blank line
        conn.sendall(b"\r\n>>> ")
        line = _read_line(conn)
        assert line == b"2+2"
        conn.sendall(b"2+2\r\n4\r\n>>> ")
    finally:
        conn.close()


def test_loopback_real_socket_repl_probe():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    thread = threading.Thread(target=_serve_one_repl_session,
                               args=(server,), daemon=True)
    thread.start()
    try:
        sock = probe.connect(host, port, timeout=2.0)
        try:
            result = probe.run_repl_probe(sock, timeout=2.0)
        finally:
            sock.close()
    finally:
        thread.join(timeout=2.0)
        server.close()

    assert result.prompt_ok
    assert result.eval_ok
    assert result.eval_reply == b"2+2\r\n4\r\n>>> "
