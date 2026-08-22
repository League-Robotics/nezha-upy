"""protocol_adapter -- the real v6 ``Adapter`` (``protocol.md`` Sec 4/5/7)
that ``src/core/protocol.py``'s ``ProtocolHandler`` dispatches to, once
wired in (sprint 007 ticket 006). Bridges the handler's duck-typed
``identity()``/``now()``/``status()``/``on_estop()``/``on_get()``/
``on_set()``/``field_count()``/``field_name()``/``on_tlm()``/
``on_wheels()``/``on_stop()`` seam onto the SAME ``motion.MoveQueue``/
``config.ConfigDispatch`` objects the retiring ``motion.RobotDispatch``
wrapped (ticket 006 deletes that class once this one exists to replace
it). See ``clasi/sprints/007-.../sprint.md``'s Architecture section for
why this module lives at ``hardware/`` rather than a third top-level
``adapter/`` package, and its Design Rationale for the WHEELS
raw-duty -> velocity behavior change this ticket makes real.

Ported from radio-robot-lib's ``src/adapter/diffdrive_adapter.{h,cpp}``
(the C++ archetype ``Protocol::DiffDriveAdapter``) -- read that pair
first if extending this module; ``docs/design/protocol.md`` Sec 5/7 is
the spec both implement. This port intentionally keeps the archetype's
own scope choices:

- ``countsPerLength`` [counts/mm] is the ONE geometry factor this whole
  path needs (Sec 4 point 2 / Sec 5 point 2) -- a constructor argument,
  not a config field, because it is a property of the robot's gearing/
  wheel, not a tunable control-law gain, so it is NOT reachable through
  ``GET``/``SET``. A non-positive value is rejected and this adapter
  falls back to ``1.0`` (mm == counts) rather than dividing by zero
  later, mirroring ``DiffDriveAdapter``'s own constructor guard.
- ``maxDuty``/``fullDutyVelocity``/``cyclePeriod`` are NOT this
  adapter's problem at all in this port: unlike the C++ archetype
  (which hard-codes them onto the kernel at construction, Sec 7),
  ``core/boot.py``'s existing Step 2 already calls
  ``diffdrive.configure(**config.diffdrive_configure_kwargs(...))``
  before any adapter exists -- this module never touches kernel
  bring-up, only the already-configured ``diffdrive`` object handed to
  it via ``move_queue.diffdrive``.

Wire-reachable ``GET``/``SET`` field names (this ticket's own
implementation decision, per ``protocol.md`` Sec 7: "which names are
valid is entirely the adapter's business" -- recorded here, and in
ticket 005's own completion notes): the 15 ``wheel_control`` JSON field
names ``config.WHEEL_CONTROL_FIELDS`` already declares (``v_min``,
``bias_max``, ``tau_adapt``, ``a_steady``, ``deficit_threshold``,
``deficit_window``, ``pid_kp``, ``pid_ki``, ``pid_i_max``, ``pid_kaff``,
``pid_max``, ``pos_err_max``, ``stall_speed``, ``stall_demand``,
``stall_window``), in that same declaration order for ``field_name()``'s
bare-``GET`` enumeration. Chosen over the C++ archetype's own
``"wheel_control.v_min"``-prefixed wire names because this port has no
second config group ever likely to collide on ``v_min`` alone, and the
bare JSON name is what ``data/<robot>.json`` and ``config.py`` already
call the same field everywhere else in this codebase -- a wire client
reading this robot's own JSON to guess a field name gets the right
answer with no prefix to strip. Resolution itself is NOT duplicated
here: ``on_get()``/``on_set()`` delegate to ``config.ConfigDispatch``'s
new ``get_field()``/``set_field()`` accessors (added by this same
ticket), which are the one place that knows which 15 names are valid --
this module only holds the ORDER they enumerate in for bare ``GET``.

``WHEELS``'s behavior change (sprint.md Design Rationale, "an accepted
behavior change, not a bug"): v5's raw open-loop
``diffdrive.driveDuty()`` teleop is gone. ``on_wheels()`` scales
``[mm/s]`` by ``countsPerLength`` into ``[counts/s]``, splits into
``velocity``/``twist`` (half-sum / half-difference), and calls
``move_queue.diffdrive.drive(velocity, twist, lease_ms)`` directly --
bypassing ``MoveQueue.enqueue()``/``tick()`` entirely, matching
``protocol.md`` Sec 5.1's "there is no queue in this library... WHEELS
reaches ``drive()`` directly." ``twist`` is CCW-positive by
construction: ``twist = (right - left) / 2`` means a faster RIGHT wheel
makes a positive twist. Swap which argument is "left" here and every
twist sign inverts -- Sec 5 point 3 names this the single most repeated
bug in the project's history, which is why this module's own test suite
carries an explicit wheel-swap sign test that would fail if the two
wheels were exchanged.

The wire's 5000 ms ``WHEELS`` duration ceiling (``protocol.md`` Sec 5
point 1 / Sec 9.1: "the handler holds no bounds table") is enforced
HERE, above the kernel call, returning ``Result.RANGE`` without ever
reaching ``diffdrive.drive()`` -- mirroring the C++ archetype's own
``onWheels()`` exactly. This is deliberately NOT relying on
``native/moddiffdrive.cpp``'s own, separately-motivated
``kBindingLeaseMaxMs`` guard (same 5000 ms number, a different landmine
-- PLAN.md L4's ms-not-seconds guard at the native-binding layer): that
guard exists whether or not this adapter is even in the picture, but
``protocol.md``'s own spec puts the ceiling-enforcement OBLIGATION on
the adapter, not on whichever binding happens to be underneath it, so
this module checks first and never depends on the deeper guard firing.
A negative ``duration`` is NOT separately rejected here for the same
reason the C++ archetype's own check is upper-bound-only (its
``duration`` parameter is ``uint32_t``, which cannot even represent a
negative value) -- on the real device, ``moddiffdrive.cpp``'s own
``leaseMs < 0`` branch backstops it via the exact same
``"refused_lease_ceiling"`` status string this module already maps to
``Result.RANGE`` (see ``_status_to_result()``); a fake ``diffdrive`` in
an offline test that skips that guard is simply untested territory this
ticket's own scope does not require covering.

``on_stop()``/``on_estop()`` (``protocol.md`` Sec 5.1): ``STOP`` reaches
``move_queue.diffdrive.neutral()`` DIRECTLY (not through
``MoveQueue.stop()``, which would also clear ``MoveQueue``'s own
pending-move list -- a v5-era queueing concept nothing in the v6 wire
path ever populates, since ``on_wheels()`` above never calls
``enqueue()``) -- mirrors v5's ``RobotDispatch._handle_stop()``'s own
``self._queue.stop()`` call in spirit (a graceful, always-accepted
stop), just narrowed to the one kernel effect that still matters here.
``neutral()`` has no refusal path of its own (even pre-``begin()`` or
mid-``estop()``), so ``on_stop()`` always returns ``Result.OK``.
``ESTOP`` reaches ``move_queue.estop()`` (the queue's own method, which
clears its pending list AND latches the kernel's ``estop()`` under one
call) and returns ``None`` -- ``protocol.py``'s ``_handle_estop()``
never inspects an ``on_estop()`` return value at all (``ESTOP`` is never
acked at the wire level, so there is no ``Result`` to hand back).

``on_tlm(mode)`` persists ``mode`` (one of the six decoded wire strings,
already validated by the handler) as this adapter's own single, shared
value -- ``protocol.md`` Sec 6's table entry: "mode-specific behavior
beyond persisting the value is the calling application's job." Unlike
the C++ archetype, this port does NOT special-case ``"NOW"`` as a
non-persisted one-shot (that nuance lives in ``DiffDriveAdapter``'s own
comment, not in ``protocol.md`` itself, and neither this ticket's
acceptance criteria nor its test list calls for it) -- every mode the
handler hands over is stored as-is; a one-shot ``NOW`` read without
changing the persisted subscription, if ever needed, is exactly the
"calling application's job" ``comms.py`` (ticket 006) is free to add
later without touching this method's contract. Per ``sprint.md``'s
Design Rationale, this value is intentionally the ONE piece of state
this adapter holds that is NOT per-``ProtocolHandler``-instance --
every transport's handler shares the SAME ``ProtocolAdapter``, so
``TLM``'s mode is one robot-wide subscription, not one per channel.

``status()``'s ``otos``/``wedge`` fields are constant ``False``
placeholders: this sprint wires no OTOS or line-sensor hardware (
``sprint.md`` Scope), so there is nothing live to report -- a
deliberate, commented placeholder, not a silent omission. ``flags`` is
a LOCAL bit layout (this port's own, not any externally-numbered
scheme) built from ``diffdrive.output()``'s own health booleans,
matching the C++ archetype's ``computeFlags()`` posture: reusing a
spec-numbered bit layout that assumes subsystems this robot doesn't
have (OTOS/line/planner) would misrepresent what the bits mean to a
future reader with the spec open.

LANDMINE: no f-strings, no PEP 604/generic-subscript type hints, no
host-only stdlib -- must import and run unmodified under both CPython
(host tests) and MicroPython (CLAUDE.md).
"""

