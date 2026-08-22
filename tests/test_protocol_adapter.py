"""Sprint 007 ticket 005 gate: `src/hardware/protocol_adapter.py`'s
`ProtocolAdapter` -- the real v6 Adapter (protocol.md Sec 4/5/7) bridging
`core/protocol.py`'s handler seam onto `hardware/motion.MoveQueue` and
`core/config.ConfigDispatch`.

Offline-tested against a fake diffdrive (mirrors `tests/test_motion.py`'s
own `_StubDiffDrive` convention) wrapped in a REAL `motion.MoveQueue`, and
a REAL `config.ConfigDispatch` built from a small literal `wheel_control`
dict (mirrors `tests/test_config.py`'s own `_make_dispatch()` fixture
convention) -- this exercises the new `get_field()`/`set_field()`
accessors end to end, not a third mock standing in for them.

Covers every method the ticket names: `identity`/`now`/`status`/
`on_wheels`/`on_stop`/`on_estop`/`on_get`/`on_set`/`field_count`/
`field_name`/`on_tlm`, the velocity/twist geometry scaling, the
wheel-swap sign test (protocol.md Sec 5 point 3's "single most repeated
bug" -- swapping which argument is "left" must flip the test), the
5000 ms WHEELS ceiling enforced ABOVE the kernel call, and TLM-mode
persistence shared across two `ProtocolHandler` instances (sprint.md's
"one robot, not one per transport" design rationale).
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import config  # noqa: E402
from core import protocol  # noqa: E402
from hardware import motion  # noqa: E402
from hardware import protocol_adapter  # noqa: E402


# --- fakes -----------------------------------------------------------------

class _FakeDiffDrive:
    """Records every call; `output()` reports a settable dict of the
    same keys `native/moddiffdrive.cpp`'s real `output()` binding
    produces (ready/estopped/leaseExpired/stallHalted/connectedLeft/
    connectedRight/velocity/twist) -- defaults reflect an idle,
    un-configured kernel (everything False/0.0). `drive()`'s return
    value is settable per test (`drive_return`) so the status-string ->
    Result mapping can be exercised without a real kernel."""

    def __init__(self):
        self.drive_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0
        self.drive_return = "ok"
        self.out = {
            "ready": False,
            "estopped": False,
            "leaseExpired": False,
            "stallHalted": False,
            "connectedLeft": False,
            "connectedRight": False,
            "velocity": 0.0,
            "twist": 0.0,
        }

    def drive(self, velocity, twist, lease_ms):
        self.drive_calls.append((velocity, twist, lease_ms))
        return self.drive_return

    def neutral(self):
        self.neutral_calls += 1

    def estop(self):
        self.estop_calls += 1

    def output(self):
        return dict(self.out)


def _make_config_dispatch(**wheel_control_overrides):
    wheel_control = {}
    for json_field, _kernel_field in config.WHEEL_CONTROL_FIELDS:
        wheel_control[json_field] = 0.0
    wheel_control.update(wheel_control_overrides)
    return config.ConfigDispatch({"wheel_control": wheel_control})


def _make_adapter(diffdrive=None, config_dispatch=None, counts_per_length=1.0,
                   name="testbot", serial="SN001", drivetrain="differential",
                   profile="tovez", version="6.0.0", now_fn=None):
    diffdrive = diffdrive if diffdrive is not None else _FakeDiffDrive()
    move_queue = motion.MoveQueue(diffdrive)
    config_dispatch = (config_dispatch if config_dispatch is not None
                        else _make_config_dispatch())
    adapter = protocol_adapter.ProtocolAdapter(
        move_queue, config_dispatch, counts_per_length,
        name, serial, drivetrain, profile, version, now_fn=now_fn)
    return adapter, move_queue, diffdrive


class _RecordingSink(protocol.Sink):
    def __init__(self):
        self.written = ""

    def write(self, text):
        self.written += text


# --- identity / now ----------------------------------------------------

def test_identity_returns_constructor_scalars():
    adapter, _queue, _diffdrive = _make_adapter(
        name="tovez", serial="ABC123", drivetrain="differential",
        profile="tovez", version="6.0.0")
    assert adapter.identity() == ("tovez", "ABC123", "differential",
                                   "tovez", "6.0.0")


def test_now_delegates_to_injected_now_fn():
    calls = []

    def fake_now():
        calls.append(1)
        return 12345

    adapter, _queue, _diffdrive = _make_adapter(now_fn=fake_now)
    assert adapter.now() == 12345
    assert calls == [1]


def test_now_has_a_working_default_when_not_injected():
    adapter, _queue, _diffdrive = _make_adapter()
    value = adapter.now()
    assert isinstance(value, int)
    assert value >= 0


# --- status --------------------------------------------------------------

def test_status_projects_diffdrive_output_when_idle():
    adapter, _queue, _diffdrive = _make_adapter()
    ready, active, conn_left, conn_right, otos, wedge, flags, tlm = adapter.status()
    assert ready is False
    assert active is False
    assert conn_left is False
    assert conn_right is False
    assert otos is False  # no OTOS wired this sprint -- placeholder
    assert wedge is False  # no line sensor wired this sprint -- placeholder
    assert flags == 0
    assert tlm == "off"


def test_status_reports_ready_active_and_connected_while_driving():
    diffdrive = _FakeDiffDrive()
    diffdrive.out.update({
        "ready": True,
        "connectedLeft": True,
        "connectedRight": True,
        "velocity": 10.0,
    })
    adapter, _queue, _diffdrive = _make_adapter(diffdrive=diffdrive)
    ready, active, conn_left, conn_right, _otos, _wedge, flags, _tlm = adapter.status()
    assert ready is True
    assert active is True
    assert conn_left is True
    assert conn_right is True
    assert flags != 0


def test_status_active_is_false_while_estopped_even_if_ready():
    diffdrive = _FakeDiffDrive()
    diffdrive.out.update({"ready": True, "estopped": True, "velocity": 10.0})
    adapter, _queue, _diffdrive = _make_adapter(diffdrive=diffdrive)
    ready, active, _cl, _cr, _o, _w, _flags, _tlm = adapter.status()
    assert ready is True
    assert active is False


def test_status_tlm_reflects_persisted_mode_lowercased():
    adapter, _queue, _diffdrive = _make_adapter()
    adapter.on_tlm("FULL")
    _r, _a, _cl, _cr, _o, _w, _f, tlm = adapter.status()
    assert tlm == "full"


# --- on_wheels: geometry scaling + wheel-swap sign test -----------------

def test_on_wheels_scales_by_counts_per_length_and_splits_velocity_twist():
    adapter, _queue, diffdrive = _make_adapter(counts_per_length=2.0)
    result = adapter.on_wheels(left=100.0, right=200.0, duration=500.0,
                                reply_id=1)
    assert result == protocol.Result.OK
    assert len(diffdrive.drive_calls) == 1
    velocity, twist, lease_ms = diffdrive.drive_calls[0]
    # counts_left = 100*2 = 200, counts_right = 200*2 = 400
    # velocity = (200+400)/2 = 300, twist = (400-200)/2 = 100
    assert velocity == pytest.approx(300.0)
    assert twist == pytest.approx(100.0)
    assert lease_ms == 500


def test_on_wheels_never_passes_raw_duty_values_to_drive():
    """Regression pin: v5's WHEELS called driveDuty() with the raw
    left/right fields untouched. v6 must scale through countsPerLength
    first -- with a non-unity factor, the values reaching drive() must
    differ from the raw wire fields."""
    adapter, _queue, diffdrive = _make_adapter(counts_per_length=3.5)
    adapter.on_wheels(left=10.0, right=10.0, duration=100.0, reply_id=0)
    velocity, twist, _lease = diffdrive.drive_calls[0]
    assert velocity == pytest.approx(35.0)  # not the raw 10.0
    assert twist == pytest.approx(0.0)


def test_on_wheels_twist_is_ccw_positive_for_a_faster_right_wheel():
    """protocol.md Sec 5 point 3: twist = (right - left) / 2, CCW-positive
    -- a faster RIGHT wheel must yield a POSITIVE twist. This is the
    exact sign the spec calls out as "the single most repeated bug in
    this project's history": if on_wheels() ever swapped which argument
    is treated as "left" when computing counts_left/counts_right, this
    assertion's sign would flip and the test would fail."""
    adapter, _queue, diffdrive = _make_adapter(counts_per_length=1.0)
    adapter.on_wheels(left=50.0, right=150.0, duration=500.0, reply_id=1)
    _velocity, twist, _lease = diffdrive.drive_calls[-1]
    assert twist == pytest.approx(50.0)
    assert twist > 0.0


