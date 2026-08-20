"""M5-stabilisation gate: `src/boot.py`'s power-on assembly sequence,
under CPython.

  - happy path: valid config -> diffdrive configured/begun/started,
    comms + radio transport up, pump started, banner/READY emitted;
  - fail-closed path: invalid/missing config -> motion refused
    (diffdrive never armed), comms/REPL still available;
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
from hardware import motion  # noqa: E402


class _StubDiffDrive:
    """Records configure/begin/start plus the drive-side calls
    `motion.MoveQueue`/`RobotDispatch` might make."""

    def __init__(self):
        self.configure_calls = []
        self.begin_calls = 0
        self.start_calls = 0
        self.drive_calls = []
        self.duty_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0
        self._position = 0.0

    def configure(self, **kwargs):
        self.configure_calls.append(kwargs)
        return "ok"

    def begin(self):
        self.begin_calls += 1
        return "ok"

    def start(self):
        self.start_calls += 1
        return "ok"

    def drive(self, v, twist, lease_ms):
        self.drive_calls.append((v, twist, lease_ms))
        self._position += v
        return "ok"

    def driveDuty(self, duty_left, duty_right, lease_ms):
        self.duty_calls.append((duty_left, duty_right, lease_ms))
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


class _OneShotTransport:
    """Duck-typed Comms Transport (`read_line`/`send`/`send_reliable`)
    that yields ONE pre-scripted line, then `None` forever after --
    proves the pump chain (`PumpTimer.tick()` -> `Comms.pump()`) is
    wired end-to-end from a `BootResult`, via the wire-observable
    `TLM:NOW` forced-emission verb."""

    def __init__(self, line):
        self._line = line

    def read_line(self):
        line, self._line = self._line, None
        return line

    def send(self, data):
        pass

    def send_reliable(self, text):
        pass


def _tick_and_count_emissions(result, line=b"TLM:NOW"):
    """Register a one-shot TLM:NOW transport, tick the pump once, and
    return the resulting `telemetry.emit_count` delta -- the shared
    "pump reaches comms.pump()" proof used below."""
    result.comms.add_transport(_OneShotTransport(line))
    before = result.comms.telemetry.emit_count
    result.pump_timer.tick()
    return result.comms.telemetry.emit_count - before


# --- happy path ----------------------------------------------------------

def test_happy_path_configures_diffdrive_and_boots_comms(tmp_path):
    stub = _StubDiffDrive()
    result = boot.run(
        config_path=str(DATA_DIR / "tovez.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=stub,
    )

    assert result.config_error is None
    assert result.robot_config is not None
    assert result.config_ok() is True

    # diffdrive configured, not begun/started -- first motion consumer does.
    assert stub.begin_calls == 0
    assert stub.start_calls == 0
    assert len(stub.configure_calls) == 1
    kwargs = stub.configure_calls[0]
    assert kwargs["left_port"] == 2
    assert kwargs["right_port"] == 1
    assert result.diffdrive_ready is True

    # dispatch wired to the real motion/config composition, not NullDispatch.
    assert isinstance(result.dispatch, motion.RobotDispatch)

    # comms + radio transport up.
    assert result.comms is not None
    assert result.radio_link is not None
    assert result.comms.transport_count() == 1  # radio only -- no secrets

    # pump started: a tick reaches comms.pump(), proven via a
    # wire-observable TLM:NOW forced emission.
    assert result.pump_timer is not None
    assert _tick_and_count_emissions(result) == 1

    # banner/READY already emitted during run() -- a fresh transport
    # registered after boot gets the exact banner text back.
    assert result.comms._banner.startswith("DEVICE:NEZHA2:robot:tovez:")
    assert result.comms._id_line.startswith("ID:nezha:tovez:")


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
    assert stub.begin_calls == 0
    assert stub.start_calls == 0
    assert result.diffdrive_ready is False

    # motion refused: no RobotDispatch wired (NullDispatch stays default).
    assert result.dispatch is None

    # comms/REPL still available -- banner/READY still emit even with
    # config failed.
    assert result.comms is not None
    assert result.comms._banner.startswith("DEVICE:NEZHA2:robot:unconfigured:")
    assert result.radio_link is not None
    assert result.comms.transport_count() == 1

    # the pump still runs -- comms stays serviceable even in the
    # fail-closed case.
    assert _tick_and_count_emissions(result) == 1


def test_fail_closed_path_missing_file(tmp_path):
    result = boot.run(
        config_path=_missing_path(tmp_path, "no_such_robot.json"),
        secrets_path=_missing_path(tmp_path),
        diffdrive_module=_StubDiffDrive(),
    )
    assert result.robot_config is None
    assert result.diffdrive_ready is False
    assert result.comms is not None  # still boots comms/banner/READY


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
    assert stub.begin_calls == 0
    assert stub.start_calls == 0
    assert isinstance(result.dispatch, motion.RobotDispatch)
    assert _tick_and_count_emissions(result) == 1


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