from core import config
from core import protocol

__all__ = [
    "ProtocolAdapter",
    "WHEELS_DURATION_CEILING_MS",
]

# protocol.md Sec 5 point 1 / Sec 9.1: "duration [ms] required, ceiling
# 5000 -- a dead host cannot mean a runaway... enforced by the adapter
# (the handler holds no bounds table)." Same NUMBER as native/
# moddiffdrive.cpp's own kBindingLeaseMaxMs, for a different reason
# (see module docstring) -- not derived from it, spelled here as its
# own named constant so this module's own obligation reads on its own.
WHEELS_DURATION_CEILING_MS = 5000.0

# ---- diffdrive status-string -> wire Result (protocol.md Sec 6.1) --------
# native/moddiffdrive.cpp's diffdrive.drive() returns a STATUS STRING
# (statusToStr() there), not an enum -- this table is this port's own
# equivalent of DiffDriveAdapter::statusToResult()'s switch, ported to a
# dict lookup since Python has no switch. Sec 6.1's own code table has
# no dedicated "estopped"/"unconfigured"/"not begun" entry, so all three
# pre-ready refusals collapse onto ERR_NOT_CONFIGURED ("refused
# pre-ready") -- the same collapse the C++ archetype's own
# statusToResult() performs onto its single Result::kNotReady, just
# spelled with this port's own available code (protocol.py's Result
# class has no NOT_READY of its own; see that module's docstring for why
# its numbering already matches the wire 1:1 and adds nothing beyond
# it). "refused_non_finite" -> BADARG mirrors the archetype's own
# kRefusedNonFinite -> kBadArg mapping. "refused_lease_ceiling" is
# native/moddiffdrive.cpp's OWN 5000 ms guard (see module docstring) --
# included here defensively so a divergence between that guard and this
# module's own WHEELS_DURATION_CEILING_MS check (there is none today;
# both are 5000) would still surface as ERR_RANGE, not ERR_UNKNOWN.
_STATUS_TO_RESULT = {
    "ok": protocol.Result.OK,
    "refused_unconfigured": protocol.Result.NOT_CONFIGURED,
    "refused_not_begun": protocol.Result.NOT_CONFIGURED,
    "refused_estopped": protocol.Result.NOT_CONFIGURED,
    "refused_non_finite": protocol.Result.BADARG,
    "refused_lease_ceiling": protocol.Result.RANGE,
}


