"""M5-stabilisation / sprint 007 ticket 006 gate: `src/core/boot.py`'s
power-on assembly sequence, under CPython.

  - happy path: valid config -> diffdrive configured, comms + radio
    transport up (wired to a real ProtocolAdapter), pump started,
    banner/READY emitted;
  - fail-closed path: invalid/missing config -> motion refused
    (diffdrive never armed -- backed by a `_NullDiffDrive` instead),
    comms/REPL still available and still answers the wire;
  - no-secrets path: wifi_secrets.json absent -> WiFi transport not
    started, everything else proceeds normally.

No hardware, no native modules -- `boot.py` is import-guarded against
`diffdrive`/`microbit`/`utime`, and every hardware-touching dependency
`run()` needs is an injectable parameter, defaulted here with small
stand-ins (see `_StubDiffDrive`, `_FakeWifiSerial` below).
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
DATA_DIR = REPO_ROOT / "data"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import boot  # noqa: E402  (path must be set up first)
from core import protocol  # noqa: E402
from hardware import protocol_adapter  # noqa: E402


class _StubDiffDrive:
    """Records configure/drive-side calls `motion.MoveQueue`/
    `ProtocolAdapter` might make."""

    def __init__(self):
        self.configure_calls = []
        self.drive_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0
        self._position = 0.0

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)
        return "ok"

    def drive(self, v, twist, lease_ms):
        self.drive_calls.append((v, twist, lease_ms))
        self._position += v
        return "ok"

    def neutral(self):
        self.neutral_calls += 1

    def estop(self):
        self.estop_calls += 1

    def output(self):
        return {"positionLeft": self._position, "positionRight": self._position}


class _FakeWifiSerial:
    """Minimal duck-typed AT byte-pipe -- `WifiAtLink.__init__` only
    calls `init()` at construction; `service()` is never invoked here,
    so `write`/`any`/`read` just need to exist."""

    def __init__(self):
        self.baudrate = None

    def init(self, baudrate):
        self.baudrate = baudrate

    def write(self, data):
        return len(data)

    def any(self):
        return 0

    def read(self, n):
        return b""


def _missing_path(tmp_path, name="does_not_exist.json"):
    return str(tmp_path / name)


class _RecordingTransport:
    """Duck-typed Comms Transport (`read_line`/`send`/`send_reliable`)
    that yields pre-scripted lines and records every `send_reliable()`
    call -- proves the pump chain (`PumpTimer.tick()` -> `Comms.pump()`
    -> the transport's own `ProtocolHandler`) is wired end-to-end from
    a `BootResult`, via an actual wire round-trip (PING -> pong)."""

    def __init__(self, lines=None):
        self._lines = list(lines) if lines else []
        self.sent = []

    def read_line(self):
        if not self._lines:
            return None
        return self._lines.pop(0)

    def send(self, data):
        self.sent.append(bytes(data))

    def send_reliable(self, text):
        if isinstance(text, str):
            text = text.encode("ascii")
        self.sent.append(text)


def _tick_and_get_replies(result, line=b"PING #1"):
    """Register a one-shot transport carrying `line`, tick the pump
    once, and return whatever the transport's own handler replied --
    the shared "pump reaches comms.pump() end to end" proof used below.
    `PING` is sequenced as of the 2026-08-21 reliability-layer retarget
    (protocol.md Sec 8.3/8.4) and needs a mandatory `#id`; `#1` is
    always in order here since each call registers a FRESH transport,
    hence a fresh ProtocolHandler with `expected_next` still at 1."""
    transport = _RecordingTransport([line])
    result.comms.add_transport(transport)
    result.pump_timer.tick()
    return transport.sent


# --- happy path ----------------------------------------------------------

def test_happy_path_configures_diffdrive_and_boots_comms(tmp_path):
    stub = _StubDiffDrive()
    result = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=stub,
    )

    assert result.config_error is None
    assert result.config_ok() is True
    # run() RELEASES the parsed document once the scalars are extracted --
    # it is ~6.9 KB of a ~16.7 KB device heap (measured on tovez), the
    # largest resident allocation there was. config_ok() is the readiness
    # flag precisely because `robot_config is not None` no longer answers
    # that question.
    assert result.robot_config is None
    assert result.config_loaded is True

    assert len(stub.configure_calls) == 1
    kwargs = stub.configure_calls[0]
    assert kwargs["left_port"] == 2
    assert kwargs["right_port"] == 1
    assert result.diffdrive_ready is True

    # dispatch wired to a real ProtocolAdapter, backed by the real stub
    # diffdrive -- never None (module docstring: comms always needs one).
    assert isinstance(result.dispatch, protocol_adapter.ProtocolAdapter)
    name, serial, drivetrain, profile, version = result.dispatch.identity()
    assert name == "tovez"          # identity.uid
    assert profile == "tovez"       # identity.robot_name
    assert drivetrain == "differential"
    assert serial.startswith("f137c0")
    assert version == boot.VERSION

    # comms + radio transport up.
    assert result.comms is not None
    assert result.radio_link is not None
    assert result.comms.transport_count() == 1  # radio only -- no secrets

    # pump started: a tick reaches comms.pump() and the fresh transport's
    # OWN handler answers PING for real -- the ack fires first
    # (protocol.md Sec 8.1, unconditional on an in-order id), THEN
    # PING's own "pong <now>" reply.
    assert result.pump_timer is not None
    replies = _tick_and_get_replies(result, line=b"PING #1")
    assert len(replies) == 2
    assert replies[0] == b"ack 1 0"
    assert replies[1].startswith(b"pong ")

    # banner/READY already emitted during run() -- a fresh transport
    # registered after boot gets the exact banner text back.
    replies = _tick_and_get_replies(result, line=b"HELLO")
    assert replies == [("device NEZHA2 robot %s %s" % (name, serial)).encode("ascii")]


# --- fail-closed path ------------------------------------------------------

def test_fail_closed_path_refuses_motion_but_keeps_comms_alive(tmp_path):
    stub = _StubDiffDrive()
    result = boot.run(
        config_path=str(FIXTURES_DIR / "robot_config_malformed.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=stub,
    )

    # config load failed, fail-closed -- recorded, not raised out of run().
    assert result.robot_config is None
    assert result.config_ok() is False
    assert result.config_error is not None

    # diffdrive never armed.
    assert stub.configure_calls == []
    assert result.diffdrive_ready is False

    # motion refused: the ProtocolAdapter is still real (comms needs one
    # regardless), but it is backed by a no-op _NullDiffDrive -- WHEELS
    # is refused (NOT_CONFIGURED) and the REAL stub diffdrive is never
    # touched.
    assert isinstance(result.dispatch, protocol_adapter.ProtocolAdapter)
    result_code = result.dispatch.on_wheels(100.0, 100.0, 500.0, 1)
    assert result_code == protocol.Result.NOT_CONFIGURED
    assert stub.drive_calls == []

    # comms/REPL still available -- banner/READY still emit even with
    # config failed.
    assert result.comms is not None
    name, _serial, _drivetrain, _profile, _version = result.dispatch.identity()
    assert name == "unconfigured"
    assert result.radio_link is not None
    assert result.comms.transport_count() == 1

    # the pump still runs, and the wire still answers -- comms stays
    # serviceable even in the fail-closed case.
    replies = _tick_and_get_replies(result, line=b"PING #1")
    assert len(replies) == 2
    assert replies[0] == b"ack 1 0"
    assert replies[1].startswith(b"pong ")


def test_fail_closed_path_missing_file(tmp_path):
    result = boot.run(
        config_path=_missing_path(tmp_path, "no_such_robot.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=_StubDiffDrive(),
    )
    assert result.robot_config is None
    assert result.diffdrive_ready is False
    assert result.comms is not None  # still boots comms/banner/READY
    assert isinstance(result.dispatch, protocol_adapter.ProtocolAdapter)


# --- no-secrets path ---------------------------------------------------

def test_no_secrets_path_skips_wifi_but_boots_everything_else(tmp_path):
    stub = _StubDiffDrive()
    result = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=_missing_path(tmp_path),  # wifi_secrets.json absent
        diffdrive_module=stub,
    )

    assert result.wifi_link is None
    assert result.comms.transport_count() == 1  # radio only

    # everything else proceeds normally -- same happy-path assertions.
    assert result.diffdrive_ready is True
    assert isinstance(result.dispatch, protocol_adapter.ProtocolAdapter)
    replies = _tick_and_get_replies(result)
    assert len(replies) == 2
    assert replies[0] == b"ack 1 0"
    assert replies[1].startswith(b"pong ")


def test_secrets_present_starts_wifi_transport(tmp_path):
    """Complement of the no-secrets test -- when wifi_secrets.json IS
    present, a WiFi transport is constructed and registered alongside
    radio."""
    secrets_path = tmp_path / "wifi_secrets.json"
    secrets_path.write_text(json.dumps({"ssid": "testnet", "password": "testpass"}))

    stub = _StubDiffDrive()
    result = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=str(secrets_path),
        diffdrive_module=stub,
        wifi_serial_factory=_FakeWifiSerial,
        wifi_repl_hook_factory=None,
    )

    assert result.wifi_link is not None
    assert result.comms.transport_count() == 2  # radio + wifi


# --- bench-debug accessor (sprint 007 ticket 009) -----------------------

def test_last_result_returns_the_most_recent_run(tmp_path):
    """`boot.last_result()` is the escape hatch a bench REPL session
    uses to reach `wifi_link.state()` after the automatic power-on
    `run()` call (whose return value `main.c` discards) -- ticket 009's
    own bring-up session hit exactly this gap live on tovez. Confirm
    it tracks the latest call and is not stale from a previous one."""
    stub = _StubDiffDrive()
    first = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=stub,
    )
    assert boot.last_result() is first

    secrets_path = tmp_path / "wifi_secrets.json"
    secrets_path.write_text(json.dumps({"ssid": "testnet", "password": "testpass"}))
    second = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=str(secrets_path),
        diffdrive_module=stub,
        wifi_serial_factory=_FakeWifiSerial,
        wifi_repl_hook_factory=None,
    )
    assert boot.last_result() is second
    assert boot.last_result() is not first
    assert boot.last_result().wifi_link is not None


# --- boot never blocks / never raises for the documented cases ---------

def test_run_never_raises_for_bad_or_missing_config(tmp_path):
    for path in (
        str(FIXTURES_DIR / "robot_config_malformed.json"),
        _missing_path(tmp_path),
    ):
        # run() must never propagate ConfigError -- fail-closed means
        # continue booting, not abort.
        boot.run(
            config_path=path,
            secrets_path=_missing_path(tmp_path),
            diffdrive_module=_StubDiffDrive(),
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
