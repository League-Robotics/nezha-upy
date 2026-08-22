"""Sprint 007 ticket 007 gate: byte-exact loopback test against
`protocol.md`'s own literal examples, driven through the REAL,
boot-assembled engine (`core.boot.run()`, real `comms.Comms`/
`core.protocol.ProtocolHandler`/`hardware.protocol_adapter.
ProtocolAdapter`, a fake `diffdrive` module standing in for hardware --
this repo's established `tests/test_boot_sequence.py` fake-injection
convention) rather than a mock adapter (`tests/unit/
test_protocol_golden_vectors.py`) or a hand-built
`comms.Comms(_FakeAdapter())` (`tests/test_comms_loopback.py`). This is
the one offline test that proves the WIRING from ticket 006, not just
the class tickets 001-005 already cover in isolation (sprint.md's Test
Strategy: "the one offline test that stands in for 'does the wiring,
not just the class, work'").

**Design-authority retarget (sprint 007 tickets 012/013, 2026-08-21) --
historical note.** This file originally pinned the last COMMITTED
revision of `protocol.md` (`ok [#id]`/`err [#id] <code>`, `ESTOP` never
replies even when malformed, non-mandatory/non-sequential ids,
`HELP`'s 12-verb sprint-scoped list) over an uncommitted draft rewrite
that existed even at that ticket's own time -- a deliberate, considered
decision, recorded at length below for the record of what was decided
and why, NOT because the reasoning was wrong at the time:

    At the time this ticket was worked, `radio-robot-lib`'s own working
    tree carried an UNCOMMITTED draft rewrite of `protocol.md` (a
    mandatory-sequence-id `ack`/`nack` reliability layer, new
    `RUN`/`debug` verbs, `ESTOP` gaining a reply) -- `git diff --
    docs/design/protocol.md` in that repo showed ~540 lines of unstaged
    changes, none of it committed. That draft was judged NOT that
    ticket's design authority: it had landed in no gated review, and
    this sprint's own architecture (sprint.md's Design Rationale;
    SUC-002, "ESTOP never replies, even when malformed") was built
    against, and matched byte-for-byte, the last COMMITTED revision. If
    the uncommitted draft were to land as its own commit, it was
    flagged as describing a wire-breaking redesign needing its own
    sprint, not a ticket-sized fix.

That "own sprint" arrived: the stakeholder's 2026-08-21 retarget
decision (sprint 007 ticket 012's own issue,
[[retarget-v6-port-to-reliability-layer-draft]]) explicitly OVERRIDES
the resolution above. `reference/protocol-draft-2026-08-21.md` (this
repo's own verbatim snapshot of that draft, taken by ticket 012) is now
the current design authority for this file, and ticket 013 is the
retarget record for every literal reply string this file pins --
`ack`/`nack` mandatory sequencing, `ok`'s deletion, `err`'s field-order
flip, `ESTOP`'s reply flip, and `HELP`'s growth to 13 verbs (`RUN` now
in scope). The 12-verb/silent-ESTOP text this docstring used to carry
is preserved above as the changelog record of a real decision that was
later, explicitly superseded -- not silently dropped as if no one had
thought about it.

Every literal reply string below is TRANSCRIBED from
`reference/protocol-draft-2026-08-21.md` (ticket 013's own re-pin), not
copied from a first passing run of this port.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
DATA_DIR = REPO_ROOT / "data"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import boot  # noqa: E402  (path must be set up first)


# --- a small, self-contained fake diffdrive (this repo's per-file-fake
# convention -- mirrors tests/test_boot_sequence.py's own _StubDiffDrive
# and tests/test_protocol_adapter.py's own _FakeDiffDrive) ----------------

class _FakeDiffDrive(object):
    """Records ``configure()``/``drive()`` calls; ``output()`` reports a
    FIXED, deterministic health snapshot so this file's ``STATUS``
    assertions do not depend on kernel internals this ticket does not
    exercise -- only ticket 007's own wiring claim, not the kernel's."""

    def __init__(self):
        self.configure_calls = []
        self.drive_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)

    def drive(self, velocity, twist, lease_ms):
        self.drive_calls.append((velocity, twist, lease_ms))
        return "ok"

    def neutral(self):
        self.neutral_calls += 1

    def estop(self):
        self.estop_calls += 1

    def output(self):
        return {
            "ready": True, "estopped": False, "leaseExpired": False,
            "stallHalted": False, "connectedLeft": True,
            "connectedRight": False, "velocity": 0.0, "twist": 0.0,
        }


# --- in-process pipe / loopback transport (matches test_comms_loopback.
# py's own _Pipe/LoopbackTransport convention -- v6 lines are plain
# ASCII text, no COBS/wire-codec demuxer needed here) ---------------------

class _Pipe(object):
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


class _LoopbackTransport(object):
    """Duck-typed Comms Transport (`read_line`/`send`/`send_reliable`),
    the same shape `radio_shim.RadioLink`/`wifi_at.WifiAtLink` and
    `test_comms_loopback.py`'s own loopback fixture present."""

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


