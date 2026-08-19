"""motion -- move queue, stop conditions, timeout fault, replace
semantics, GO_TO, CALIBRATE, and the CONFIG-family/motion verb dispatch
router, M5 (PLAN.md / ``docs/design/specification.md`` Sec 6/7.2, UC-013).

**Every duration in this module is MILLISECONDS.** PLAN.md's landmine
ledger (L4): a sec/ms slip once ran wheels 8+ minutes unsupervised --
this is a load-bearing regression risk, not a style note. See
``MAX_MOVE_DURATION_MS`` and ``tests/test_motion.py``'s own explicit
ms-vs-seconds regression assertion.

---

**Teaching-framework loop-ownership decision** (spec Sec 7.2 / Sec 10
open item 4, "decide before M5" -- this ticket's own explicit
instruction to resolve or escalate, not guess):

DECIDED: no ``on_tick()`` callback framework is implemented. This
module exposes plain, direct function calls (``MoveQueue.enqueue()``/
``stop()``/``estop()``/``go_to()``), driven either by ``comms.py``'s
verb dispatch (the primary, wire-driven path -- ``RobotDispatch``
below) or directly from student/REPL code. The vendored kernel
(``vendor/differential_drive.h``) free-runs its own control cadence on
a CODAL fiber, independent of Python's call stack (spec Sec 5/7.1) --
so "loop ownership" for WHEEL MOTION itself resolves to "the kernel
owns cadence, not Python," regardless of whether student code is
shaped as ``while True:`` or anything else. What DOES need periodic
pumping is ``MoveQueue.tick()`` (renews leases, advances the queue,
detects timeout faults) -- that pumping is FRAMEWORK-owned, via
``comms.py``'s scheduled pump (ticket 005's ``PumpTimer``/
``micropython.schedule``), the same mechanism that already services
wire commands every cycle. This is a rejection of an ``on_tick()``-
per-move callback registration as unneeded complexity on top of that
existing pump.

Student-facing contract (spec Sec 7.2, restated here since this is
where the loop-ownership decision lives): wheel control requires
reaching idle (``microbit_hal_idle()``) for the kernel fiber to be
scheduled at all -- a tight ``while True:`` loop that never reaches
idle (including the realistic polling idiom ``while True: p =
radio.receive()``) starves the kernel fiber. The VM-hook starvation
watchdog (``native/watchdog.h``, ticket 004) is the safety backstop for
that case (fault bit surfaced in ``telemetry.py``'s ``watchdog_fault``
field), not a substitute for the contract itself.

KNOWN GAP, flagged not silently dropped: a stakeholder-approved,
NOT-YET-TICKETED issue
(``clasi/issues/generator-driven-control-loop-mode-addition-not-
replacement.md``, status ``pending``, untracked in this sprint's
``sprint.md`` issue list as of this ticket) proposes a SECOND,
additive execution mode -- move commands as Python generators, where
each ``next()`` runs one kernel ``step()`` inline and the generator
owns pacing (framework-owned cadence inside the generator,
student-owned loop body -- explicitly "neither ``on_tick()`` nor raw
student ``while True:``", the same rejection of ``on_tick()`` this
ticket independently reaches for the surface it DOES implement). That
mode requires new native bindings (``diffdrive.step()``, a mode
latch, mode-aware Sleeper, a reentrancy guard, a ``cyclePeriod``
accessor) that its own text describes as "a small follow-on ticket
after 004 closes, before ticket 007 needs them" -- confirmed NOT
present (``native/moddiffdrive.cpp`` exposes no ``step`` binding; no
such follow-on ticket exists in this sprint's ticket list;
``mcp__clasi__list_tickets`` shows only 001-009). Building that native
extension is out of this ticket's own file scope (``native/`` C++ work
needing its own qstr/glue wiring and a verified rebuild) and is not
required by this ticket's acceptance criteria (which test the
background-mode queue/stop/timeout/replace/ms semantics, not
generator mode). This module therefore implements ONLY the
background-mode surface; generator mode is deliberately deferred,
recorded here for a follow-on ticket rather than guessed at or
silently omitted.

---

Verb payload shapes (this ticket's own hand-decoded, documented
convention -- ``msgs.py`` has no per-verb protobuf field tables yet,
same discipline as ``config.py``'s CONFIG-family dispatch):

  MOVE:      corr_id:u8, queue_mode:u8 (0=replace,1=append), v:f32-LE,
             twist:f32-LE, duration_ms:u32-LE, has_stop_distance:u8,
             stop_distance_mm:f32-LE                       (19 bytes)
  WHEELS:    corr_id:u8, duty_left:f32-LE, duty_right:f32-LE,
             lease_ms:u32-LE                                (13 bytes)
  STOP:      corr_id:u8                                      (1 byte)
  ESTOP:     corr_id:u8                                      (1 byte)
  GO_TO:     corr_id:u8, x:f32-LE, y:f32-LE, speed:f32-LE,
             omega:f32-LE                                   (17 bytes)
  CALIBRATE: corr_id:u8, kind:u8 (0=line_cal_min,1=line_cal_max)
                                                               (2 bytes)
"""

