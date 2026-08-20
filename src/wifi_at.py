"""wifi_at -- WiFi AT state machine + UDP v5 plane + TCP-REPL demux.

Owns the whole AT dialogue: joining, `CIPMUX=1`, the TCP REPL mirror
server, the UDP v5 socket, per-datagram coalescing (ONE `AT+CIPSEND`
per datagram -- per-char floods the module), the >=50 ms telemetry
throttle (Sec 8), and READY-on-new-peer-edge handling. Ports
`reference/modrobot/wifi_stdio.cpp`'s AT-sequence machine from C++ to
Python (Sec 3), not a straight copy. The native `wifiuart` module is
only a byte-pipe shim over UARTE1 plus a REPL stdin/stdout ring --
every AT/`+IPD`/coalescing byte is handled HERE. The UDP v5 plane
feeds `comms.py`'s SAME `Comms` engine (`WifiAtLink` implements its
Transport contract), not a second protocol engine.

Single-context (Sec 8): `WifiAtLink.service()`/module-level `pump()`
run ONLY from the scheduled pump context, never a VM/GC hook or IRQ --
so every method here is non-blocking (no `time.sleep`/busy-wait).

BENCH-TIME: the WiFi module persists AP-join/socket/server state
across nRF52 reflashes -- power-cycle it before any bring-up session,
or `AT+RST` may race a stale auto-rejoin already in progress.

`wifiuart`/`json` are import-guarded; `load_secrets()` degrades to
`(None, None)` without `json`. No PEP 604/generic-subscript hints, no
f-strings (CLAUDE.md).
"""

try:
    import json
except ImportError:  # a MicroPython build without json
    json = None

try:
    import wifiuart
except ImportError:  # CPython (tests), or a build without --with-wifi
    wifiuart = None

__all__ = [
    "WifiAtLink",
    "TlmThrottle",
    "NativeWifiSerial",
    "NativeReplHook",
    "load_secrets",
    "pump",
    "V5_LINK",
    "DEFAULT_PORT",
    "DEFAULT_DISCOVERY_PORT",
    "TLM_MIN_INTERVAL_MS",
]

# Protocol constants -- mirror reference/modrobot/wifi_stdio.cpp.
V5_LINK = 4  # ESP-AT link id, fixed (kV5Link)
DEFAULT_PORT = 7654  # well-known TCP REPL / UDP local port
DEFAULT_DISCOVERY_PORT = 7655  # host's fixed local port (kV5DiscoveryPort)
TLM_MIN_INTERVAL_MS = 50  # spec Sec 8: WiFi-plane TLM throttle floor

_CMD_TIMEOUT_MS = 4000
_JOIN_TIMEOUT_MS = 15000
_BACKOFF_DELAY_MS = 5000
_JOIN_QUERY_ATTEMPTS = 6  # ~9s of AT+CWJAP? polling (auto-rejoin settle window)
_PEER_SILENCE_MS = 60000  # mirrors Hardware::WifiLink::kPeerSilence
_STATUS_LINE_MAX = 96
_INCOMING_CHUNK_MAX = 256

_ST_CONFIGURE = "configure"
_ST_JOIN = "join"
_ST_ADDRESS = "address"
_ST_SERVER = "server"
_ST_READY = "ready"
_ST_BACKOFF = "backoff"

# (command, expect, timeout_ms, tolerant); AT+RST first because the
# RJ11-powered module keeps server/client/mux state across an nRF reset.
_CONFIGURE_STEPS = (
    ("AT+RST", "ready", 6000, True),
    ("AT", "OK", 2000, True),  # absorb boot-banner stragglers
    ("ATE0", "OK", _CMD_TIMEOUT_MS, True),
    ("AT+CIPMODE=0", "OK", _CMD_TIMEOUT_MS, True),
    ("AT+CIPSERVER=0", "OK", _CMD_TIMEOUT_MS, True),
    ("AT+CIPCLOSE=5", "OK", _CMD_TIMEOUT_MS, True),
    ("AT+CIPCLOSE", "OK", _CMD_TIMEOUT_MS, True),
    ("AT+CWMODE=1", "OK", _CMD_TIMEOUT_MS, False),
    ("AT+CIPMUX=1", "OK", _CMD_TIMEOUT_MS, False),
    ("AT+CIPDINFO=1", "OK", _CMD_TIMEOUT_MS, True),  # +IPD then carries sender ip/port inline
)