def _make_host_harness(result):
    """Registers one MORE transport on the already-booted
    ``result.comms`` (alongside boot's own real radio transport) and
    returns a helper that sends one line, ticks the REAL boot-assembled
    pump once (`result.pump_timer.tick()` -> `comms.pump()` -> this
    transport's own `ProtocolHandler`), and returns every reply line the
    wire produced for it. Mirrors `test_boot_sequence.py`'s own
    `_tick_and_get_replies()`, kept local here (this repo's per-file-fake
    convention) since this file drives a whole CONVERSATION over one
    persistent transport rather than a one-shot line per call."""
    device_to_host = _Pipe()
    host_to_device = _Pipe()
    device_transport = _LoopbackTransport(inbound=host_to_device, outbound=device_to_host)
    assert result.comms.add_transport(device_transport) is True

    def send_and_pump(line_bytes):
        host_to_device.write_line(line_bytes)
        result.pump_timer.tick()
        replies = []
        while True:
            reply = device_to_host.read_line()
            if reply is None:
                break
            replies.append(reply)
        return replies

    return send_and_pump


def _boot(tmp_path, now_ms=42424):
    """Boots the REAL engine (`core.boot.run()`) against
    `data/tovez.json`, with a fake `diffdrive` standing in for hardware
    -- no native module, no radio hardware, matching
    `test_boot_sequence.py`'s own happy-path fixture. `now_ms` is fixed
    so `PING`'s `pong <now>` reply is byte-exact, not merely
    ``startswith``."""
    stub = _FakeDiffDrive()
    result = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=str(tmp_path / "wifi_secrets.json"),  # absent -- no WiFi
        diffdrive_module=stub,
        now_fn=lambda: now_ms,
    )
    # Real ProtocolAdapter, real MoveQueue/diffdrive path -- not the
    # fail-closed _NullDiffDrive fallback (boot.py module docstring).
    assert result.diffdrive_ready is True
    # BootResult is a plain-attribute object by design ("so tests can
    # assert on each piece directly" -- its own docstring); stash the
    # fake stub on it so a test needing to assert on-adapter effects
    # (e.g. ESTOP reaching the real kernel) does not need its own,
    # parallel boot() call just to keep a reference to it.
    result.diffdrive = stub
    return result


def _status_dict(status_line):
    """Parses a ``status k=v k=v ...`` reply into a dict -- protocol.md
    Sec 6 states STATUS's key ORDER is not guaranteed ("k=v, order not
    guaranteed, unknown keys ignored"), so this file asserts key
    PRESENCE and VALUE, never whole-line position."""
    assert status_line.startswith(b"status ")
    pairs = status_line[len(b"status "):].split(b" ")
    out = {}
    for pair in pairs:
        key, _, value = pair.partition(b"=")
        out[key] = value
    return out


# --- the byte-exact assertions, transcribed from protocol.md -------------

