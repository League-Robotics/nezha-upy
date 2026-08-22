"""motion -- move queue, stop conditions, timeout fault, replace
semantics, and GO_TO, spec Sec 6/7.2, UC-013.

Sprint 007 ticket 006 (v6 line-protocol cutover): the CONFIG-family/
motion binary verb dispatch router (``RobotDispatch`` and its
``_handle_move``/``_handle_wheels``/``_handle_stop``/``_handle_estop``/
``_handle_go_to``/``_handle_calibrate`` methods, plus the module-level
``_corr_id_or_none()``/``_unpack_f32_le()`` helpers and ``ERR_*``
reply-code constants that existed only to serve it) is DELETED --
superseded by ``hardware/protocol_adapter.py``'s ``ProtocolAdapter``,
which dispatches v6's text-line ``WHEELS``/``STOP``/``ESTOP`` verbs
straight onto ``MoveQueue``'s underlying ``diffdrive`` (bypassing the
queue for those three, per ``protocol.md`` Sec 5.1 -- see
``protocol_adapter.py``'s own docstring). ``MOVE``/``GO_TO``/
``CALIBRATE`` are out of scope for v6 entirely (sprint.md's own Scope
section) -- a later sprint rebuilds a motion API for them; until then
``MoveQueue.enqueue()``/``go_to()`` remain reachable only from direct
student/REPL code, not from any wire verb.

**Every duration in this module is MILLISECONDS.** A sec/ms slip once
ran wheels 8+ minutes unsupervised -- this is a load-bearing regression
risk, not a style note. See ``MAX_MOVE_DURATION_MS`` and
``tests/test_motion.py``'s explicit ms-vs-seconds regression assertion.

---

**Teaching-framework loop-ownership decision** (spec Sec 7.2 / Sec 10
open item 4):

DECIDED: no ``on_tick()`` callback framework is implemented. This
module exposes plain, direct function calls (``MoveQueue.enqueue()``/
``stop()``/``estop()``/``go_to()``), driven directly from student/REPL
code (v6's wire path reaches ``MoveQueue.diffdrive`` directly through
``hardware/protocol_adapter.py`` for ``WHEELS``/``STOP``/``ESTOP``,
never through this queue -- see this module's own top-of-file note).
The vendored kernel
(``vendor/differential_drive.h``) free-runs its own control cadence on
a CODAL fiber, independent of Python's call stack (spec Sec 5/7.1) --
so "loop ownership" for wheel motion resolves to "the kernel owns
cadence, not Python," regardless of how student code is shaped. What
DOES need periodic pumping is ``MoveQueue.tick()`` (renews leases,
advances the queue, detects timeout faults) -- that pumping is
framework-owned, via ``comms.py``'s scheduled pump (``PumpTimer``/
``micropython.schedule``), the same mechanism that already services
wire commands every cycle.

Student-facing contract: wheel control requires reaching idle
(``microbit_hal_idle()``) for the kernel fiber to be scheduled at all
-- a tight ``while True:`` loop that never reaches idle (including the
realistic polling idiom ``while True: p = radio.receive()``) starves
the kernel fiber. The VM-hook starvation watchdog (``native/
watchdog.h``) is the safety backstop for that case (fault bit surfaced
in ``telemetry.py``'s ``watchdog_fault`` field), not a substitute for
the contract itself.

A second, additive execution mode is implemented below: ``drive()``, a
generator where each ``next()`` runs one ``diffdrive.step()`` cycle
inline, the generator owning pacing. Mutually exclusive with the
background/fiber mode above at the native layer (mode latches on
whichever of ``start()``/``step()`` is called first this boot, ticket
006) -- ``MoveQueue`` above is unchanged either way. See
``clasi/issues/generator-driven-control-loop-mode-addition-not-
replacement.md`` and sprint 006 SUC-001/SUC-002.
"""

import math

