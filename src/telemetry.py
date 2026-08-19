"""telemetry -- the full 22-field TLM frame assembly, M5 (PLAN.md /
``docs/design/specification.md`` Sec 6/7.2/7.5, UC-012).

``src/comms.py``'s ``TelemetryPolicy`` (ticket 005) already owns the ack
ring and the emit-policy arithmetic (WHEN a primary frame is due) but
deliberately does NOT build a real frame -- its own docstring: "does
NOT build a real 22-field TLM wire frame (that is ticket 007's
``src/telemetry.py``)". This module is that frame assembler: given the
current sensor/kernel state, it produces the 22 named fields as a plain
dict, ready for a boot-level ``emit_callback(now, acks)`` (the callback
``comms.Comms(..., emit_callback=...)`` accepts) to hand to
``TelemetryFrameBuilder.build()``.

Field derivation (22 fields -- see this module's own inline enumeration
in ``TelemetryFrameBuilder.build()`` for the authoritative list). Source
of truth: radio-robot-elite's CURRENT ``src/firm/messages/telemetry.h``
``msg::Telemetry`` struct (21 top-level fields when ``acks_``/
``acks_count`` are counted as ONE logical field, matching how a wire
client reads them together) plus this port's own two M1 additions (spec
Sec 7.2/7.5): ``cycle_overrun_count`` and ``watchdog_fault``. NOTE this
oracle has evolved past the "22 fields" plain description PLAN.md/spec
give -- no document in this repo enumerates the 22 names directly, so
this module's field list is this ticket's own grounded reconstruction,
documented here rather than asserted without a paper trail:

  - ``duty_per_speed_left/right``, ``bias_left/right``, ``pid_left/
    right`` exist in ``msg::Telemetry`` (byte-for-byte wire-compatible
    shape, spec Sec 2 "byte-for-byte compatible") but have NO source in
    this port's kernel any more than they do in the CURRENT
    radio-robot-elite kernel -- that oracle's own ``telemetry.cpp``
    already documents holding them at zero for exactly this reason
    ("EXPLORATORY-KERNEL REWRITE ... held at zero here"). This port
    follows the SAME precedent: always zero, kept in the frame shape.
  - ``color`` is always 0 -- no color driver exists this sprint (M7,
    explicitly deferred per sprint.md's Out of Scope).
  - ``watchdog_fault`` is exposed BOTH as its own top-level field (this
    ticket's acceptance criterion: "the watchdog fault bit ... [is]
    present and populated") AND as a bit inside ``flags`` (spec Sec 7.2's
    literal wording: "fault bit in telemetry") -- one underlying value,
    surfaced two ways so either reading style finds it.

MicroPython-only modules are import-guarded so this module imports and
runs unmodified under CPython (this ticket's own offline gate)."""

__all__ = [
    "FLAG_ACTIVE",
    "FLAG_OTOS_PRESENT",
    "FLAG_OTOS_CONNECTED",
    "FLAG_CONN_LEFT",
    "FLAG_CONN_RIGHT",
    "FLAG_ESTOPPED",
    "FLAG_LEASE_EXPIRED",
    "FLAG_STALL_HALTED",
    "FLAG_LINE_PRESENT",
    "FLAG_WATCHDOG_FAULT",
    "SEQ_MODULUS",
    "TelemetryState",
    "TelemetryFrameBuilder",
    "pack_line_channels",
]

FLAG_ACTIVE = 1 << 0
FLAG_OTOS_PRESENT = 1 << 1
FLAG_OTOS_CONNECTED = 1 << 2
FLAG_CONN_LEFT = 1 << 3
FLAG_CONN_RIGHT = 1 << 4
FLAG_ESTOPPED = 1 << 5
FLAG_LEASE_EXPIRED = 1 << 6
FLAG_STALL_HALTED = 1 << 7
FLAG_LINE_PRESENT = 1 << 8
FLAG_WATCHDOG_FAULT = 1 << 9

# msg::Telemetry.seq wraps mod 128 -- matches Core::Telemetry::
# emitPrimary()'s own `seq_ = (seq_ + 1) % 128u`.
SEQ_MODULUS = 128


class TelemetryState:
    """Plain, mutable snapshot of everything a frame needs -- the
    "synthetic sensor/kernel-state fixture" this ticket's acceptance
    criteria ask ``tests/test_telemetry.py`` to assert against. Every
    field has a safe zero/False default so a caller only needs to set
    what a given test scenario actually exercises.

    ``diffdrive_output``: the dict ``diffdrive.output()`` returns (or a
    fake with the same keys under CPython) -- see
    ``native/moddiffdrive.cpp``'s ``diffdrive_output_fn`` for the full
    key set this reads from (``positionLeft``/``positionRight``/
    ``velocityLeft``/``velocityRight``/``velocity``/``twist``/
    ``cycleBusy``/``cyclePeriodMeasured``/``cycleOverrunCount``/
    ``ready``/``estopped``/``leaseExpired``/``stallHalted``/
    ``connectedLeft``/``connectedRight``/``watchdogFault``). ``None``
    (the default) reads as an all-zeros/all-False kernel snapshot --
    matches this port's own "not configured yet" boot state.
    """

    def __init__(self):
        self.mode = 0
        self.diffdrive_output = None
        self.otos_reading = None  # otos.OtosReading | None
        self.otos_present = False
        self.line_reading = None  # line.LineReading | None
        self.line_present = False
        self.pose_x = 0
        self.pose_y = 0
        self.pose_heading = 0
        self.active = False