def test_banner_and_hello_match_protocol_md_literal_banner_shape(tmp_path):
    """protocol.md Sec 3 (``sendBanner()``) / Sec 6 (`HELLO`'s own
    reply, byte-identical to the banner): ``device NEZHA2 robot <name>
    <serial>`` -- ``name`` = ``identity.uid``, ``serial`` =
    ``connection.serial_last_6`` (`data/tovez.json`: ``"tovez"`` /
    ``"f137c0"``, per ``boot.py``'s own field-mapping note)."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    assert send_and_pump(b"HELLO") == [b"device NEZHA2 robot tovez f137c0"]


def test_ping_matches_protocol_md_literal_pong_now_shape(tmp_path):
    """protocol.md Sec 6 table: ``PING`` -> ``pong <now>``, ``now`` =
    robot clock ``[ms]``. ``PING`` is sequenced as of the 2026-08-21
    retarget (Sec 8.3/8.4) -- a mandatory ``#id`` now carries the
    command, and the ``ack <id> <lastDone>`` line (Sec 8.1) fires
    unconditionally, ahead of ``PING``'s own informational reply (Sec
    9.8 item 4: "ack first, always")."""
    result = _boot(tmp_path, now_ms=42424)
    send_and_pump = _make_host_harness(result)

    assert send_and_pump(b"PING #1") == [b"ack 1 0", b"pong 42424"]


def test_id_and_ver_match_protocol_md_literal_shapes(tmp_path):
    """protocol.md Sec 6 table: ``ID`` -> ``id <drivetrain> <profile>
    <version>``; ``VER`` -> ``ver <version>``. Both are sequenced now
    -- each command below carries the next mandatory, strictly
    increasing id on this transport's own handler, each acked ahead of
    its own reply."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    version = boot.VERSION.encode("ascii")
    assert send_and_pump(b"ID #1") == [
        b"ack 1 0", b"id differential tovez " + version]
    assert send_and_pump(b"VER #2") == [b"ack 2 0", b"ver " + version]


def test_status_carries_every_protocol_md_key_present_not_positional(tmp_path):
    """protocol.md Sec 6 table: ``STATUS`` -> ``status ready=1 active=0
    connL=1 connR=1 otos=0 wedge=0 flags=<hex> tlm=off next=<n>`` -- "k=v,
    order not guaranteed" (asserted by key/value below, not whole-line
    equality). ``next`` (Sec 8.7, added 2026-08-21) is the handler's own
    ``expected_next`` -- 2 here, since the in-order ``#1`` this test
    sends is the only id this handler has ever accepted."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    replies = send_and_pump(b"STATUS #1")
    assert len(replies) == 2
    assert replies[0] == b"ack 1 0"
    fields = _status_dict(replies[1])
    assert set(fields.keys()) == {
        b"ready", b"active", b"connL", b"connR", b"otos", b"wedge",
        b"flags", b"tlm", b"next",
    }
    assert fields[b"ready"] == b"1"    # _FakeDiffDrive.output()["ready"] = True
    assert fields[b"active"] == b"0"   # velocity == twist == 0.0 -- not moving
    assert fields[b"connL"] == b"1"    # output()["connectedLeft"] = True
    assert fields[b"connR"] == b"0"    # output()["connectedRight"] = False
    assert fields[b"otos"] == b"0"     # no OTOS wired this sprint (sprint.md Scope)
    assert fields[b"wedge"] == b"0"    # no line sensor wired this sprint
    assert fields[b"flags"] == b"11"   # READY(0x1) | CONNECTED_LEFT(0x10), lowercase hex
    assert fields[b"tlm"] == b"off"    # ProtocolAdapter's own default subscription
    assert fields[b"next"] == b"2"     # expected_next after accepting #1


def test_help_matches_this_sprints_own_scoped_13_verb_list(tmp_path):
    """Renamed from the pre-retarget "...12_verb_list" (sprint 007
    ticket 013): ``RUN`` came into scope with ticket 012's 2026-08-21
    reliability-layer retarget, so ``HELP``'s reply now matches
    ``reference/protocol-draft-2026-08-21.md``'s own Sec 6 table row
    literally -- 13 verbs, ``RUN`` last -- rather than the 12-verb,
    RUN-excluded list this test used to pin as a deliberate scope
    reduction. Reached via a mandatory in-order id now that ``HELP``
    itself is sequenced, generated the same way Sec 4 says HELP must be
    ("from the same table dispatch() uses, so it cannot drift")."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    assert send_and_pump(b"HELP #1") == [
        b"ack 1 0",
        b"help HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP "
        b"ESTOP RUN",
    ]