__all__ = [
    "MAX_QUEUE_DEPTH",
    "MAX_MOVE_DURATION_MS",
    "DEFAULT_LEASE_MS",
    "TIMEOUT_GRACE_MS",
    "QUEUE_MODE_REPLACE",
    "QUEUE_MODE_APPEND",
    "MoveQueueError",
    "Move",
    "MoveQueue",
    "GEN_LEASE_PERIODS",
    "drive",
    "MoveHandle",
]

MAX_QUEUE_DEPTH = 5

# Policy ceiling on a single queued move's OWN duration_ms -- separate
# from and much larger than the native binding's 5000 ms per-call lease
# ceiling (a queued move renews its lease repeatedly via tick()). This
# is the ms-not-seconds landmine guard: a move is REFUSED at enqueue
# time, never silently clamped, if its duration is not a plausible
# millisecond value. A units-confused caller sending seconds where ms
# is expected gets an almost-instant move, visibly wrong in the
# classroom -- which is why "every duration is ms" is a documented
# CONTRACT, not just a bound.
MAX_MOVE_DURATION_MS = 60000

# Per-tick() lease renewal -- well under the native binding's 5000 ms
# ceiling (native/moddiffdrive.cpp's kBindingLeaseMaxMs) so a queue that
# stops ticking (student loop stalls) decays to neutral quickly via the
# kernel's own lease expiry, without this module needing its own timer.
DEFAULT_LEASE_MS = 1000

# Grace window past a move's own duration_ms before a still-not-complete
# move is treated as a TIMEOUT FAULT rather than ordinary tick() jitter
# -- reuses the VM-hook starvation watchdog's own 250 ms stall threshold
# (native/watchdog.h kStallThresholdUs) rather than inventing a second
# "how long is a real stall" constant.
TIMEOUT_GRACE_MS = 250

QUEUE_MODE_REPLACE = 0
QUEUE_MODE_APPEND = 1


class MoveQueueError(ValueError):
    """Raised by ``Move.__init__`` on an invalid duration -- fail fast
    (never silently clamp), matching the native binding's own lease-
    ceiling precedent."""


class Move:
    """One queued velocity/twist command. ``v``/``twist``:
    [counts/s]/[counts/s] (matches ``diffdrive.drive()``'s own units --
    this module never converts, it passes these straight through).
    ``duration_ms``: int, REQUIRED, ``0 < duration_ms <=
    MAX_MOVE_DURATION_MS``. ``stop_distance_mm``: optional early-stop
    threshold on cumulative |encoder delta| (mean of both wheels) since
    the move started -- ``None`` disables it (duration is the only stop
    condition)."""

    def __init__(self, v=0.0, twist=0.0, duration_ms=0, stop_distance_mm=None):
        if duration_ms <= 0 or duration_ms > MAX_MOVE_DURATION_MS:
            raise MoveQueueError(
                "duration_ms out of range (ms, not seconds): %r" % (duration_ms,)
            )
        self.v = v
        self.twist = twist
        self.duration_ms = duration_ms
        self.stop_distance_mm = stop_distance_mm

    def __repr__(self):
        return "Move(v=%r, twist=%r, duration_ms=%r, stop_distance_mm=%r)" % (
            self.v, self.twist, self.duration_ms, self.stop_distance_mm,
        )


