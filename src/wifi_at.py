"""wifi_at -- WiFi AT state machine + UDP v5 plane + TCP-REPL demux
(ticket 006, M4).

Owns EVERYTHING the AT dialogue needs: joining the network, `CIPMUX=1`,
bringing up the TCP REPL mirror server and the UDP v5 socket, per-
datagram coalescing (ONE `AT+CIPSEND` per datagram, never per-character
-- PLAN.md's landmine ledger: "per-char AT sends flood the module"), the
>=50 ms telemetry throttle specific to this plane (spec Sec 8), and
READY-on-new-peer-edge handling. See `docs/design/specification.md`
Sec 3/5/8 and `reference/modrobot/wifi_stdio.cpp` (the proven AT-
sequence oracle this module's state machine, `IpdParser`, and `Matcher`
port from -- NOT a straight copy, since that file targeted the old
modrobot module surface and ran the AT dialogue in C++; here it is
Python, per spec Sec 3: "the AT state machine on top is Python").

Split of responsibility with the native `wifiuart` module (ticket 006's
C side, `native/modwifiuart.cpp` + `native/codal_app/wifi_uart_pipe.cpp`
+ `wifi_stdio_hook.cpp`): the C side is a byte-pipe shim over the
module's UARTE1 link (the stock micropython-microbit-v2 port never
exposes the second UARTE, and `microbit.uart.init(tx,rx)` retargets the
ONE stdio UART -- see `native/wifi_uart_fwd.h`) plus a tiny stdin-inject/
stdout-capture ring pair for mirroring the REPL. EVERY byte of AT
dialogue, `+IPD` framing, and datagram coalescing happens HERE, in
Python -- the C side never parses an AT reply or an `+IPD` header.

The UDP v5 plane feeds `src/comms.py`'s SAME `Comms` engine from ticket
005 (`WifiAtLink` implements that module's own Transport contract --
`read_line()`/`send()`/`send_reliable()` -- so `comms.add_transport(link)`
just works), NOT a second protocol engine.

Single-context module access (spec Sec 8): `WifiAtLink.service()` and
the module-level `pump()` below must be called ONLY from the scheduled
pump context (the same `micropython.schedule()`-driven main-context call
site `comms.py`'s own `PumpTimer` uses) -- never from a VM/GC hook or an
IRQ. Every method here is non-blocking by construction (bounded per-call
work, no `time.sleep`/busy-wait loops) -- a deliberate difference from
`wifi_stdio.cpp`'s own blocking `sendRaw()`/`waitFor()` style, which is
safe there only because it runs off the C stdio HAL's own call sites,
never inside a single bounded Python pump tick.

BENCH-TIME NOTE (expanded fully in ticket 009's procedures doc): the
WiFi module persists its AP-join/socket/server state across nRF52
reflashes (PLAN.md's landmine ledger) -- power-cycle the module before
any WiFi bring-up session, or this state machine's own `AT+RST` may
race a module that is mid-way through its own stale auto-rejoin.

MicroPython-only modules (`micropython`'s own `wifiuart`) are import-
guarded so this whole module imports under CPython (this ticket's
offline gate) -- see the top of the file. `json` is also import-guarded
(`load_secrets()` degrades to `(None, None)` without it) since it is not
guaranteed present on every MicroPython build.

Deviations from the radio-robot/wifi_stdio.cpp sources, matching
`wire.py`/`comms.py`'s own precedent: no `from __future__ import
annotations`, no PEP 604/generic-subscript type hints, no f-strings
(project style: CLAUDE.md) -- every function's shape is documented in
its docstring instead.
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

# -- protocol constants -- mirror reference/modrobot/wifi_stdio.cpp -----

V5_LINK = 4  # ESP-AT link id, fixed (kV5Link)
DEFAULT_PORT = 7654  # module's own well-known TCP REPL / UDP local port
DEFAULT_DISCOVERY_PORT = 7655  # host's fixed local port (kV5DiscoveryPort)
TLM_MIN_INTERVAL_MS = 50  # spec Sec 8: ">=50 ms TLM throttle on the WiFi plane"

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

# (command, expect, timeout_ms, tolerant) -- mirrors wifi_stdio.cpp's
# own serviceConfigure() kSteps table exactly, including the AT+RST-
# first ordering (the module is RJ11-powered and keeps its server/
# client links/mux mode/lease across an nRF reset -- rebooting the
# module first is what makes every bring-up start from a clean state).
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
    # =1: +IPD now carries the sender's ip/port inline -- required so the
    # v5 UDP socket (opened in _service_server()) can learn its peer.
    ("AT+CIPDINFO=1", "OK", _CMD_TIMEOUT_MS, True),
)


class _Matcher:
    """Incremental substring matcher -- Python port of
    reference/modrobot/wifi_stdio.cpp's own Matcher: feed one byte at a
    time, True exactly when `token` has just been completed. `token` is
    `bytes` (or None); feeding while unarmed always returns False."""

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
    """Python port of `reference/modrobot/wifi_stdio.cpp`'s own
    `IpdParser`: parses both `+IPD,<link>,<len>:` (CIPDINFO=0) and the
    CIPDINFO=1 extended `+IPD,<link>,<len>,"<ip>",<port>:` form -- both
    forms must parse (see that file's own comment on why)."""

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
        """Feed one byte (int). Returns True exactly when a full header
        (either form) has just been recognized -- `self.link`/`length`/
        `ip`/`port` are valid at that instant."""
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
    """>=50 ms telemetry throttle specific to the WiFi plane (spec Sec 8)
    -- independent of `comms.py`'s own general 25 ms primary-frame
    cadence (`TelemetryPolicy`, ticket 005): this throttle caps how
    often a PERIODIC (non-ack) telemetry push actually goes out over
    THIS plane, even when the engine's own cadence would ask for it more
    often. Deliberately its own tiny class (rather than folded directly
    into `WifiAtLink`) so its timer logic is unit-testable in isolation
    -- see this ticket's own acceptance criteria."""

    def __init__(self, min_interval_ms=TLM_MIN_INTERVAL_MS):
        self._min_interval_ms = min_interval_ms
        self._last_sent_ms = None

    def allow(self, now):
        """True (and records `now`) iff at least `min_interval_ms` has
        elapsed since the last allowed call, or this is the first call
        ever. Never raises; `now` is the same [ms] integer the pump
        passes everywhere else in this codebase."""
        if self._last_sent_ms is None or (now - self._last_sent_ms) >= self._min_interval_ms:
            self._last_sent_ms = now
            return True
        return False


class WifiAtLink:
    """WiFi AT bring-up state machine + the UDP v5 plane's `comms.py`
    Transport (`read_line`/`send`/`send_reliable`) + TCP-REPL demux.

    `serial` is a small duck-typed AT byte-pipe: `init(baudrate)`,
    `write(data: bytes) -> int` (bytes actually accepted, non-blocking),
    `any() -> int`, `read(n) -> bytes` (non-blocking). `NativeWifiSerial`
    below adapts the native `wifiuart` module to this contract; tests
    use a scripted fake.

    `repl_hook`, if given, is a small duck-typed TCP-REPL mirror bridge:
    `set_active(bool)`, `stdin_push(data) -> int`, `stdout_pull(n) ->
    bytes`. `NativeReplHook` below adapts the native `wifiuart` module's
    own repl_active/stdin_push/stdout_pull surface; `None` (the default)
    leaves the REPL mirror inert -- the UDP v5 plane still works fully
    without it (this ticket's own offline gate never wires one)."""

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

    # -- comms.py Transport contract (ticket 005) -- the UDP v5 plane --
    # feeds the SAME engine, never a second protocol engine. ------------

    def read_line(self):
        """Non-blocking. Returns the next complete v5 UDP datagram's raw
        content (no trailing delimiter to strip -- unlike radio_shim.py,
        a UDP datagram IS the message, no framing needed), or None."""
        if not self._v5_rx:
            return None
        return self._v5_rx.pop(0)

    def send(self, data):
        """Queue ONE UDP datagram for the current v5 peer -- ONE
        `AT+CIPSEND` per call, never decomposed per character (spec Sec
        3/8; see `_pop_next_send()`). Silently drops (matches
        wifi_stdio.cpp's own `sendV5Datagram()` failure policy) if not
        READY or no peer is currently known."""
        if self._state != _ST_READY:
            return
        if not self._v5_peer_known_now(self._last_now):
            return
        self._send_queue.append(("v5", self._v5_peer_ip, self._v5_peer_port, bytes(data)))

    def send_reliable(self, text):
        if isinstance(text, str):
            text = text.encode("ascii")
        self.send(text)

    # -- telemetry-specific send, throttled independently of send() -----

    def send_telemetry(self, data, throttle, now):
        """Periodic (non-ack) telemetry push on the WiFi plane, gated by
        `throttle` (a `TlmThrottle` instance -- the caller, e.g. a future
        `telemetry.py`, owns exactly one per WiFi transport). Ordinary
        command replies/acks must use `send()`/`send_reliable()`
        directly, UNTHROTTLED -- an ack's reliability matters more than
        this plane's own AT-command budget, and only a periodic frame is
        what spec Sec 8's ">=50 ms TLM throttle" applies to."""
        if not throttle.allow(now):
            return
        self.send(data)

    # -- new-peer edge (spec Sec 8: "READY on new-peer edge handled in
    # the pump") ----------------------------------------------------

    def poll_new_peer_edge(self):
        """True exactly once per NEW (ip, port) the v5 plane starts
        hearing from -- consumes the edge (a second call before another
        new peer arrives returns False). The pump (see `pump()` below)
        uses this to fire `comms.send_ready()` for a freshly-connected
        WiFi peer, mirroring the boot handshake a fresh radio connection
        gets."""
        current = (
            (self._v5_peer_ip, self._v5_peer_port)
            if self._v5_peer_known_now(self._last_now) else None
        )
        if current is not None and current != self._reported_peer:
            self._reported_peer = current
            return True
        return False

    # -- the state machine ------------------------------------------

    def service(self, now):
        """Advance the AT bring-up / READY-state pumping by one bounded
        step. Call every scheduled-pump tick (single-context: main
        context only, never a VM/GC hook -- spec Sec 8)."""
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
        """The current bring-up state name -- for tests/diagnostics."""
        return self._state

    def _enter_state(self, state, now):
        self._state = state
        self._step = 0
        self._awaiting = False
        self._ipd.reset()
        self._line_buf = bytearray()
        self._payload_remaining = 0
        self._payload_buf = bytearray()

    def _enter_backoff(self, now):
        # Tear down peer/client state -- matches wifi_stdio.cpp's own
        # restart(): AT+RST (the next CONFIGURE pass) wipes every
        # ESP-AT socket on the module side, so the peer relationship and
        # any in-flight send are equally stale.
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

    # -- AT command/await plumbing -- mirrors wifi_stdio.cpp's own
    # sendCommand()/awaitReply(), but NON-BLOCKING: one call per pump
    # tick, never a busy-wait loop (see this module's own docstring for
    # why that is a deliberate difference from the C++ oracle). --------

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
        # ONE write() call for the whole command line -- AT commands
        # here are always well under the UARTE's 250-byte TX buffer
        # (native/codal_app/wifi_uart_pipe.cpp), so a single accepted
        # write is the expected case; this module does not retry a
        # short write (out of scope -- see the module docstring's
        # non-blocking-by-construction note).
        self._serial.write((command_text + "\r\n").encode("ascii"))
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

    # -- incoming byte demux -- Python port of wifi_stdio.cpp's own
    # feedIncoming()/handleStatusLine() ---------------------------------

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
                # The peer is learned/refreshed off the HEADER alone,
                # not the payload -- so an empty datagram still counts
                # as heard-from, exactly like every other byte on this
                # link (matches wifi_stdio.cpp's own comment).
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
        # else: payload on an unrecognized/not-yet-matched link --
        # dropped, matching wifi_stdio.cpp's own "not ready yet" policy.

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
        """`<link>,CONNECT` / `<link>,CLOSED` -- mirrors
        wifi_stdio.cpp's own handleStatusLine(). The v5 UDP link is not
        a TCP client; ESP-AT's mux-mode CIPSTART reports a CONNECT/
        CLOSED lifecycle for it the same as a TCP one, so this is
        explicitly ignored for V5_LINK (else the v5 socket would get
        mistaken for a REPL client)."""
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
            # Newest client wins -- a stale abandoned session otherwise
            # shadows the fresh one (matches wifi_stdio.cpp's own
            # comment).
            self._repl_link = link
            if self._repl_hook is not None:
                self._repl_hook.set_active(True)
        elif status == "CLOSED" and self._repl_link == link:
            self._repl_link = None
            if self._repl_hook is not None:
                self._repl_hook.set_active(False)

    # -- peer-silence lazy-forget -- mirrors wifi_stdio.cpp's own
    # v5PeerKnown(): checked here rather than on a timer so a caller
    # that never asks pays nothing. --------------------------------

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
            # Step 0 polls AT+CWJAP? for the module's own auto-rejoin
            # (after AT+RST) to land -- an explicit CWJAP fired into an
            # in-progress auto-join answers busy/ERROR (wifi_stdio.cpp's
            # own comment on the gopiv 2026-08-14 near-livelock this
            # avoids).
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
        # DHCP only -- this repo's bench convention (spec Sec 2/9) has
        # no static-IP requirement; a future robot needing one can add
        # AT+CIPSTA here without touching the rest of this file.
        self._pump_incoming(now)
        if not self._awaiting:
            self._start_command("AT+CWDHCP=1,1", "OK", _CMD_TIMEOUT_MS, now)
            return
        result = self._poll_await(now)
        if result == "pending":
            return
        # Tolerant of any result -- matches wifi_stdio.cpp's own
        # serviceAddress(), which proceeds regardless of match/reject/
        # timeout.
        self._enter_state(_ST_SERVER, now)

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
            # The v5 UDP plane: a SECOND, independent socket (V5_LINK).
            # Remote "255.255.255.255",discovery_port with mode 2
            # ("remote resets to the last sender") means no peer needs
            # to be known yet -- the host broadcasts until this robot
            # answers, and the first datagram heard teaches the real
            # peer (see _feed_byte()'s own IPD handling).
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

        # Drain the REPL mirror's captured stdout once nothing else is
        # already in flight -- queued through the SAME send machinery
        # below, so a REPL reply and a v5 datagram are both subject to
        # the identical one-CIPSEND-per-datagram discipline.
        if (self._send_phase is None and not self._send_queue
                and self._repl_hook is not None and self._repl_link is not None):
            chunk = self._repl_hook.stdout_pull(512)
            if chunk:
                self._send_queue.append(("repl", self._repl_link, None, chunk))

        if self._send_phase == "await_prompt":
            result = self._poll_await(now)
            if result == "matched":
                # ONE write() call for the payload -- the second (and
                # last) write of this datagram's exactly-two-writes
                # shape (command, then payload).
                self._serial.write(self._send_payload)
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
        # ONE write() call for the command -- the first of this
        # datagram's exactly-two-writes shape.
        self._start_command(command, ">", _CMD_TIMEOUT_MS, now)
        self._send_payload = data
        self._send_phase = "await_prompt"

    def _service_backoff(self, now):
        self._pump_incoming(now)  # keep draining so stray bytes don't wedge the next bring-up
        if now - self._deadline < 0:
            return
        self._enter_state(_ST_CONFIGURE, now)


def pump(link, now, comms=None):
    """Call once per scheduled-pump tick (the same
    `micropython.schedule()`-driven main-context call site `comms.py`'s
    own `PumpTimer` uses -- spec Sec 5/8, single-context module access).

    Advances `link`'s AT bring-up/READY-state byte pumping, then --
    spec Sec 8's "READY on new-peer edge handled in the pump" -- sends
    the boot READY line once per NEW v5 peer this plane starts hearing
    from. `comms`, if given, is the SAME `comms.Comms` instance `link`
    was registered on via `comms.add_transport(link)` (ticket 005) --
    the UDP v5 plane feeds that one engine, never a second protocol
    engine (this ticket's own acceptance criteria)."""
    link.service(now)
    if comms is not None and link.poll_new_peer_edge():
        comms.send_ready()


def load_secrets(path="wifi_secrets.json"):
    """Reads `wifi_secrets.json` (gitignored, provided locally at bench
    time -- see CLAUDE.md/README.md; NEVER commit one) if present.
    Expected schema: `{"ssid": "...", "password": "..."}` -- see
    `wifi_secrets.example.json` for a placeholder template. Returns
    `(ssid, password)`, or `(None, None)` if the file is absent,
    unreadable, or malformed -- never raises (a missing secrets file at
    bench time is an expected, offline-testable condition, not an
    error)."""
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
    """Adapts the native `wifiuart` module (native/modwifiuart.cpp,
    ticket 006) to the small duck-typed AT byte-pipe contract
    `WifiAtLink` expects (`init`/`write`/`any`/`read`) -- see
    `native/wifi_uart_fwd.h` for the C side. Only usable on a
    `--with-wifi` build; every method here is a thin one-line forward
    to the `wifiuart` module, so a missing import surfaces immediately
    as an `AttributeError` on first use -- the correct failure mode for
    on-device code that should never run without the module it depends
    on."""

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