import math
import struct

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
    "RobotDispatch",
    "ERR_OK",
    "ERR_QUEUE_FULL",
    "ERR_FAULTED",
    "ERR_DURATION_TOO_LONG",
    "ERR_MALFORMED",
]

MAX_QUEUE_DEPTH = 5

# Policy ceiling on a single queued move's OWN duration_ms -- separate
# from and much larger than the native binding's 5000 ms per-call LEASE
# ceiling (a queued move renews its lease repeatedly via tick(), see
# MoveQueue.tick()'s own comment); this is the ms-not-seconds landmine
# guard (PLAN.md L4): a move is REFUSED at enqueue time, never silently
# clamped, if its duration is not a plausible millisecond value. 60000 ms
# (60 s) is generous for a classroom teaching move while still catching
# an 8-minute-class of bug (480000+ ms would refuse; more importantly, a
# units-confused caller who means "8 seconds" but sends a raw "8"
# (thinking whole seconds) gets an almost-instant move, visibly wrong in
# the classroom -- not a landmine this ceiling can catch by itself, which
# is exactly why "every duration is ms" is a documented CONTRACT, not
# just a bound).
MAX_MOVE_DURATION_MS = 60000

# Per-tick() lease renewal -- well under the native binding's 5000 ms
# ceiling (native/moddiffdrive.cpp's kBindingLeaseMaxMs) so a queue that
# stops ticking (student loop stalls) decays to neutral quickly via the
# kernel's own lease expiry, without this module needing its own timer.
DEFAULT_LEASE_MS = 1000

# Grace window past a move's own duration_ms before a still-not-complete
# move is treated as a TIMEOUT FAULT rather than an ordinary duration
# completion crossed by normal tick() jitter -- deliberately reuses the
# VM-hook starvation watchdog's own 250 ms stall threshold
# (native/watchdog.h kStallThresholdUs) as a single, cross-referenced
# "how long is a real stall" constant rather than inventing a second one.
TIMEOUT_GRACE_MS = 250

QUEUE_MODE_REPLACE = 0
QUEUE_MODE_APPEND = 1