class MoveQueue:
    """The 5-deep move queue over a ``diffdrive``-shaped backend
    (duck-typed: ``drive(v, twist, lease_ms) -> status:str``,
    ``driveDuty(dutyLeft, dutyRight, lease_ms) -> status:str``,
    ``neutral() -> None``, ``estop() -> None``, ``output() -> dict``
    with at least ``positionLeft``/``positionRight`` -- the real
    ``diffdrive`` native module or a stub).

    Call ``tick(now_ms)`` every cycle (from ``comms.py``'s scheduled
    pump, per the loop-ownership decision in the module docstring) to
    advance the queue, renew leases, and detect timeout faults.
    """

    def __init__(self, diffdrive):
        self.diffdrive = diffdrive
        self._diffdrive = diffdrive  # internal alias, kept for brevity below
        self._queue = []
        self._current = None
        self._current_start_ms = None
        self._current_start_position = None
        self.fault = False
        self.fault_reason = None

    def depth(self):
        """Number of PENDING moves (not counting the one in progress)."""
        return len(self._queue)

    def is_running(self):
        return self._current is not None

    def enqueue(self, move, queue_mode=QUEUE_MODE_APPEND):
        """Add ``move`` to the queue. ``queue_mode=QUEUE_MODE_REPLACE``
        clears whatever is pending/in-progress first (replace
        semantics) -- the new move takes over on the NEXT ``tick()``.
        ``queue_mode=QUEUE_MODE_APPEND`` (default) adds to the back of
        the pending queue, refused with ``False`` if already at
        ``MAX_QUEUE_DEPTH``. Refused (``False``, no state change) while
        ``self.fault`` is latched -- ``clear_fault()`` first."""
        if self.fault:
            return False
        if queue_mode == QUEUE_MODE_REPLACE:
            self._queue = []
            self._current = None
        if len(self._queue) >= MAX_QUEUE_DEPTH:
            return False
        self._queue.append(move)
        return True

    def stop(self):
        """Clear the queue and command neutral -- a graceful stop."""
        self._queue = []
        self._current = None
        self._diffdrive.neutral()

    def estop(self):
        """Clear the queue and command a hard estop."""
        self._queue = []
        self._current = None
        self._diffdrive.estop()

    def clear_fault(self):
        self.fault = False
        self.fault_reason = None

    def go_to(self, target_x, target_y, current_pose, speed, omega, queue_mode=QUEUE_MODE_REPLACE):
        """Decompose a point-to-point GO_TO into two queued moves: turn
        to face ``(target_x, target_y)``, then drive straight to it --
        computed ONCE from ``current_pose`` (``(x, y, heading_rad)``) at
        issue time (open-loop within each leg, a simple turn-then-drive
        strategy, not continuously-corrected navigation -- the vendored
        ``DiffDrive`` kernel has no equivalent to radio-robot-elite's
        ``Motion::Navigator``). ``speed``: [counts/s] for the straight
        leg. ``omega``: [counts/s] twist magnitude for the turn leg
        (sign chosen by the computed turn direction). Returns ``True``
        if both legs were queued, ``False`` (no state change) if the
        queue refused (faulted, or already at depth) or the two legs
        would not both fit."""
        if self.fault:
            return False
        x0, y0, heading0 = current_pose
        dx = target_x - x0
        dy = target_y - y0
        distance = (dx * dx + dy * dy) ** 0.5
        if distance <= 0.0:
            return True  # already there -- nothing to queue

        target_heading = _atan2(dy, dx)
        turn = _normalize_angle(target_heading - heading0)

        turn_duration_ms = _duration_for_angle_ms(turn, omega)
        drive_duration_ms = _duration_for_distance_ms(distance, speed)

        turn_move = Move(v=0.0, twist=omega if turn >= 0 else -omega,
                          duration_ms=turn_duration_ms)
        drive_move = Move(v=speed, twist=0.0, duration_ms=drive_duration_ms,
                           stop_distance_mm=distance)

        if not self.enqueue(turn_move, queue_mode=queue_mode):
            return False
        if not self.enqueue(drive_move, queue_mode=QUEUE_MODE_APPEND):
            return False
        return True

    def _distance_travelled(self):
        out = self._diffdrive.output()
        start_left, start_right = self._current_start_position
        delta_left = out.get("positionLeft", 0.0) - start_left
        delta_right = out.get("positionRight", 0.0) - start_right
        return (abs(delta_left) + abs(delta_right)) / 2.0

    def _start_next(self, now_ms):
        self._current = self._queue.pop(0)
        self._current_start_ms = now_ms
        out = self._diffdrive.output()
        self._current_start_position = (
            out.get("positionLeft", 0.0), out.get("positionRight", 0.0),
        )

    def _complete_current(self):
        self._current = None
        self._current_start_ms = None
        self._current_start_position = None

    def _trip_fault(self, reason):
        self.fault = True
        self.fault_reason = reason
        self._queue = []
        self._current = None
        self._current_start_ms = None
        self._current_start_position = None
        self._diffdrive.neutral()

    def tick(self, now_ms):
        """Advance the queue by one cycle. See module docstring for why
        this must be pumped periodically (framework-owned, via
        ``comms.py``'s scheduled pump) rather than by an ``on_tick()``
        callback this module registers itself."""
        if self.fault:
            return
        if self._current is None:
            if not self._queue:
                return
            self._start_next(now_ms)

        move = self._current
        elapsed = now_ms - self._current_start_ms

        if elapsed > move.duration_ms + TIMEOUT_GRACE_MS:
            self._trip_fault("timeout")
            return

        if move.stop_distance_mm is not None and self._distance_travelled() >= move.stop_distance_mm:
            self._complete_current()
            return

        if elapsed >= move.duration_ms:
            self._complete_current()
            return

        remaining = move.duration_ms - elapsed
        lease = remaining if remaining < DEFAULT_LEASE_MS else DEFAULT_LEASE_MS
        self._diffdrive.drive(move.v, move.twist, int(lease))