class _Matcher:
    """Incremental substring matcher: feed one byte at a time, True
    exactly when `token` (bytes, or None) has just been completed."""

    def __init__(self, token=None):
        self._token = None
        self._matched = 0
        self.reset(token)

    def reset(self, token):
        self._token = token
        self._matched = 0

    def feed(self, ch):
        token = self._token
        if not token:
            return False
        if ch == token[self._matched]:
            self._matched += 1
            if self._matched == len(token):
                self._matched = 0
                return True
            return False
        self._matched = 1 if ch == token[0] else 0
        return False


class _IpdParser:
    """Parses both `+IPD,<link>,<len>:` (CIPDINFO=0) and the
    CIPDINFO=1 extended `+IPD,<link>,<len>,"<ip>",<port>:` form."""

    _TAG = b"+IPD,"

    def __init__(self):
        self._tag = _Matcher()
        self.link = -1
        self.length = 0
        self.ip = ""
        self.port = 0
        self._stage = "tag"
        self._saw_digit = False
        self._ip_chars = []
        self._port_saw_digit = False
        self.reset()

    def reset(self):
        self._stage = "tag"
        self._tag.reset(self._TAG)
        self.link = -1
        self.length = 0
        self._saw_digit = False
        self.ip = ""
        self._ip_chars = []
        self.port = 0
        self._port_saw_digit = False

    def feed(self, ch):
        """Feed one byte (int); True exactly when a full header (either
        form) is recognized -- `self.link`/`length`/`ip`/`port` valid."""
        stage = self._stage
        if stage == "tag":
            if self._tag.feed(ch):
                self._stage = "link"
                self.link = 0
                self._saw_digit = False
            return False
        if stage == "link":
            if 0x30 <= ch <= 0x39:
                self.link = self.link * 10 + (ch - 0x30)
                self._saw_digit = True
                return False
            if ch == 0x2C and self._saw_digit:  # ','
                self._stage = "len"
                self.length = 0
                self._saw_digit = False
                return False
            self.reset()
            return False
        if stage == "len":
            if 0x30 <= ch <= 0x39:
                self.length = self.length * 10 + (ch - 0x30)
                self._saw_digit = True
                return False
            if ch == 0x3A and self._saw_digit:  # ':'
                self._stage = "done"
                return True
            if ch == 0x2C and self._saw_digit:  # ',' -- extended form
                self._stage = "to_quote"
                return False
            self.reset()
            return False
        if stage == "to_quote":
            if ch == 0x22:  # '"'
                self._stage = "ip"
                self._ip_chars = []
                return False
            self.reset()
            return False
        if stage == "ip":
            if ch == 0x22:
                self.ip = bytes(self._ip_chars).decode("ascii")
                self._stage = "to_port"
                return False
            if len(self._ip_chars) < 15:
                self._ip_chars.append(ch)
                return False
            self.reset()  # address too long -- resynchronize
            return False
        if stage == "to_port":
            if ch == 0x2C:
                self._stage = "port"
                self.port = 0
                self._port_saw_digit = False
                return False
            self.reset()
            return False
        if stage == "port":
            if 0x30 <= ch <= 0x39:
                self.port = self.port * 10 + (ch - 0x30)
                self._port_saw_digit = True
                return False
            if ch == 0x3A and self._port_saw_digit:  # ':'
                self._stage = "done"
                return True
            self.reset()
            return False
        return False  # stage == "done": inert until the next reset()


class TlmThrottle:
    """>=50 ms telemetry throttle for the WiFi plane (Sec 8),
    independent of `comms.py`'s general 25 ms cadence -- caps how
    often a PERIODIC (non-ack) push goes out over THIS plane."""

    def __init__(self, min_interval_ms=TLM_MIN_INTERVAL_MS):
        self._min_interval_ms = min_interval_ms
        self._last_sent_ms = None

    def allow(self, now):
        """True (and records `now`, int [ms]) iff `min_interval_ms`
        has elapsed since the last allowed call, or this is the
        first ever."""
        if self._last_sent_ms is None or (now - self._last_sent_ms) >= self._min_interval_ms:
            self._last_sent_ms = now
            return True
        return False