def test_on_wheels_twist_sign_flips_if_left_and_right_are_exchanged():
    """Companion to the test above, phrased as the ticket's own
    wheel-swap convention: calling on_wheels() with left/right EXCHANGED
    must produce the exactly negated twist -- proof that the two
    arguments are not treated symmetrically (a bug that swapped them
    internally would make this fail by producing the SAME twist both
    times instead of its negation)."""
    adapter_a, _qa, diffdrive_a = _make_adapter(counts_per_length=1.0)
    adapter_a.on_wheels(left=50.0, right=150.0, duration=500.0, reply_id=1)
    _va, twist_a, _la = diffdrive_a.drive_calls[-1]

    adapter_b, _qb, diffdrive_b = _make_adapter(counts_per_length=1.0)
    adapter_b.on_wheels(left=150.0, right=50.0, duration=500.0, reply_id=1)
    _vb, twist_b, _lb = diffdrive_b.drive_calls[-1]

    assert twist_a == pytest.approx(50.0)
    assert twist_b == pytest.approx(-50.0)
    assert twist_a == pytest.approx(-twist_b)


# --- on_wheels: 5000 ms ceiling, enforced by the adapter -----------------

def test_on_wheels_rejects_duration_over_5000ms_ceiling_without_calling_drive():
    adapter, _queue, diffdrive = _make_adapter()
    result = adapter.on_wheels(left=10.0, right=10.0, duration=5001.0,
                                reply_id=3)
    assert result == protocol.Result.RANGE
    assert diffdrive.drive_calls == []  # rejected above the kernel call