ERR_OK = 0
ERR_QUEUE_FULL = 1
ERR_FAULTED = 2
ERR_DURATION_TOO_LONG = 3
ERR_MALFORMED = 4


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
    with at least ``positionLeft``/``positionRight`` -- the REAL
    ``diffdrive`` native module (ticket 004) or a stub, per this
    ticket's own Gate wording).

    Call ``tick(now_ms)`` every cycle (from ``comms.py``'s scheduled
    pump, per this module's own loop-ownership decision above) to
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
        issue time (open-loop within each leg; this is a simple
        turn-then-drive strategy, NOT the continuously-corrected
        navigation radio-robot-elite's own evolved ``Motion::Navigator``
        provides -- that subsystem has no equivalent in the vendored
        ``DiffDrive`` kernel this port uses, so this is a deliberately
        scoped-down, documented GO_TO, not a re-derivation of that
        system). ``speed``: [counts/s] for the straight leg.
        ``omega``: [counts/s] twist magnitude for the turn leg (sign
        chosen by the computed turn direction). Returns ``True`` if both
        legs were queued, ``False`` (no state change) if the queue
        refused (faulted, or -- with ``QUEUE_MODE_APPEND`` -- already at
        depth) or the two legs would not both fit."""
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


def _unpack_f32_le(data):
    return struct.unpack("<f", bytes(data))[0]


class RobotDispatch:
    """The single composite object wired as ``comms.Comms(...,
    dispatch=...)`` -- routes CONFIG-family verbs to a
    ``config.ConfigDispatch`` and motion verbs (MOVE/WHEELS/STOP/ESTOP/
    GO_TO/CALIBRATE) to a ``MoveQueue``, matching ``comms.py``'s own
    single-dispatch-object interface
    (``handle_command(verb_name, payload, now) -> (corr_id, err_code) |
    None``). ``line_sensor`` (optional, a ``line.LineSensor``) backs
    CALIBRATE; ``pose_provider`` (optional, a zero-arg callable
    returning ``(x, y, heading_rad)``) backs GO_TO -- both may be
    ``None`` if this robot has no line sensor / no pose estimate wired
    yet, in which case the corresponding verb acks ``ERR_MALFORMED``
    rather than raising."""

    def __init__(self, config_dispatch, move_queue, line_sensor=None, pose_provider=None):
        self._config_dispatch = config_dispatch
        self._queue = move_queue
        self._line_sensor = line_sensor
        self._pose_provider = pose_provider

    def handle_command(self, verb_name, payload, now):
        if verb_name in ("CONFIG", "SET_FIELD", "GET_CONFIG"):
            return self._config_dispatch.handle_command(verb_name, payload, now)
        if verb_name == "MOVE":
            return self._handle_move(payload)
        if verb_name == "WHEELS":
            return self._handle_wheels(payload)
        if verb_name == "STOP":
            return self._handle_stop(payload)
        if verb_name == "ESTOP":
            return self._handle_estop(payload)
        if verb_name == "GO_TO":
            return self._handle_go_to(payload)
        if verb_name == "CALIBRATE":
            return self._handle_calibrate(payload)
        return None

    def _handle_move(self, payload):
        if len(payload) != 19:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        queue_mode = payload[1]
        v = _unpack_f32_le(payload[2:6])
        twist = _unpack_f32_le(payload[6:10])
        duration_ms = struct.unpack("<I", bytes(payload[10:14]))[0]
        has_stop_distance = payload[14]
        stop_distance_mm = _unpack_f32_le(payload[15:19]) if has_stop_distance else None

        if duration_ms == 0 or duration_ms > MAX_MOVE_DURATION_MS:
            return (corr_id, ERR_DURATION_TOO_LONG)
        try:
            move = Move(v=v, twist=twist, duration_ms=duration_ms,
                        stop_distance_mm=stop_distance_mm)
        except MoveQueueError:
            return (corr_id, ERR_DURATION_TOO_LONG)

        ok = self._queue.enqueue(move, queue_mode=queue_mode)
        if not ok:
            return (corr_id, ERR_FAULTED if self._queue.fault else ERR_QUEUE_FULL)
        return (corr_id, ERR_OK)

    def _handle_wheels(self, payload):
        if len(payload) != 13:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        duty_left = _unpack_f32_le(payload[1:5])
        duty_right = _unpack_f32_le(payload[5:9])
        lease_ms = struct.unpack("<I", bytes(payload[9:13]))[0]

        self._queue.stop()  # WHEELS is an immediate teleop command -- clears the queue first
        status = self._queue.diffdrive.driveDuty(duty_left, duty_right, lease_ms)
        return (corr_id, ERR_OK if status == "ok" else ERR_MALFORMED)

    def _handle_stop(self, payload):
        if len(payload) != 1:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        self._queue.stop()
        return (payload[0], ERR_OK)

    def _handle_estop(self, payload):
        if len(payload) != 1:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        self._queue.estop()
        return (payload[0], ERR_OK)

    def _handle_go_to(self, payload):
        if len(payload) != 17:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        if self._pose_provider is None:
            return (corr_id, ERR_MALFORMED)
        x = _unpack_f32_le(payload[1:5])
        y = _unpack_f32_le(payload[5:9])
        speed = _unpack_f32_le(payload[9:13])
        omega = _unpack_f32_le(payload[13:17])
        ok = self._queue.go_to(x, y, self._pose_provider(), speed, omega)
        return (corr_id, ERR_OK if ok else ERR_QUEUE_FULL)

    def _handle_calibrate(self, payload):
        if len(payload) != 2:
            return (_corr_id_or_none(payload), ERR_MALFORMED)
        corr_id = payload[0]
        kind = payload[1]
        if self._line_sensor is None:
            return (corr_id, ERR_MALFORMED)
        reading = self._line_sensor.reading
        if kind == 0:
            self._line_sensor.cal_min = list(reading.raw)
        elif kind == 1:
            self._line_sensor.cal_max = list(reading.raw)
        else:
            return (corr_id, ERR_MALFORMED)
        return (corr_id, ERR_OK)


def _corr_id_or_none(payload):
    if payload:
        return payload[0]
    return None