def test_wheels_and_stop_ack_and_err_pair_matches_protocol_md_literal_shapes(tmp_path):
    """protocol.md Sec 8.1/8.2/8.6: ``ack <id> <lastDone>`` (every
    in-order command, accepted or not) / ``err <code> #<id>`` (layered
    on top, only on rejection) -- exercised here via a
    ``WHEELS``/``STOP`` round trip, through the REAL
    ``ProtocolAdapter.on_wheels()``/``on_stop()``, not a mock. ``ok`` is
    gone (Sec 8.2): the ack alone is the acceptance signal for a
    successful ``WHEELS``/``STOP``."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    # Accepted: within the 5000 ms WHEELS ceiling (protocol.md Sec 5
    # point 1 / Sec 9.1) -- just the ack, carrying the id the command
    # sent; no more standalone "ok".
    assert send_and_pump(b"WHEELS 50 50 500 #1") == [b"ack 1 0"]

    # Rejected: OVER the 5000 ms ceiling -- the ack still fires
    # (Sec 8.2: an in-order command is acked regardless of content),
    # THEN "err 3 #<id>" layers on top -- code 3 is ERR_RANGE
    # (protocol.md Sec 6.1's code table), enforced by the adapter (the
    # handler itself holds no bounds table, Sec 9.1). Field order is
    # code-first, id-last (Sec 8.6).
    assert send_and_pump(b"WHEELS 50 50 6000 #2") == [b"ack 2 0", b"err 3 #2"]

    # STOP always accepted (protocol.md Sec 5.1: `neutral()` has no
    # refusal path of its own) -- just the ack, carrying STOP's own
    # mandatory id.
    assert send_and_pump(b"STOP #3") == [b"ack 3 0"]


def test_estop_reply_flip_matches_protocol_md_through_the_real_engine(tmp_path):
    """protocol.md Sec 8.3, flipped 2026-08-21: ``ESTOP`` now ALWAYS
    replies the bare word ``estop``, with the kernel call executed
    BEFORE that reply is written -- superseding the pre-retarget
    "ESTOP never replies" rule this file used to pin (SUC-002's own
    flip, ticket 012's Step 3). This is exactly the kind of thing that
    could be right in ``protocol.py``'s own handler and wrong in how
    ``comms.py``'s ``_TransportSink`` bridges it back onto the wire --
    this file's whole reason to exist is proving the WIRING, not just
    the class (module docstring), so this test drives ``ESTOP`` through
    the REAL boot-assembled engine, not the mock-adapter harness ticket
    012 already covers in ``tests/unit/test_protocol_golden_vectors.py``.
    ``ESTOP`` is unsequenced (Sec 8.3) -- no id, and it must not disturb
    a handler that has already accepted other sequenced commands."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    # A sequenced command first, so this test also proves ESTOP does
    # not consume or disturb the sequence it sits outside of.
    assert send_and_pump(b"PING #1") == [b"ack 1 0", b"pong 42424"]

    assert send_and_pump(b"ESTOP") == [b"estop"]
    assert result.diffdrive.estop_calls == 1, (
        "on_estop() must have reached the REAL, boot-assembled "
        "DifferentialDrive stub through comms.py/protocol_adapter.py's "
        "own wiring, not just a mock handler")

    # The sequence is untouched -- the next in-order id is still #2.
    assert send_and_pump(b"PING #2") == [b"ack 2 0", b"pong 42424"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
