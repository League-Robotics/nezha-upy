"""M5 gate: `src/hardware/motion.py`'s queue/stop-condition/timeout-fault/replace
logic against a stub diffdrive backend, with an explicit regression
assertion that durations are treated as milliseconds, not seconds."""

import struct
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hardware import motion  # noqa: E402


class _StubDiffDrive:
    """Records every call; `output()` reports a simple integrating
    position model (position advances by `drive()`'s `v` each call) so
    `stop_distance_mm` is exercisable. `step()`/`cyclePeriod()` extend
    this same stub for the generator-mode tests below (ticket 007) --
    unused by, and harmless to, the MoveQueue/RobotDispatch tests above."""

    def __init__(self, cycle_period_ms=24):
        self.drive_calls = []
        self.neutral_calls = 0
        self.estop_calls = 0
        self.duty_calls = []
        self.step_calls = 0
        self._cycle_period_ms = cycle_period_ms
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

    def step(self):
        self.step_calls += 1

    def cyclePeriod(self):
        return self._cycle_period_ms


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

    # Each tick() checks distance travelled as of the PRIOR tick
    # (read-sensor-then-drive order) before issuing this cycle's drive().
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

    # now_ms jumps far past duration_ms + TIMEOUT_GRACE_MS with no
    # intervening tick() -- e.g. the pump stalled.
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
    minutes. A move commanded for 100 ms must be DONE well before 100
    real seconds pass."""
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
    """Companion: if duration_ms were (incorrectly) seconds, a 100-unit
    move would need 100_000 ms -- confirm this does NOT wait that long."""
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
    # facing +x already, target straight ahead -> turn leg is
    # ~zero-duration (1 ms floor).
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


# --- Generator-driven move mode (ticket 007, SUC-001/SUC-002) ----------
# Offline against the same _StubDiffDrive (step()/cyclePeriod()-extended
# above), driven by a fake, GC-independent ms clock -- no real sleeping.

class _FakeClock:
    """`sleep()` advances the counter instead of blocking, so pacing
    tests run instantly and deterministically. No ticks-wraparound
    handling needed at these magnitudes -- motion.py's own CPython
    fallback for `_ticks_add`/`_ticks_diff` is plain +/-."""

    def __init__(self, start_ms=0):
        self.ms = start_ms
        self.sleep_calls = []

    def now(self):
        return self.ms

    def sleep(self, wait_ms):
        self.sleep_calls.append(wait_ms)
        self.ms += wait_ms


def test_generator_each_next_runs_exactly_one_kernel_step():
    diffdrive = _StubDiffDrive()
    clock = _FakeClock()
    gen = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    for expected in range(1, 4):
        next(gen)
        assert diffdrive.step_calls == expected
    gen.stop()


def test_generator_pacing_uses_absolute_deadlines_not_drifting_sleep():
    """Absolute-deadline pacing (mirroring the vendored kernel's own
    run()) self-corrects for a slow cycle instead of drifting: make
    step() cost 10ms (matching moddiffdrive.cpp's ~9-10ms real settle
    cost) and confirm the NEXT wait shrinks to period-cost, not the
    full period -- proof the deadline is `previous_cycle + period`, not
    `now() + period`."""
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    step_cost_ms = 10
    real_step = diffdrive.step

    def step_with_cost():
        real_step()
        clock.ms += step_cost_ms

    diffdrive.step = step_with_cost

    gen = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    next(gen)  # cycle 1: cycle == now at start, no wait yet
    assert clock.sleep_calls == []
    next(gen)  # cycle 2: wait = period - step_cost, not the full period
    assert clock.sleep_calls == [24 - step_cost_ms]
    gen.stop()


def test_generator_lease_renewed_each_cycle_is_short():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    gen = motion.drive(diffdrive, v=2.0, twist=0.5, duration_ms=1000,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    for _ in range(3):
        next(gen)
    expected_lease = 24 * motion.GEN_LEASE_PERIODS
    assert diffdrive.drive_calls == [(2.0, 0.5, expected_lease)] * 3
    gen.stop()


def test_generator_finally_lands_neutral_on_normal_completion():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    gen = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=72,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    yields = 0
    with pytest.raises(StopIteration):
        while True:
            next(gen)
            yields += 1
    assert yields == 4
    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 5  # 4 driving cycles + 1 landing step in finally


# --- MoveHandle: stop()/with are the CONTRACT; bare break is not (ticket 012) --
#
# Measured on hardware (ticket 009): a bare `break` out of `for state in
# motion.drive(...):` does NOT run the generator's `finally` on
# MicroPython -- mark-and-sweep GC does not promptly close a suspended
# generator the way CPython's refcounting does, so `GeneratorExit` never
# fires. The tests below exercise the DOCUMENTED paths (`stop()`, `with`)
# directly, by explicit call -- not by letting a generator/handle go out
# of scope and hoping a runtime finalizes it promptly. That distinction
# is what makes these tests portable: they prove `MoveHandle.stop()`'s
# own logic, which no longer depends on when-or-whether a runtime
# finalizes a generator. CPython finalization TIMING is NOT proof of
# MicroPython behaviour -- only explicit-call tests (this file) are
# portable; finalization-timing claims are hardware-only proof (ticket
# 009's re-run), not something an offline CPython test can establish.

def test_drive_gen_finally_lands_neutral_on_generator_close():
    """Mechanism-only, not the contract: proves the raw generator's
    `finally` lands neutral()+step() when explicitly closed. Exercises
    `_drive_gen` directly (bypassing `MoveHandle`) -- this is the exact
    mechanism `MoveHandle.stop()` relies on and hardware already proved
    correct (ticket 009's `gen.close()` bench run); it is NOT proof that
    a bare `break` triggers it -- see
    test_bare_break_without_stop_leaves_duty_commanded below."""
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    gen = motion._drive_gen(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                             ticks_ms=clock.now, sleep_ms=clock.sleep)
    next(gen)
    next(gen)
    assert diffdrive.step_calls == 2
    assert diffdrive.neutral_calls == 0

    gen.close()

    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 3  # 2 driving cycles + 1 landing step


def test_movehandle_stop_lands_neutral():
    """The documented explicit-stop idiom: `move.stop()`, not
    `gen.close()`, not a bare `break`."""
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    move = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                         ticks_ms=clock.now, sleep_ms=clock.sleep)
    next(move)
    next(move)
    assert diffdrive.step_calls == 2
    assert diffdrive.neutral_calls == 0

    move.stop()

    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 3  # 2 driving cycles + 1 landing step


def test_movehandle_stop_twice_is_idempotent():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    move = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                         ticks_ms=clock.now, sleep_ms=clock.sleep)
    next(move)
    move.stop()
    move.stop()  # must not raise, must not re-run finally
    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 2  # 1 driving cycle + 1 landing step


def test_movehandle_stop_after_natural_completion_is_a_noop():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    move = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=72,
                         ticks_ms=clock.now, sleep_ms=clock.sleep)
    with pytest.raises(StopIteration):
        while True:
            next(move)
    assert diffdrive.neutral_calls == 1  # finally already ran on natural completion

    move.stop()  # must not raise, must not re-run finally

    assert diffdrive.neutral_calls == 1


def test_movehandle_with_stops_on_normal_exit():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    with motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                       ticks_ms=clock.now, sleep_ms=clock.sleep) as move:
        next(move)
        next(move)
    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 3  # 2 driving cycles + 1 landing step


def test_movehandle_with_stops_on_break():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    with motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                       ticks_ms=clock.now, sleep_ms=clock.sleep) as move:
        for _state in move:
            if diffdrive.step_calls >= 2:
                break  # __exit__ still runs -- stop() is not conditional on how we leave
    assert diffdrive.neutral_calls == 1
    assert diffdrive.step_calls == 3  # 2 driving cycles + 1 landing step


def test_movehandle_with_stops_on_exception_and_does_not_suppress_it():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                           ticks_ms=clock.now, sleep_ms=clock.sleep) as move:
            next(move)
            raise _Boom("student code raised inside the with block")

    assert diffdrive.neutral_calls == 1  # __exit__ still stopped the move
    assert diffdrive.step_calls == 2  # 1 driving cycle + 1 landing step


def test_bare_break_without_stop_leaves_duty_commanded():
    """Known, ACCEPTED gap (ticket 012) -- do not "fix" this test to
    assert the opposite. `move` stays referenced by this test function
    across the `break`, so this is not a GC-timing test: it proves that
    breaking out of the loop, by itself, triggers nothing -- no implicit
    close, on any Python. Only `stop()`/`with` (tested above) run
    `finally`. On hardware this residual duty is what the ~250 ms
    starvation watchdog exists to catch -- a FAILSAFE for the
    forgot-to-stop case, not the contract itself."""
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    move = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                         ticks_ms=clock.now, sleep_ms=clock.sleep)
    for _state in move:
        if diffdrive.step_calls >= 2:
            break
    # No stop() called -- finally has NOT run. This is the documented gap.
    assert diffdrive.step_calls == 2
    assert diffdrive.neutral_calls == 0


def test_generator_zero_duration_still_lands_clean_neutral():
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    gen = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=0,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    with pytest.raises(StopIteration):
        next(gen)
    assert diffdrive.drive_calls == []  # no driving cycle ever ran
    assert diffdrive.step_calls == 1  # only the finally's landing step
    assert diffdrive.neutral_calls == 1


def test_generator_rejects_duration_over_ceiling():
    diffdrive = _StubDiffDrive()
    gen = motion.drive(diffdrive, v=1.0, twist=0.0,
                        duration_ms=motion.MAX_MOVE_DURATION_MS + 1)
    with pytest.raises(motion.MoveQueueError):
        next(gen)


def test_generator_abandoned_stops_stepping_with_short_lease_outstanding():
    """Python never auto-advances a generator -- an abandoned one simply
    stops stepping ("wheels move only while you keep iterating"). The
    short (~3x period) lease outstanding on the last drive() is what
    lets the native kernel decay to neutral on its own once it expires
    (hardware-verified in ticket 009); this offline test verifies the
    Python-side precondition that makes that decay possible."""
    diffdrive = _StubDiffDrive(cycle_period_ms=24)
    clock = _FakeClock()
    gen = motion.drive(diffdrive, v=1.0, twist=0.0, duration_ms=1000,
                        ticks_ms=clock.now, sleep_ms=clock.sleep)
    next(gen)
    next(gen)
    steps_after_two_cycles = diffdrive.step_calls
    last_lease = diffdrive.drive_calls[-1][2]
    assert last_lease == diffdrive.cyclePeriod() * motion.GEN_LEASE_PERIODS

    # Abandoned: no further next() calls, ever.
    assert diffdrive.step_calls == steps_after_two_cycles


def test_move_queue_background_mode_unaffected_by_generator_addition():
    """Proves the ticket-007 generator addition changed nothing about
    MoveQueue/RobotDispatch: same _StubDiffDrive (now step()/
    cyclePeriod()-extended, harmlessly), same tick()-driven fiber-mode
    behavior as the pre-existing tests above -- and it never calls the
    new step()/cyclePeriod() surface at all."""
    diffdrive = _StubDiffDrive()
    queue = motion.MoveQueue(diffdrive)
    queue.enqueue(motion.Move(v=3.0, duration_ms=100))

    queue.tick(now_ms=0)
    assert queue.is_running() is True
    assert diffdrive.drive_calls[-1] == (3.0, 0.0, 100)  # lease shrinks to remaining duration
    assert diffdrive.step_calls == 0  # background/fiber mode never calls step()

    queue.tick(now_ms=100)
    assert queue.is_running() is False
