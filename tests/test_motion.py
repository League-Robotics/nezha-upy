"""M5 gate: `src/motion.py`'s queue/stop-condition/timeout-fault/replace
logic against a stub diffdrive backend, with an explicit regression
assertion that durations are treated as milliseconds, not seconds. See
`clasi/sprints/001-python-first-firmware-image-m0-m6/tickets/
007-python-firmware-layer-config-telemetry-motion-otos-line-m5.md`."""

import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import motion  # noqa: E402


class _StubDiffDrive:
    """Records every call; `output()` reports a simple integrating
    position model so `stop_distance_mm` is exercisable (encoder
    counts advance by `drive()`'s own `v` on every `drive()` call, one
    "cycle" per call -- exact units don't matter, only that position
    advances monotonically with commanded speed)."""

    def __init__(self):
        self.drive_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0
        self.duty_calls = []
        self._position = 0.0

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


# --- Move validation -----------------------------------------------

def test_move_rejects_zero_duration():
    with pytest.raises(motion.MoveQueueError):
        motion.Move(v=1.0, twist=0.0, duration_ms=0)


def test_move_rejects_duration_over_ceiling():
    with pytest.raises(motion.MoveQueueError):
        motion.Move(v=1.0, twist=0.0, duration_ms=motion.MAX_MOVE_DURATION_MS + 1)


# --- Queue depth / overflow ------------------------------------------

def test_enqueue_up_to_max_depth_then_refuses():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    for _ in range(motion.MAX_QUEUE_DEPTH):
        assert queue.enqueue(motion.Move(v=1.0, duration_ms=100)) is True
    assert queue.depth() == motion.MAX_QUEUE_DEPTH
    assert queue.enqueue(motion.Move(v=1.0, duration_ms=100)) is False
    assert queue.depth() == motion.MAX_QUEUE_DEPTH  # unchanged on refusal


# --- Replace semantics -------------------------------------------------

def test_replace_clears_pending_queue():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    assert queue.depth() == 2

    replacement = motion.Move(v=9.0, duration_ms=50)
    assert queue.enqueue(replacement, queue_mode=motion.QUEUE_MODE_REPLACE) is True
    assert queue.depth() == 1
    assert queue._queue[0] is replacement


def test_replace_stops_in_progress_move():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=1000))
    queue.tick(now_ms=0)
    assert queue.is_running() is True

    queue.enqueue(motion.Move(v=5.0, duration_ms=200), queue_mode=motion.QUEUE_MODE_REPLACE)
    assert queue.is_running() is False  # the old in-progress move was cleared
    queue.tick(now_ms=1)
    assert queue.is_running() is True
    # the NEW move is now driving, not the old one
    assert diffdrive.drive_calls[-1][0] == 5.0


# --- Normal duration-based completion ----------------------------------

def test_move_completes_at_duration_and_advances_queue():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.enqueue(motion.Move(v=2.0, duration_ms=100))

    queue.tick(now_ms=0)
    assert queue.is_running() is True
    assert diffdrive.drive_calls[-1][0] == 1.0

    queue.tick(now_ms=100)  # elapsed == duration_ms -> completes
    assert queue.is_running() is False
    assert queue.depth() == 1

    queue.tick(now_ms=101)  # picks up the next move
    assert queue.is_running() is True
    assert diffdrive.drive_calls[-1][0] == 2.0
    assert queue.fault is False


# --- Stop condition: early stop_distance_mm -----------------------------

def test_stop_distance_completes_move_early():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=10.0, duration_ms=10000, stop_distance_mm=25.0))

    # Each tick() checks the distance travelled BY THE END OF THE PRIOR
    # tick (a realistic "read sensor, decide, then drive" order) before
    # issuing this cycle's own drive() call.
    queue.tick(now_ms=0)  # distance so far: 0 -> drives, position -> 10
    assert queue.is_running() is True
    queue.tick(now_ms=100)  # distance so far: 10 -> drives, position -> 20
    assert queue.is_running() is True
    queue.tick(now_ms=200)  # distance so far: 20 -> drives, position -> 30
    assert queue.is_running() is True
    queue.tick(now_ms=300)  # distance so far: 30 >= 25 -> completes early, no drive
    assert queue.is_running() is False
    assert queue.fault is False
    assert len(diffdrive.drive_calls) == 3  # not a 4th drive on the completing tick


# --- Timeout fault -------------------------------------------------------