class WifiAtLink:
    """WiFi AT bring-up state machine + the UDP v5 plane's `comms.py`
    Transport (`read_line`/`send`/`send_reliable`) + TCP-REPL demux.
    `serial`: duck-typed AT byte-pipe -- `init(baudrate)`, `write(data:
    bytes) -> int`, `any() -> int`, `read(n) -> bytes`, all
    non-blocking (`NativeWifiSerial` adapts `wifiuart`; tests fake it).
    `repl_hook`, if given: `set_active(bool)`, `stdin_push(data) ->
    int`, `stdout_pull(n) -> bytes` (`NativeReplHook` adapts
    `wifiuart`); `None` (default) leaves the REPL mirror inert."""

    def __init__(self, serial, ssid, password, port=DEFAULT_PORT,
                 discovery_port=DEFAULT_DISCOVERY_PORT, baudrate=115200,
                 repl_hook=None):
        self._serial = serial
        self._ssid = ssid
        self._password = password
        self._port = port
        self._discovery_port = discovery_port
        self._repl_hook = repl_hook

        self._state = _ST_CONFIGURE
        self._step = 0
        self._join_query_attempt = 0

        self._awaiting = False
        self._expect = _Matcher()
        self._reject_error = _Matcher(b"ERROR")
        self._reject_fail = _Matcher(b"FAIL")
        self._reject_busy = _Matcher(b"busy")
        self._await_matched = False
        self._await_rejected = False
        self._deadline = 0

        self._ipd = _IpdParser()
        self._payload_remaining = 0
        self._payload_link = -1
        self._payload_buf = bytearray()

        self._line_buf = bytearray()

        self._repl_link = None

        self._v5_peer_ip = None
        self._v5_peer_port = None
        self._v5_peer_known = False
        self._last_v5_heard = 0
        self._reported_peer = None

        self._v5_rx = []

        self._send_queue = []
        self._send_phase = None
        self._send_payload = b""

        self._last_now = 0

        self._serial.init(baudrate)

    # -- comms.py Transport contract; feeds the SAME engine ---------------

    def read_line(self):
        """Non-blocking; next v5 UDP datagram's raw content (a UDP
        datagram IS the message, no framing/delimiter), or None."""
        if not self._v5_rx:
            return None
        return self._v5_rx.pop(0)

    def send(self, data):
        """Queue ONE UDP datagram for the v5 peer -- ONE `AT+CIPSEND`
        per call, never per character (Sec 3/8). Drops silently if not
        READY or no peer currently known."""
        if self._state != _ST_READY:
            return
        if not self._v5_peer_known_now(self._last_now):
            return
        self._send_queue.append(("v5", self._v5_peer_ip, self._v5_peer_port, bytes(data)))

    def send_reliable(self, text):
        if isinstance(text, str):
            text = text.encode("ascii")
        self.send(text)

    def send_telemetry(self, data, throttle, now):
        """Periodic (non-ack) push, gated by `throttle` (a
        `TlmThrottle`). Replies/acks must use `send()`/
        `send_reliable()` directly, UNTHROTTLED."""
        if not throttle.allow(now):
            return
        self.send(data)

    def poll_new_peer_edge(self):
        """True exactly once per NEW (ip, port) the v5 plane starts
        hearing from (consumed on read). `pump()` uses this to fire
        `comms.send_ready()` for a freshly-connected WiFi peer."""
        current = (
            (self._v5_peer_ip, self._v5_peer_port)
            if self._v5_peer_known_now(self._last_now) else None
        )
        if current is not None and current != self._reported_peer:
            self._reported_peer = current
            return True
        return False

    def service(self, now):
        """Advance the AT bring-up / READY-state pumping by one bounded
        step. Call every scheduled-pump tick (main context only, never
        a VM/GC hook or IRQ -- spec Sec 8)."""
        self._last_now = now
        if self._state == _ST_CONFIGURE:
            self._service_configure(now)
        elif self._state == _ST_JOIN:
            self._service_join(now)
        elif self._state == _ST_ADDRESS:
            self._service_address(now)
        elif self._state == _ST_SERVER:
            self._service_server(now)
        elif self._state == _ST_READY:
            self._service_ready(now)
        elif self._state == _ST_BACKOFF:
            self._service_backoff(now)

    def state(self):
        return self._state  # for tests/diagnostics

    def _enter_state(self, state, now):
        self._state = state
        self._step = 0
        self._awaiting = False
        self._ipd.reset()
        self._line_buf = bytearray()
        self._payload_remaining = 0
        self._payload_buf = bytearray()

    def _enter_backoff(self, now):
        # Tear down peer/client state -- the next CONFIGURE pass's AT+RST wipes every ESP-AT socket.
        self._v5_peer_known = False
        self._v5_peer_ip = None
        self._v5_peer_port = None
        self._repl_link = None
        if self._repl_hook is not None:
            self._repl_hook.set_active(False)
        self._send_queue = []
        self._send_phase = None
        self._deadline = now + _BACKOFF_DELAY_MS
        self._enter_state(_ST_BACKOFF, now)

    # -- AT command/await: NON-BLOCKING port of sendCommand()/awaitReply() --

    def _start_await(self, expect, timeout_ms, now):
        self._expect.reset(expect)
        self._reject_error.reset(b"ERROR")
        self._reject_fail.reset(b"FAIL")
        self._reject_busy.reset(b"busy")
        self._await_matched = False
        self._await_rejected = False
        self._deadline = now + timeout_ms
        self._awaiting = True

    def _start_command(self, command_text, expect, timeout_ms, now):
        self._serial.write((command_text + "\r\n").encode("ascii"))  # 1 write; under UARTE's 250-byte TX buf
        expect_bytes = expect.encode("ascii") if isinstance(expect, str) else expect
        self._start_await(expect_bytes, timeout_ms, now)

    def _poll_await(self, now):
        if not self._awaiting:
            return "timeout"
        if self._await_matched:
            self._awaiting = False
            return "matched"
        if self._await_rejected:
            self._awaiting = False
            return "rejected"
        if now - self._deadline >= 0:
            self._awaiting = False
            return "timeout"
        return "pending"

    # -- incoming byte demux: port of feedIncoming()/handleStatusLine() --

    def _pump_incoming(self, now):
        while True:
            n = self._serial.any()
            if n <= 0:
                break
            chunk = self._serial.read(min(n, _INCOMING_CHUNK_MAX))
            if not chunk:
                break
            for ch in chunk:
                self._feed_byte(ch, now)

    def _feed_byte(self, ch, now):
        if self._payload_remaining > 0:
            self._payload_buf.append(ch)
            self._payload_remaining -= 1
            if self._payload_remaining == 0:
                self._finish_payload()
            return
        if self._ipd.feed(ch):
            self._payload_remaining = self._ipd.length
            self._payload_link = self._ipd.link
            if self._payload_link == V5_LINK:
                # Peer learned/refreshed off the HEADER alone -- an empty datagram still counts as heard-from.
                if self._ipd.ip:
                    self._v5_peer_ip = self._ipd.ip
                if self._ipd.port:
                    self._v5_peer_port = self._ipd.port
                self._last_v5_heard = now
                self._v5_peer_known = True
            self._ipd.reset()
            if self._payload_remaining == 0:
                self._finish_payload()
            return
        self._feed_status_byte(ch)
        if self._awaiting:
            if self._expect.feed(ch):
                self._await_matched = True
            if (self._reject_error.feed(ch) or self._reject_fail.feed(ch)
                    or self._reject_busy.feed(ch)):
                self._await_rejected = True

    def _finish_payload(self):
        data = bytes(self._payload_buf)
        self._payload_buf = bytearray()
        if self._payload_link == V5_LINK:
            self._v5_rx.append(data)
        elif self._payload_link == self._repl_link and self._repl_hook is not None:
            self._repl_hook.stdin_push(data)
        # else: unrecognized/not-yet-matched link -- dropped.

    def _feed_status_byte(self, ch):
        if ch == 0x0D:  # '\r'
            return
        if ch == 0x0A:  # '\n'
            line = bytes(self._line_buf)
            self._line_buf = bytearray()
            self._handle_status_line(line)
            return
        if len(self._line_buf) + 1 < _STATUS_LINE_MAX:
            self._line_buf.append(ch)
        else:
            self._line_buf = bytearray()

    def _handle_status_line(self, line):
        """`<link>,CONNECT` / `<link>,CLOSED`. V5_LINK is ignored here:
        ESP-AT's mux CIPSTART reports this lifecycle for it too (not a
        TCP client), else it'd be mistaken for a REPL client."""
        try:
            text = line.decode("ascii")
        except UnicodeError:
            return
        comma = text.find(",")
        if comma <= 0:
            return
        link_text = text[:comma]
        status = text[comma + 1:]
        if not link_text.isdigit():
            return
        link = int(link_text)
        if link == V5_LINK:
            return
        if status == "CONNECT":
            # Newest client wins -- else a stale abandoned session shadows the fresh one.
            self._repl_link = link
            if self._repl_hook is not None:
                self._repl_hook.set_active(True)
        elif status == "CLOSED" and self._repl_link == link:
            self._repl_link = None
            if self._repl_hook is not None:
                self._repl_hook.set_active(False)

    # -- peer-silence lazy-forget: checked here, not on a timer -------

    def _v5_peer_known_now(self, now):
        if not self._v5_peer_known:
            return False
        if now - (self._last_v5_heard + _PEER_SILENCE_MS) >= 0:
            self._v5_peer_known = False
            self._v5_peer_ip = None
            self._v5_peer_port = None
            return False
        return True

    # -- bring-up states --------------------------------------------

    def _service_configure(self, now):
        self._pump_incoming(now)
        if self._step >= len(_CONFIGURE_STEPS):
            self._enter_state(_ST_JOIN, now)
            return
        command, expect, timeout_ms, tolerant = _CONFIGURE_STEPS[self._step]
        if not self._awaiting:
            self._start_command(command, expect, timeout_ms, now)
            return
        result = self._poll_await(now)
        if result == "pending":
            return
        if result != "matched" and not tolerant:
            self._enter_backoff(now)
            return
        self._step += 1

    def _service_join(self, now):
        self._pump_incoming(now)
        if self._step == 0:
            # LANDMINE: poll AT+CWJAP? first to let the module's own
            # post-AT+RST auto-rejoin land -- firing an explicit CWJAP
            # into an in-progress auto-join answers busy/ERROR, observed
            # on gopiv 2026-08-14 as a join->backoff->RST near-livelock
            # (reference/modrobot/wifi_stdio.cpp::serviceJoin()).
            if not self._awaiting:
                expect = "+CWJAP:\"%s\"" % self._ssid
                self._start_command("AT+CWJAP?", expect, 1500, now)
                return
            result = self._poll_await(now)
            if result == "matched":
                self._join_query_attempt = 0
                self._enter_state(_ST_ADDRESS, now)
                return
            if result == "pending":
                return
            self._join_query_attempt += 1
            if self._join_query_attempt < _JOIN_QUERY_ATTEMPTS:
                self._awaiting = False  # re-query; auto-join takes a few seconds
                return
            self._join_query_attempt = 0
            self._step = 1
            self._awaiting = False
            return
        if not self._awaiting:
            command = "AT+CWJAP=\"%s\",\"%s\"" % (self._ssid, self._password)
            self._start_command(command, "OK", _JOIN_TIMEOUT_MS, now)
            return
        result = self._poll_await(now)
        if result == "matched":
            self._enter_state(_ST_ADDRESS, now)
            return
        if result == "pending":
            return
        self._enter_backoff(now)

    def _service_address(self, now):
        self._pump_incoming(now)  # DHCP only; add AT+CIPSTA here for static IP
        if not self._awaiting:
            self._start_command("AT+CWDHCP=1,1", "OK", _CMD_TIMEOUT_MS, now)
            return
        result = self._poll_await(now)
        if result == "pending":
            return
        self._enter_state(_ST_SERVER, now)  # tolerant of match/reject/timeout alike

    def _service_server(self, now):
        self._pump_incoming(now)
        if self._step == 0:
            if not self._awaiting:
                command = "AT+CIPSERVER=1,%d" % self._port
                self._start_command(command, "OK", _CMD_TIMEOUT_MS, now)
                return
            result = self._poll_await(now)
            if result == "pending":
                return
            if result == "matched":
                self._step = 1
                self._awaiting = False
                return
            self._enter_backoff(now)
            return
        if self._step == 1:
            # v5 UDP: SECOND socket (V5_LINK), remote "255.255.255.255",
            # mode 2 -- no peer known needed yet; first datagram teaches it.
            if not self._awaiting:
                command = ("AT+CIPSTART=%d,\"UDP\",\"255.255.255.255\",%d,%d,2"
                           % (V5_LINK, self._discovery_port, self._port))
                self._start_command(command, "OK", _CMD_TIMEOUT_MS, now)
                return
            result = self._poll_await(now)
            if result == "pending":
                return
            if result == "matched":
                self._enter_state(_ST_READY, now)
                return
            self._enter_backoff(now)
            return

    def _service_ready(self, now):
        self._pump_incoming(now)

        # Drain REPL stdout when idle, via the same one-CIPSEND-each send machinery as v5 datagrams.
        if (self._send_phase is None and not self._send_queue
                and self._repl_hook is not None and self._repl_link is not None):
            chunk = self._repl_hook.stdout_pull(512)
            if chunk:
                self._send_queue.append(("repl", self._repl_link, None, chunk))

        if self._send_phase == "await_prompt":
            result = self._poll_await(now)
            if result == "matched":
                self._serial.write(self._send_payload)  # 2nd of 2 writes: command, then payload
                self._send_phase = "await_ok"
                self._start_await(b"SEND OK", _CMD_TIMEOUT_MS, now)
            elif result in ("rejected", "timeout"):
                self._send_phase = None  # drop -- not worth retrying stale data
            return

        if self._send_phase == "await_ok":
            result = self._poll_await(now)
            if result != "pending":
                self._send_phase = None
            return

        if self._send_queue:
            self._pop_next_send(now)

    def _pop_next_send(self, now):
        kind, a, b, data = self._send_queue.pop(0)
        if kind == "v5":
            ip, port = a, b
            command = "AT+CIPSEND=%d,%d,\"%s\",%d" % (V5_LINK, len(data), ip, port)
        else:
            link = a
            command = "AT+CIPSEND=%d,%d" % (link, len(data))
        self._start_command(command, ">", _CMD_TIMEOUT_MS, now)  # 1st of 2 writes
        self._send_payload = data
        self._send_phase = "await_prompt"

    def _service_backoff(self, now):
        self._pump_incoming(now)  # keep draining so stray bytes don't wedge the next bring-up
        if now - self._deadline < 0:
            return
        self._enter_state(_ST_CONFIGURE, now)