def _atan2(y, x):
    return math.atan2(y, x)


def _normalize_angle(angle):
    """Wrap ``angle`` (radians) to (-pi, pi]."""
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle <= -math.pi:
        angle += 2.0 * math.pi
    return angle


def _duration_for_angle_ms(angle, omega):
    if omega == 0:
        return MAX_MOVE_DURATION_MS
    duration = int(abs(angle) / abs(omega) * 1000.0)
    if duration <= 0:
        duration = 1
    if duration > MAX_MOVE_DURATION_MS:
        duration = MAX_MOVE_DURATION_MS
    return duration


def _duration_for_distance_ms(distance, speed):
    if speed == 0:
        return MAX_MOVE_DURATION_MS
    duration = int(abs(distance) / abs(speed) * 1000.0)
    if duration <= 0:
        duration = 1
    if duration > MAX_MOVE_DURATION_MS:
        duration = MAX_MOVE_DURATION_MS
    return duration


# --- Generator-driven move mode (SUC-001/SUC-002) -----------------------
# Additive: a new, separate entry point alongside MoveQueue above
# (unchanged). Mode latches natively on the first diffdrive.step()
# call this boot (ticket 006's start()/step() latch) -- no mode tracking
# here duplicates that.

try:
    import utime as _time
except ImportError:  # CPython -- no utime; shims below stand in for it
    import time as _time


def _ticks_ms():
    if hasattr(_time, "ticks_ms"):
        return _time.ticks_ms()
    return int(_time.monotonic() * 1000)


def _ticks_add(ticks, delta):
    if hasattr(_time, "ticks_add"):
        return _time.ticks_add(ticks, delta)
    return ticks + delta


def _ticks_diff(a, b):
    if hasattr(_time, "ticks_diff"):
        return _time.ticks_diff(a, b)
    return a - b


def _sleep_ms(ms):
    if hasattr(_time, "sleep_ms"):
        _time.sleep_ms(ms)
    else:
        _time.sleep(ms / 1000.0)


# Short lease multiple (~3x cyclePeriod), renewed every next() -- an
# abandoned generator decays to neutral on its own before the watchdog
# would ever need to act (SUC-002).
GEN_LEASE_PERIODS = 3