def test_timeout_fault_when_far_past_duration_plus_grace():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    assert queue.is_running() is True

    # now_ms jumps far past duration_ms + TIMEOUT_GRACE_MS without any
    # intervening tick() calls -- e.g. the pump stalled.
    queue.tick(now_ms=100 + motion.TIMEOUT_GRACE_MS + 1)
    assert queue.fault is True
    assert queue.fault_reason == "timeout"
    assert diffdrive.neutral_calls == 1
    assert queue.depth() == 0
    assert queue.is_running() is False


def test_tick_within_grace_window_completes_normally_not_faulted():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    queue.tick(now_ms=100 + motion.TIMEOUT_GRACE_MS)  # exactly at the edge -- not a fault
    assert queue.fault is False
    assert queue.is_running() is False


def test_faulted_queue_refuses_new_enqueues_until_cleared():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    queue.tick(now_ms=100 + motion.TIMEOUT_GRACE_MS + 1)
    assert queue.fault is True

    assert queue.enqueue(motion.Move(v=1.0, duration_ms=100)) is False
    queue.clear_fault()
    assert queue.fault is False
    assert queue.enqueue(motion.Move(v=1.0, duration_ms=100)) is True


# --- stop() / estop() ----------------------------------------------------

def test_stop_clears_queue_and_commands_neutral():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)

    queue.stop()
    assert queue.depth() == 0
    assert queue.is_running() is False
    assert diffdrive.neutral_calls == 1


def test_estop_clears_queue_and_commands_estop():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)

    queue.estop()
    assert queue.depth() == 0
    assert diffdrive.estop_calls == 1


# --- Lease renewal stays under the native 5000 ms ceiling ---------------

def test_lease_renewal_never_exceeds_default_lease_ms():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=10000))  # longer than one lease
    queue.tick(now_ms=0)
    assert diffdrive.drive_calls[-1][2] <= motion.DEFAULT_LEASE_MS
    assert diffdrive.drive_calls[-1][2] <= 5000  # native binding ceiling


def test_lease_shrinks_to_remaining_duration_near_the_end():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=1500))
    queue.tick(now_ms=0)  # lease = min(1500, 1000) = 1000
    assert diffdrive.drive_calls[-1][2] == 1000
    queue.tick(now_ms=1000)  # remaining = 500 < 1000
    assert diffdrive.drive_calls[-1][2] == 500


# --- Explicit ms-not-seconds regression --------------------------------

def test_duration_is_milliseconds_not_seconds_regression():
    """PLAN.md landmine ledger L4: a sec/ms slip once ran wheels 8+
    minutes. A move commanded for 100 ms must be DONE well before
    100 real seconds pass -- if `duration_ms` were being treated as
    seconds, the move would still be running at now_ms=101."""
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    assert queue.is_running() is True

    queue.tick(now_ms=101)  # 101 ms elapsed, NOT 101 seconds
    assert queue.is_running() is False, (
        "a 100 ms move is still running 101 ms later -- duration_ms is "
        "being treated as seconds, not milliseconds"
    )


def test_100ms_move_would_still_be_running_if_misread_as_seconds():
    """Companion assertion: if duration_ms were (incorrectly) seconds,
    a 100-unit move would need 100_000 ms to complete -- confirm this
    module does NOT wait that long."""
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    queue.tick(now_ms=200)  # far short of 100_000
    assert queue.is_running() is False
    assert queue.fault is False


# --- GO_TO decomposition -------------------------------------------------

def test_go_to_enqueues_turn_then_drive_legs():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    ok = queue.go_to(target_x=100.0, target_y=0.0, current_pose=(0.0, 0.0, 0.0),
                      speed=50.0, omega=1.0)
    assert ok is True
    assert queue.depth() == 2
    turn_move, drive_move = queue._queue
    # facing along +x already (heading 0), target is straight ahead ->
    # turn leg should be ~zero-duration (minimum 1 ms floor).
    assert turn_move.duration_ms == 1
    assert drive_move.v == 50.0
    assert drive_move.stop_distance_mm == pytest.approx(100.0)


def test_go_to_already_at_target_queues_nothing():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    ok = queue.go_to(target_x=0.0, target_y=0.0, current_pose=(0.0, 0.0, 0.0),
                      speed=50.0, omega=1.0)
    assert ok is True
    assert queue.depth() == 0


def test_go_to_refused_while_faulted():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=1.0, duration_ms=100))
    queue.tick(now_ms=0)
    queue.tick(now_ms=100 + motion.TIMEOUT_GRACE_MS + 1)
    assert queue.fault is True

    ok = queue.go_to(target_x=100.0, target_y=0.0, current_pose=(0.0, 0.0, 0.0),
                      speed=50.0, omega=1.0)
    assert ok is False