def test_on_wheels_accepts_duration_exactly_at_5000ms_ceiling():
    adapter, _queue, diffdrive = _make_adapter()
    result = adapter.on_wheels(left=10.0, right=10.0, duration=5000.0,
                                reply_id=3)
    assert result == protocol.Result.OK
    assert len(diffdrive.drive_calls) == 1


def test_on_wheels_maps_refused_status_strings_to_result_codes():
    diffdrive = _FakeDiffDrive()
    diffdrive.drive_return = "refused_estopped"
    adapter, _queue, _diffdrive = _make_adapter(diffdrive=diffdrive)
    result = adapter.on_wheels(left=1.0, right=1.0, duration=100.0,
                                reply_id=1)
    assert result == protocol.Result.NOT_CONFIGURED


def test_on_wheels_maps_unrecognized_status_string_to_unknown():
    diffdrive = _FakeDiffDrive()
    diffdrive.drive_return = "something_a_future_kernel_might_say"
    adapter, _queue, _diffdrive = _make_adapter(diffdrive=diffdrive)
    result = adapter.on_wheels(left=1.0, right=1.0, duration=100.0,
                                reply_id=1)
    assert result == protocol.Result.UNKNOWN


# --- on_stop / on_estop ---------------------------------------------------

def test_on_stop_calls_diffdrive_neutral_directly_and_always_acks_ok():
    adapter, _queue, diffdrive = _make_adapter()
    result = adapter.on_stop(7)
    assert result == protocol.Result.OK
    assert diffdrive.neutral_calls == 1


def test_on_estop_calls_move_queue_estop_and_returns_none():
    adapter, queue, diffdrive = _make_adapter()
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    result = adapter.on_estop()
    assert result is None
    assert diffdrive.estop_calls == 1
    assert queue.depth() == 0  # MoveQueue.estop() clears the pending queue too


# --- on_get / on_set / field_count / field_name --------------------------

def test_on_get_known_name_returns_live_value():
    dispatch = _make_config_dispatch(v_min=42.0)
    adapter, _queue, _diffdrive = _make_adapter(config_dispatch=dispatch)
    assert adapter.on_get("v_min") == pytest.approx(42.0)


def test_on_get_unknown_name_returns_none_silently():
    adapter, _queue, _diffdrive = _make_adapter()
    assert adapter.on_get("not_a_real_field") is None


def test_on_set_known_name_applies_live_and_returns_ok():
    adapter, _queue, _diffdrive = _make_adapter()
    result = adapter.on_set("pid_kp", 0.002, 5)
    assert result == protocol.Result.OK
    assert adapter.on_get("pid_kp") == pytest.approx(0.002)


def test_on_set_unknown_name_returns_unknown_result():
    adapter, _queue, _diffdrive = _make_adapter()
    result = adapter.on_set("not_a_real_field", 1.0, 5)
    assert result == protocol.Result.UNKNOWN


def test_field_count_and_field_name_match_wheel_control_fields_order():
    adapter, _queue, _diffdrive = _make_adapter()
    expected_names = [json_field for json_field, _kernel_field
                      in config.WHEEL_CONTROL_FIELDS]
    assert adapter.field_count() == len(expected_names)
    actual_names = [adapter.field_name(i) for i in range(adapter.field_count())]
    assert actual_names == expected_names


# --- on_tlm: persisted, shared across handler instances ------------------

def test_on_tlm_persists_mode_on_the_adapter():
    adapter, _queue, _diffdrive = _make_adapter()
    result = adapter.on_tlm("POSE")
    assert result == protocol.Result.OK
    _r, _a, _cl, _cr, _o, _w, _f, tlm = adapter.status()
    assert tlm == "pose"


def test_tlm_mode_is_shared_across_two_protocol_handler_instances():
    """sprint.md's Design Rationale: one ProtocolAdapter shared across
    every registered transport's own ProtocolHandler -- TLM is one
    robot-wide subscription, not one per channel. A TLM sent through
    handler #1's line grammar must be visible in handler #2's STATUS
    reply, because both handlers wrap the SAME adapter instance."""
    adapter, _queue, _diffdrive = _make_adapter()
    sink1 = _RecordingSink()
    sink2 = _RecordingSink()
    handler1 = protocol.ProtocolHandler(adapter, sink1)
    handler2 = protocol.ProtocolHandler(adapter, sink2)

    handler1.feed(b"TLM FULL\n")
    assert sink1.written == ""  # TLM carries no id, no reply either way

    handler2.feed(b"STATUS\n")
    assert "tlm=full" in sink2.written