def pack_line_channels(raw):
    """Pack up to 4 one-byte channel readings (``list[int]``, 0-255
    each, left to right -- see ``line.py``'s own ordering note) into one
    uint32, MSB-first (channel 0 in the highest byte). Missing channels
    (a shorter list, or ``None``) pack as 0."""
    channels = list(raw) if raw else []
    while len(channels) < 4:
        channels.append(0)
    value = 0
    for channel_value in channels[:4]:
        value = (value << 8) | (int(channel_value) & 0xFF)
    return value


_DIFFDRIVE_OUTPUT_DEFAULTS = {
    "positionLeft": 0.0,
    "positionRight": 0.0,
    "velocityLeft": 0.0,
    "velocityRight": 0.0,
    "velocity": 0.0,
    "twist": 0.0,
    "cycleBusy": 0,
    "cyclePeriodMeasured": 0,
    "cycleOverrunCount": 0,
    "ready": False,
    "estopped": False,
    "leaseExpired": False,
    "stallHalted": False,
    "connectedLeft": False,
    "connectedRight": False,
    "watchdogFault": False,
}


class TelemetryFrameBuilder:
    """Stateful (owns the mod-128 ``seq`` counter, mirroring
    ``Core::Telemetry``'s own ``seq_``) frame assembler. One instance per
    boot -- construct once, call ``build()`` every time
    ``comms.py``'s ``emit_callback(now, acks)`` fires."""

    def __init__(self):
        self._seq = 0

    def build(self, state, acks, now):
        """Assemble and return the 22-field frame as a plain dict.

        ``state``: a ``TelemetryState`` (or any duck-typed object with
        the same attributes). ``acks``: the list of packed ack ints
        ``TelemetryPolicy``'s ``emit_callback`` hands over (oldest
        first, ``corr_id << 4 | err_code``). ``now``: int [ms].
        """
        out = dict(_DIFFDRIVE_OUTPUT_DEFAULTS)
        if state.diffdrive_output:
            out.update(state.diffdrive_output)

        seq = self._seq
        self._seq = (self._seq + 1) % SEQ_MODULUS

        flags = 0
        if state.active:
            flags |= FLAG_ACTIVE
        if state.otos_present:
            flags |= FLAG_OTOS_PRESENT
        if state.otos_reading is not None:
            flags |= FLAG_OTOS_CONNECTED
        if out["connectedLeft"]:
            flags |= FLAG_CONN_LEFT
        if out["connectedRight"]:
            flags |= FLAG_CONN_RIGHT
        if out["estopped"]:
            flags |= FLAG_ESTOPPED
        if out["leaseExpired"]:
            flags |= FLAG_LEASE_EXPIRED
        if out["stallHalted"]:
            flags |= FLAG_STALL_HALTED
        if state.line_present:
            flags |= FLAG_LINE_PRESENT
        watchdog_fault = bool(out["watchdogFault"])
        if watchdog_fault:
            flags |= FLAG_WATCHDOG_FAULT

        otos_reading = state.otos_reading
        otos_field = {
            "x": otos_reading.x if otos_reading else 0.0,
            "y": otos_reading.y if otos_reading else 0.0,
            "heading": otos_reading.heading if otos_reading else 0.0,
            "v_x": otos_reading.v_x if otos_reading else 0.0,
            "v_y": otos_reading.v_y if otos_reading else 0.0,
            "omega": otos_reading.omega if otos_reading else 0.0,
            "age": 0,
        }

        line_reading = state.line_reading
        line_value = pack_line_channels(line_reading.raw if line_reading else None)

        return {
            "now": now,
            "seq": seq,
            "mode": state.mode,
            "flags": flags,
            "enc_left": {
                "position": out["positionLeft"],
                "velocity": out["velocityLeft"],
            },
            "enc_right": {
                "position": out["positionRight"],
                "velocity": out["velocityRight"],
            },
            "otos": otos_field,
            "pose": {
                "x": state.pose_x,
                "y": state.pose_y,
                "heading": state.pose_heading,
            },
            "twist": {
                "v_x": out["velocity"],
                "omega": out["twist"],
            },
            "line": line_value,
            "color": 0,
            "acks": list(acks) if acks else [],
            "cycle_busy": out["cycleBusy"],
            "cycle_period": out["cyclePeriodMeasured"],
            "duty_per_speed_left": 0.0,
            "duty_per_speed_right": 0.0,
            "bias_left": 0.0,
            "bias_right": 0.0,
            "pid_left": 0.0,
            "pid_right": 0.0,
            "cycle_overrun_count": out["cycleOverrunCount"],
            "watchdog_fault": watchdog_fault,
        }