# --- RobotDispatch: MOVE / WHEELS / STOP / ESTOP / GO_TO / CALIBRATE ---

def _pack_move(corr_id, queue_mode, v, twist, duration_ms, stop_distance_mm=None):
    has_stop = 1 if stop_distance_mm is not None else 0
    return (
        bytes([corr_id, queue_mode])
        + struct.pack("<f", v)
        + struct.pack("<f", twist)
        + struct.pack("<I", duration_ms)
        + bytes([has_stop])
        + struct.pack("<f", stop_distance_mm or 0.0)
    )


class _FakeConfigDispatch:
    def __init__(self):
        self.calls = []

    def handle_command(self, verb_name, payload, now):
        self.calls.append((verb_name, payload, now))
        return (payload[0] if payload else None, 0)


def _make_dispatch():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    config_dispatch = _FakeConfigDispatch()
    dispatch = motion.RobotDispatch(config_dispatch, queue)
    return dispatch, diffdrive, queue, config_dispatch


def test_dispatch_routes_config_family_to_config_dispatch():
    dispatch, diffdrive, queue, config_dispatch = _make_dispatch()
    result = dispatch.handle_command("SET_FIELD", bytes([5]), 1000)
    assert result == (5, 0)
    assert config_dispatch.calls == [("SET_FIELD", bytes([5]), 1000)]


def test_dispatch_move_enqueues():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    payload = _pack_move(3, motion.QUEUE_MODE_APPEND, 1.0, 0.0, 500)
    result = dispatch.handle_command("MOVE", payload, 1000)
    assert result == (3, motion.ERR_OK)
    assert queue.depth() == 1


def test_dispatch_move_rejects_duration_too_long():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    payload = _pack_move(3, motion.QUEUE_MODE_APPEND, 1.0, 0.0,
                          motion.MAX_MOVE_DURATION_MS + 1)
    result = dispatch.handle_command("MOVE", payload, 1000)
    assert result == (3, motion.ERR_DURATION_TOO_LONG)
    assert queue.depth() == 0


def test_dispatch_move_malformed_length():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    result = dispatch.handle_command("MOVE", bytes([1, 2, 3]), 1000)
    assert result == (1, motion.ERR_MALFORMED)


def test_dispatch_wheels_calls_drive_duty_and_clears_queue():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    queue.enqueue(motion.Move(v=1.0, duration_ms=1000))
    payload = bytes([4]) + struct.pack("<f", 0.5) + struct.pack("<f", -0.5) + struct.pack("<I", 1000)
    result = dispatch.handle_command("WHEELS", payload, 1000)
    assert result == (4, motion.ERR_OK)
    assert diffdrive.duty_calls == [(0.5, -0.5, 1000)]
    assert queue.depth() == 0


def test_dispatch_stop():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    queue.enqueue(motion.Move(v=1.0, duration_ms=1000))
    result = dispatch.handle_command("STOP", bytes([6]), 1000)
    assert result == (6, motion.ERR_OK)
    assert diffdrive.neutral_calls == 1
    assert queue.depth() == 0


def test_dispatch_estop():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    result = dispatch.handle_command("ESTOP", bytes([7]), 1000)
    assert result == (7, motion.ERR_OK)
    assert diffdrive.estop_calls == 1


def test_dispatch_go_to_with_pose_provider():
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    config_dispatch = _FakeConfigDispatch()
    dispatch = motion.RobotDispatch(config_dispatch, queue, pose_provider=lambda: (0.0, 0.0, 0.0))
    payload = (
        bytes([8]) + struct.pack("<f", 100.0) + struct.pack("<f", 0.0)
        + struct.pack("<f", 50.0) + struct.pack("<f", 1.0)
    )
    result = dispatch.handle_command("GO_TO", payload, 1000)
    assert result == (8, motion.ERR_OK)
    assert queue.depth() == 2


def test_dispatch_go_to_without_pose_provider_acks_malformed():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    payload = (
        bytes([8]) + struct.pack("<f", 100.0) + struct.pack("<f", 0.0)
        + struct.pack("<f", 50.0) + struct.pack("<f", 1.0)
    )
    result = dispatch.handle_command("GO_TO", payload, 1000)
    assert result == (8, motion.ERR_MALFORMED)


def test_dispatch_unknown_verb_returns_none():
    dispatch, diffdrive, queue, _ = _make_dispatch()
    assert dispatch.handle_command("VER", b"", 1000) is None