def _status_to_result(status):
    return _STATUS_TO_RESULT.get(status, protocol.Result.UNKNOWN)


# ---- local STATUS flags layout (protocol.md Sec 5.2's own "a LOCAL bit
# layout, not a spec-numbered scheme" posture -- see module docstring).
_FLAG_READY = 1 << 0
_FLAG_ESTOPPED = 1 << 1
_FLAG_LEASE_EXPIRED = 1 << 2
_FLAG_STALL_HALTED = 1 << 3
_FLAG_CONNECTED_LEFT = 1 << 4
_FLAG_CONNECTED_RIGHT = 1 << 5


try:
    import utime as _time
except ImportError:  # CPython -- no utime; a monotonic-clock shim stands in
    import time as _time


def _default_now_ms():
    """Default ``now_fn`` -- ``utime.ticks_ms()`` on-device,
    ``time.monotonic()*1000`` under CPython. Same DI pattern as
    ``core.comms.PumpTimer``'s own ``now_fn`` (and ``core.boot``'s
    ``_now_ms()``) -- injectable so offline tests never depend on wall
    clock time."""
    if hasattr(_time, "ticks_ms"):
        return _time.ticks_ms()
    return int(_time.monotonic() * 1000)


# The 15 wire-reachable GET/SET names, in WHEEL_CONTROL_FIELDS's own
# declaration order (module docstring: this port's own field-name
# exposure decision) -- built once at import time, not per-instance,
# since it never varies by robot.
_FIELD_NAMES = tuple(
    json_field for json_field, _kernel_field in config.WHEEL_CONTROL_FIELDS
)