class MoveHandle:
    """Wraps the generator ``drive()`` builds so stopping can be an
    explicit method call instead of relying on generator finalization.

    Ticket 012, measured on hardware: a bare ``break`` out of ``for
    state in motion.drive(...):`` does NOT run the generator's
    ``finally`` on MicroPython -- mark-and-sweep GC does not promptly
    close a suspended generator the way CPython's refcounting does, so
    ``GeneratorExit`` never fires and the wheels keep the last commanded
    duty until the starvation watchdog trips (~250 ms). ``stop()`` makes
    the close explicit and reliable instead of implicit and timing-
    dependent -- it does not duplicate the landing logic, it just
    guarantees ``close()`` actually happens.

    Two supported idioms, one mechanism (both call ``stop()``):

    * Explicit -- ``move = motion.drive(...); ...; move.stop()``.
    * Context manager -- ``with motion.drive(...) as move: ...`` --
      preferred for student code since ``__exit__`` stops the wheels no
      matter how the block is left (normal exit, ``break``, or an
      exception).

    ``__iter__``/``__next__`` delegate to the wrapped generator, so
    plain ``for state in motion.drive(...):`` keeps working unchanged
    for callers who always let the move run to completion.
    """

    def __init__(self, gen):
        self._gen = gen
        self._stopped = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._gen)

    def stop(self):
        """Close the inner generator, running its existing ``finally``
        (``neutral()`` + one landing ``step()``). Idempotent: safe to
        call twice, after the move already completed normally, or from
        inside the loop right before ``break``."""
        if self._stopped:
            return
        self._stopped = True
        self._gen.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        return False  # never suppress an exception raised in the `with` block


def drive(diffdrive, v, twist, duration_ms, ticks_ms=_ticks_ms, sleep_ms=_sleep_ms):
    """Generator-driven move: each ``next()`` runs one ``diffdrive.step()``
    cycle and yields ``diffdrive.output()``; the generator owns pacing --
    absolute deadlines against ``diffdrive.cyclePeriod()``, mirroring the
    vendored kernel's own ``run()`` pacing rule, not a fixed
    ``sleep(period)`` that drifts under jitter. ``duration_ms``:
    MILLISECONDS (module docstring's ms-not-seconds landmine --
    ``0 <= duration_ms <= MAX_MOVE_DURATION_MS``).

    Returns a ``MoveHandle`` (not a bare generator) -- iterate it
    directly (``for state in motion.drive(...):``), or stop it early
    with ``move.stop()`` / ``with motion.drive(...) as move:`` (see
    ``MoveHandle``). A bare ``break`` alone does NOT land a clean
    neutral on MicroPython (ticket 012) -- ``stop()``/``with`` is the
    documented contract, not the watchdog's ~250 ms coast.

    On normal completion, or when ``stop()`` closes the generator, the
    ``finally`` block commands ``neutral()`` and lands one more
    ``step()`` so the staged zero actually reaches the bus: wheels move
    only while the caller keeps iterating (and has not stopped).

    ``ticks_ms``/``sleep_ms``: injectable clock seam for offline tests
    (default: ``utime`` on-device, a ``time.monotonic()``-based shim
    under CPython) -- same DI pattern as ``comms.PumpTimer``'s ``now_fn``.
    """
    return MoveHandle(_drive_gen(diffdrive, v, twist, duration_ms, ticks_ms, sleep_ms))


def _drive_gen(diffdrive, v, twist, duration_ms, ticks_ms, sleep_ms):
    """The generator ``drive()`` wraps in a ``MoveHandle``. Not part of
    the public surface -- call ``drive()``."""
    if duration_ms < 0 or duration_ms > MAX_MOVE_DURATION_MS:
        raise MoveQueueError(
            "duration_ms out of range (ms, not seconds): %r" % (duration_ms,)
        )
    period_ms = diffdrive.cyclePeriod()
    lease_ms = period_ms * GEN_LEASE_PERIODS
    end = _ticks_add(ticks_ms(), duration_ms)
    cycle = ticks_ms()
    try:
        while _ticks_diff(end, ticks_ms()) > 0:
            wait = _ticks_diff(cycle, ticks_ms())
            if wait > 0:
                sleep_ms(wait)
            cycle = _ticks_add(cycle, period_ms)  # absolute deadline, not now()+period
            diffdrive.drive(v, twist, lease_ms)
            diffdrive.step()
            yield diffdrive.output()
    finally:
        diffdrive.neutral()
        diffdrive.step()  # one landing cycle so the staged zero reaches the bus