def pump(link, now, comms=None):
    """Call once per scheduled-pump tick (same call site as
    `comms.py`'s `PumpTimer`). Advances `link`'s AT pumping, then
    sends boot READY once per NEW v5 peer heard from (Sec 8). `comms`,
    if given, is the SAME instance `link` was registered on."""
    link.service(now)
    if comms is not None and link.poll_new_peer_edge():
        comms.send_ready()


def load_secrets(path="wifi_secrets.json"):
    """Reads `wifi_secrets.json` (gitignored, provided locally; NEVER
    commit one), schema `{"ssid": ..., "password": ...}`. Returns
    `(ssid, password)`, or `(None, None)` if absent/malformed."""
    if json is None:
        return None, None
    try:
        f = open(path)
    except OSError:
        return None, None
    try:
        text = f.read()
    finally:
        f.close()
    try:
        data = json.loads(text)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    return data.get("ssid"), data.get("password")


class NativeWifiSerial:
    """Adapts native `wifiuart` to the AT byte-pipe contract
    `WifiAtLink` expects (`init`/`write`/`any`/`read`); `--with-wifi`
    builds only."""

    def init(self, baudrate):
        wifiuart.init(baudrate=baudrate)

    def write(self, data):
        return wifiuart.write(data)

    def any(self):
        return wifiuart.any()

    def read(self, n):
        return wifiuart.read(n)


class NativeReplHook:
    """Adapts `wifiuart`'s `repl_active`/`stdin_push`/`stdout_pull`
    surface to the `repl_hook` duck-type `WifiAtLink` expects."""

    def set_active(self, active):
        wifiuart.repl_active(active)

    def stdin_push(self, data):
        return wifiuart.stdin_push(data)

    def stdout_pull(self, n):
        return wifiuart.stdout_pull(n)