class ProtocolAdapter(object):
    """The v6 ``Adapter`` (``protocol.md`` Sec 4), backed by an existing
    ``motion.MoveQueue`` (for ``move_queue.diffdrive``'s ``drive()``/
    ``neutral()``/``output()`` and ``move_queue.estop()`` itself) and an
    existing ``config.ConfigDispatch`` (for its ``get_field()``/
    ``set_field()`` name-keyed accessors). Both are duck-typed
    (MicroPython has no ``abc`` module) -- a fake diffdrive-backed
    ``MoveQueue`` and a ``ConfigDispatch`` built from a small literal
    ``wheel_control`` dict are exactly what this module's own test suite
    injects, mirroring ``tests/test_motion.py``'s/``tests/
    test_comms_loopback.py``'s established interface-seam convention.

    One instance is shared across every registered transport's own
    ``protocol.ProtocolHandler`` (``sprint.md``'s Design Rationale:
    "one robot, not one per transport") -- ``on_tlm()``'s persisted mode
    and every kernel/config effect are therefore visible to every
    handler that shares this adapter."""

    def __init__(self, move_queue, config_dispatch, counts_per_length,
                 name, serial, drivetrain, profile, version, now_fn=None):
        self._move_queue = move_queue
        self._config_dispatch = config_dispatch
        # Non-positive rejected, falls back to 1.0 (mm == counts) --
        # mirrors DiffDriveAdapter's own constructor guard (module
        # docstring) rather than dividing by zero in on_wheels() later.
        self._counts_per_length = (
            counts_per_length if counts_per_length > 0.0 else 1.0
        )
        self._name = name
        self._serial = serial
        self._drivetrain = drivetrain
        self._profile = profile
        self._version = version
        self._now_fn = now_fn if now_fn is not None else _default_now_ms
        # protocol.md Sec 6: TLM's own default subscription is OFF until
        # a client ever sends one -- stored uppercase (the same casing
        # the wire's TLM verb and _TLM_MODES use), reported lowercase by
        # status() to match protocol.md's own literal STATUS example
        # ("tlm=off").
        self._tlm_mode = "OFF"

    # ---- session identity/clock/status -----------------------------------

    def identity(self):
        """protocol.md Sec 3.1/4: ``(name, serial, drivetrain, profile,
        version)`` -- backs HELLO's banner, ID, and VER."""
        return (self._name, self._serial, self._drivetrain, self._profile,
                self._version)

    def now(self):
        """Robot clock, ``[ms]`` -- backs PING's ``pong <now>``."""
        return self._now_fn()

    def status(self):
        """``(ready, active, conn_left, conn_right, otos, wedge, flags,
        tlm)`` -- projects ``move_queue.diffdrive.output()``'s health
        booleans (module docstring: ``otos``/``wedge`` are constant
        placeholders this sprint, ``flags`` a local bit layout)."""
        out = self._move_queue.diffdrive.output()
        ready = bool(out.get("ready", False))
        estopped = bool(out.get("estopped", False))
        lease_expired = bool(out.get("leaseExpired", False))
        stall_halted = bool(out.get("stallHalted", False))
        conn_left = bool(out.get("connectedLeft", False))
        conn_right = bool(out.get("connectedRight", False))
        velocity = out.get("velocity", 0.0)
        twist = out.get("twist", 0.0)

        # "active" == "a motion command is currently in effect" -- the
        # same reading DiffDriveAdapter::status() gives spec Sec 6.5's
        # bit 2 for a WHEELS-only, planner-free command surface.
        active = (ready and not estopped and not lease_expired
                  and not stall_halted
                  and (velocity != 0.0 or twist != 0.0))

        flags = 0
        if ready:
            flags |= _FLAG_READY
        if estopped:
            flags |= _FLAG_ESTOPPED
        if lease_expired:
            flags |= _FLAG_LEASE_EXPIRED
        if stall_halted:
            flags |= _FLAG_STALL_HALTED
        if conn_left:
            flags |= _FLAG_CONNECTED_LEFT
        if conn_right:
            flags |= _FLAG_CONNECTED_RIGHT

        otos = False  # no OTOS wired this sprint (sprint.md Scope) -- placeholder
        wedge = False  # no line sensor wired this sprint -- placeholder
        tlm = self._tlm_mode.lower()
        return (ready, active, conn_left, conn_right, otos, wedge, flags, tlm)

    # ---- motion: WHEELS/STOP/ESTOP (protocol.md Sec 5/5.1/9.1) -----------

    def on_wheels(self, left, right, duration, reply_id):
        """``left``/``right``: ``[mm/s]``. ``duration``: ``[ms]``, the
        drive lease. Scales by ``countsPerLength`` into ``[counts/s]``,
        splits into ``velocity``/``twist``, and calls ``move_queue.
        diffdrive.drive()`` directly (module docstring: no queue
        involved). The 5000 ms ceiling is checked BEFORE any kernel
        call -- see ``WHEELS_DURATION_CEILING_MS``'s own comment."""
        if duration > WHEELS_DURATION_CEILING_MS:
            return protocol.Result.RANGE

        counts_left = left * self._counts_per_length      # [counts/s]
        counts_right = right * self._counts_per_length    # [counts/s]
        velocity = (counts_left + counts_right) * 0.5     # [counts/s]
        twist = (counts_right - counts_left) * 0.5        # [counts/s]

        status = self._move_queue.diffdrive.drive(velocity, twist,
                                                    int(duration))
        return _status_to_result(status)

    def on_stop(self, reply_id):
        """``STOP #<id>`` -> ``move_queue.diffdrive.neutral()`` directly
        (module docstring). ``neutral()`` has no refusal path, so this
        always returns ``Result.OK`` (protocol.md Sec 5.1)."""
        self._move_queue.diffdrive.neutral()
        return protocol.Result.OK

    def on_estop(self):
        """``ESTOP`` -> ``move_queue.estop()`` (clears any pending move
        and latches the kernel's own ``estop()``). Returns nothing --
        ``ESTOP`` is never acked at the wire level (protocol.md Sec 4),
        so there is no ``Result`` for the handler to inspect."""
        self._move_queue.estop()

    # ---- configuration: pure delegation (protocol.md Sec 7) --------------

    def on_get(self, name):
        """Resolves ``name`` against ``config_dispatch.get_field()``.
        ``None`` means "unknown name" -- the handler's own ``GET``
        path treats that as silent, no reply (protocol.md Sec 7.1)."""
        return self._config_dispatch.get_field(name)

    def on_set(self, name, value, reply_id):
        """Resolves ``name`` against ``config_dispatch.set_field()``.
        An unrecognized name returns ``Result.UNKNOWN`` -- protocol.md
        Sec 7: "an unknown name is just ``err [#id] 1`` coming back from
        the adapter," so this method owns that outcome, not a silent
        no-op the way ``GET``'s id-less wire shape has to be."""
        if self._config_dispatch.set_field(name, value):
            return protocol.Result.OK
        return protocol.Result.UNKNOWN

    def field_count(self):
        """Number of wire-reachable ``wheel_control`` fields -- backs
        bare ``GET``'s enumeration (protocol.md Sec 6)."""
        return len(_FIELD_NAMES)

    def field_name(self, index):
        """The ``index``'th wire-reachable field name, in
        ``config.WHEEL_CONTROL_FIELDS``'s own declaration order (module
        docstring's field-name-exposure decision)."""
        return _FIELD_NAMES[index]

    # ---- telemetry mode (protocol.md Sec 6) -------------------------------

    def on_tlm(self, mode):
        """Persists ``mode`` (already validated by the handler) as this
        adapter's own single, shared subscription (module docstring --
        no per-transport TLM state). Always returns ``Result.OK``; the
        wire never sees this Result (``TLM`` carries no id)."""
        self._tlm_mode = mode
        return protocol.Result.OK
