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

Every literal reply string asserted below is TRANSCRIBED from
`radio-robot-lib`'s `docs/design/protocol.md` Sec 2/3/4/6 -- NOT
copy-pasted from a first passing run of this port (this ticket's own
acceptance criterion).

Byte-level disagreement found while writing this test, and how it was
resolved (this ticket's own instruction: report, don't silently absorb
or weaken):

1. **Design-authority resolution.** At the time this ticket was worked,
   `radio-robot-lib`'s own working tree carried an UNCOMMITTED draft
   rewrite of `protocol.md` (a mandatory-sequence-id `ack`/`nack`
   reliability layer, new `RUN`/`debug` verbs, `ESTOP` gaining a reply)
   -- `git diff -- docs/design/protocol.md` in that repo shows ~540
   lines of unstaged changes as of this writing, none of it committed.
   That draft is NOT this ticket's design authority: it has landed in
   no gated review, and this sprint's own architecture (sprint.md's
   Design Rationale; SUC-002, "ESTOP never replies, even when
   malformed") was built against, and matches byte-for-byte, the last
   COMMITTED revision (`git log`: `a380495` colon->space/`#id` grammar
   migration, `34d12c2` doc consolidation, `c99e6e8` debug/RUN --
   `c99e6e8` itself does NOT touch Sec 8/the ack/nack layer). This file
   pins against that committed text (`ok [#id]`/`err [#id] <code>`,
   `ESTOP` never replies, non-mandatory/non-sequential ids). If/when the
   uncommitted draft lands as its own commit, it describes a
   wire-breaking redesign that needs its own sprint, not a ticket-sized
   fix -- flagged here so it is not mistaken for something this ticket
   should have implemented.
2. **`HELP`'s verb count.** Even the committed doc's own Sec 6 table row
   lists 13 verbs, `... STOP ESTOP RUN` -- but `RUN` is explicitly out
   of this sprint's verb scope (sprint.md's Architecture Overview;
   `core/protocol.py`'s own module docstring: "`RUN`... NEITHER is
   ported here at all, not even deferred to a later ticket"). This is a
   real, byte-level divergence between the doc's literal text and this
   port, so `test_help_matches_this_sprints_own_scoped_12_verb_list`
   below pins the ACTUAL, sprint-scoped 12-verb `HELP` text rather than
   the doc's literal 13-verb row -- a scope decision already recorded
   before this ticket, not a new bug to fix here (fixing it would mean
   porting `RUN`, which sprint.md explicitly does not do).

No other disagreement was found: banner, `PING`/`pong`, `ID`/`VER`, the
`WHEELS`/`STOP` `ok`/`err` pair, and `STATUS`'s field set all matched
the committed doc text exactly on the first pass.
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
    robot clock ``[ms]``."""
    result = _boot(tmp_path, now_ms=42424)
    send_and_pump = _make_host_harness(result)

    assert send_and_pump(b"PING") == [b"pong 42424"]


def test_id_and_ver_match_protocol_md_literal_shapes(tmp_path):
    """protocol.md Sec 6 table: ``ID`` -> ``id <drivetrain> <profile>
    <version>``; ``VER`` -> ``ver <version>``."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    version = boot.VERSION.encode("ascii")
    assert send_and_pump(b"ID") == [b"id differential tovez " + version]
    assert send_and_pump(b"VER") == [b"ver " + version]


def test_status_carries_every_protocol_md_key_present_not_positional(tmp_path):
    """protocol.md Sec 6 table: ``STATUS`` -> ``status ready=1 active=0
    connL=1 connR=1 otos=0 wedge=0 flags=<hex> tlm=off`` -- "k=v, order
    not guaranteed" (asserted by key/value below, not whole-line
    equality)."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    replies = send_and_pump(b"STATUS")
    assert len(replies) == 1
    fields = _status_dict(replies[0])
    assert set(fields.keys()) == {
        b"ready", b"active", b"connL", b"connR", b"otos", b"wedge",
        b"flags", b"tlm",
    }
    assert fields[b"ready"] == b"1"    # _FakeDiffDrive.output()["ready"] = True
    assert fields[b"active"] == b"0"   # velocity == twist == 0.0 -- not moving
    assert fields[b"connL"] == b"1"    # output()["connectedLeft"] = True
    assert fields[b"connR"] == b"0"    # output()["connectedRight"] = False
    assert fields[b"otos"] == b"0"     # no OTOS wired this sprint (sprint.md Scope)
    assert fields[b"wedge"] == b"0"    # no line sensor wired this sprint
    assert fields[b"flags"] == b"11"   # READY(0x1) | CONNECTED_LEFT(0x10), lowercase hex
    assert fields[b"tlm"] == b"off"    # ProtocolAdapter's own default subscription


def test_help_matches_this_sprints_own_scoped_12_verb_list(tmp_path):
    """protocol.md's own committed Sec 6 table row lists 13 verbs
    (``HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP ESTOP
    RUN``) -- but ``RUN`` is explicitly out of this sprint's verb scope
    (sprint.md's Architecture Overview; ``core/protocol.py``'s own
    module docstring: "NEITHER [RUN nor debug] is ported here at all,
    not even deferred to a later ticket"). This is the one byte-level
    disagreement between the doc's literal text and this port found
    while writing this test (see module docstring) -- NOT a bug to fix
    here, since fixing it would mean porting RUN, which sprint.md
    explicitly does not do this sprint. Pinned against the 12-verb list
    this port's own ``VERB_TABLE`` actually produces, generated the same
    way protocol.md Sec 4 says HELP must be ("from the same table
    dispatch() uses, so it cannot drift") -- just a smaller table than
    the archetype's."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    assert send_and_pump(b"HELP") == [
        b"help HELLO PING ID VER STATUS HELP GET SET TLM WHEELS STOP ESTOP"
    ]


def test_wheels_and_stop_ok_and_err_pair_matches_protocol_md_literal_shapes(tmp_path):
    """protocol.md Sec 6.1: ``ok [#id]`` (accepted) / ``err [#id]
    <code>`` (rejected) -- exercised here via a ``WHEELS``/``STOP``
    round trip (this ticket's own acceptance criterion), through the
    REAL ``ProtocolAdapter.on_wheels()``/``on_stop()``, not a mock."""
    result = _boot(tmp_path)
    send_and_pump = _make_host_harness(result)

    # Accepted: within the 5000 ms WHEELS ceiling (protocol.md Sec 5
    # point 1 / Sec 9.1) -- "ok", carrying the SAME id the command sent.
    assert send_and_pump(b"WHEELS 50 50 500 #10") == [b"ok #10"]

    # Rejected: OVER the 5000 ms ceiling -- "err", code 3 (ERR_RANGE,
    # protocol.md Sec 6.1's code table), enforced by the adapter (the
    # handler itself holds no bounds table, Sec 9.1).
    assert send_and_pump(b"WHEELS 50 50 6000 #11") == [b"err #11 3"]

    # STOP always accepted (protocol.md Sec 5.1: `neutral()` has no
    # refusal path of its own) -- "ok", carrying STOP's own (required)
    # id.
    assert send_and_pump(b"STOP #12") == [b"ok #12"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
