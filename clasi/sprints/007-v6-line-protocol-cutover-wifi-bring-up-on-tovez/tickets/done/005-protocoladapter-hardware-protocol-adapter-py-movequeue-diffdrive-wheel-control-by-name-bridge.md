---
id: '005'
title: 'ProtocolAdapter (hardware/protocol_adapter.py): MoveQueue/diffdrive + wheel_control-by-name
  bridge'
status: done
use-cases:
- SUC-001
- SUC-003
depends-on:
- '004'
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# ProtocolAdapter (hardware/protocol_adapter.py): MoveQueue/diffdrive + wheel_control-by-name bridge

## Description

Build the real `Adapter` (`protocol.md` §4) that `src/core/
protocol.py` dispatches to once wired in: `src/hardware/
protocol_adapter.py`'s `ProtocolAdapter`, backed by the same
`motion.MoveQueue`/`config.ConfigDispatch` objects
`motion.RobotDispatch` wraps today (that class retires in ticket 006,
after this one exists to replace it).

**`onWheels(left, right, duration, id)` — the one real behavior
change this sprint makes** (see sprint.md Design Rationale): v5's
`RobotDispatch._handle_wheels()` calls `diffdrive.driveDuty(duty_left,
duty_right, lease_ms)` directly — open-loop duty, no geometry. v6's
`WHEELS` is `[mm/s]`, scaled by `countsPerLength` into
`DifferentialDrive::drive(velocity, twist, lease)` (`protocol.md`
§5): `velocity = (left + right) / 2`, `twist = (right - left) / 2`,
both in counts/s after scaling by `countsPerLength` (source:
`data/tovez.json`'s `wheels.ticks_per_mm`, read once at construction
— it is geometry, not a tunable, so it is a constructor argument, not
reachable through `GET`/`SET`, matching `protocol.md` §5 point 2).
Enforce the 5000 ms lease ceiling here (the handler holds no bounds
table — `protocol.md` §9.1 — so this is the adapter's job,
`kRange`/`ERR_RANGE` on violation).

**`onStop(id)`** → `self._queue.diffdrive` neutral (mirrors
`_handle_stop`'s `self._queue.stop()`); always `kOk` (matches
`protocol.md` §5.1: `neutral()` has no refusal path). **`onEstop()`**
→ `self._queue.estop()` latch; returns nothing (void, per
`protocol.md` §4 — `ESTOP` is never acked at the wire level either,
so there is no `Result` to return).

**`onGet(name, out)` / `onSet(name, value, id)`** — resolve `name`
against the surviving `wheel_control` dict/`WHEEL_CONTROL_FIELDS`
table from `config.ConfigDispatch` (its binary index-keyed dispatch
retires in ticket 006; the underlying dict and name table survive —
see sprint.md Design Rationale). Add name-keyed accessor methods to
`ConfigDispatch` (e.g. `get_field(name)`/`set_field(name, value)`) if
none exist yet, rather than reaching into its private `_wheel_control`
dict directly from the adapter. Unknown name → `onGet` returns
`False` (silent, no reply, per `protocol.md` §6); `onSet` on an
unknown name → the handler's own `ERR_UNKNOWN` path (confirm which
side owns this — `protocol.md` §7 says "an unknown name is just `err
[#id] 1` coming back from the adapter", so `onSet` itself should
return `kUnknown` for an unrecognized name, not silently no-op).

**`identity()`/`now()`/`status()`** — small, mostly-plumbing: name/
serial/version for `HELLO`/`ID`/`VER`; a millisecond clock for
`PING`'s `pong <now>`; a `StatusFields`-shaped object/dict for
`STATUS` (ready/active/connL/connR/otos/wedge/flags/tlm) — this
sprint has no OTOS/line-sensor wiring in scope, so `otos`/`wedge` may
be constant placeholders (`0`) with a comment noting they're not yet
backed by real sensors, not a silent omission.

**`onTlm(mode)`** — persists the mode on the adapter (one value,
shared across every handler instance, per sprint.md's Design
Rationale — there is one robot, not one TLM subscription per
transport).

Exact `GET`/`SET` field-name exposure (which `wheel_control` keys are
wire-reachable) is this ticket's own implementation decision, per
`protocol.md` §7 ("which names are valid is entirely the adapter's
business") — start from `WHEEL_CONTROL_FIELDS`'s existing names;
record the final list in this ticket's completion notes.

## Acceptance Criteria

- [x] `src/hardware/protocol_adapter.py` exists with `ProtocolAdapter`
      implementing `identity`/`now`/`status`/`onWheels`/`onStop`/
      `onEstop`/`onGet`/`onSet`/`onTlm`.
- [x] `onWheels` scales by `countsPerLength` and calls
      `MoveQueue.diffdrive.drive(velocity, twist, lease)` — a test
      asserts the scaled velocity/twist values reach `drive()`, not
      raw duty, and that swapping which argument is "left" would flip
      the test (the wheel-swap sign-test convention this repo's other
      motion code already uses).
- [x] 5000 ms lease ceiling enforced in the adapter (`kRange` above
      it), not the handler.
- [x] `onStop`/`onEstop` call `MoveQueue.diffdrive`'s neutral/estop
      paths; `onEstop` returns nothing.
- [x] `config.ConfigDispatch` gains name-keyed `get_field`/`set_field`
      (or equivalent) accessors; its old binary
      `handle_command`/`_handle_set_field`/`_handle_config`/
      `_handle_get_config`/`build_cfg_reply` are left in place for now
      (they retire in ticket 006, which also deletes the `wire.py`
      dependency they need) — this ticket only adds the new
      accessors, it does not yet delete the old ones.
- [x] `onGet`/`onSet` resolve names through the new accessors;
      unknown-name behavior matches `protocol.md` §7 exactly (`onGet`
      silent-false, `onSet` returns `kUnknown`).
- [x] Offline-tested against a fake `diffdrive`/`config` stub
      (mirrors the existing `comms.py`/`motion.py` interface-seam
      convention), covering every method above.
- [x] `py_compile`/`mpy-cross` clean.

## Completion Notes

- **GET/SET field-name list** (protocol.md §7: "which names are valid
  is entirely the adapter's business"): the 15 `wheel_control` JSON
  field names `config.WHEEL_CONTROL_FIELDS` already declares, exposed
  VERBATIM (no prefix) and in that same declaration order for bare
  `GET`'s enumeration — `v_min`, `bias_max`, `tau_adapt`, `a_steady`,
  `deficit_threshold`, `deficit_window`, `pid_kp`, `pid_ki`,
  `pid_i_max`, `pid_kaff`, `pid_max`, `pos_err_max`, `stall_speed`,
  `stall_demand`, `stall_window`. Chosen over the C++ archetype's own
  `"wheel_control.v_min"`-prefixed wire names because this port has no
  second config group that could ever collide on a bare `v_min`, and
  the un-prefixed name is what `data/<robot>.json` and `config.py`
  already call the same field everywhere else in this codebase.
  `field_count()`/`field_name(index)` hold this ordered list directly
  (built once from `config.WHEEL_CONTROL_FIELDS` at import time);
  resolution itself is not duplicated there — `on_get()`/`on_set()`
  delegate to `ConfigDispatch.get_field()`/`set_field()`, the one place
  that owns which of the 15 names are valid.
- **Ambiguity resolved — `onStop` vs `onEstop`'s call target**: the
  ticket description named `self._queue.diffdrive` neutral for
  `onStop` but `self._queue.estop()` for `onEstop` — an asymmetry (one
  bypasses `MoveQueue`'s own wrapper, the other doesn't). Read
  literally and kept as written: `on_stop()` calls
  `move_queue.diffdrive.neutral()` directly (never touches
  `MoveQueue`'s own pending-list, which nothing in the v6 path ever
  populates anyway); `on_estop()` calls `move_queue.estop()` (clears
  the pending list AND latches the kernel `estop()` in one call). Both
  satisfy the Acceptance Criteria's own looser phrasing ("call
  `MoveQueue.diffdrive`'s neutral/estop paths") since `MoveQueue.
  estop()` reaches `diffdrive.estop()` internally either way.
- **Status-string → `Result` mapping**: `diffdrive.drive()` returns a
  status STRING (`native/moddiffdrive.cpp`'s `statusToStr()`), not an
  enum. Mapped via a small table (`_STATUS_TO_RESULT`) mirroring the
  C++ archetype's `statusToResult()`: `"ok"` → `OK`;
  `"refused_unconfigured"`/`"refused_not_begun"`/`"refused_estopped"` →
  `NOT_CONFIGURED` (this port's `Result` has no dedicated "not ready"
  code, so all three pre-ready refusals collapse the same way the
  archetype's own switch does); `"refused_non_finite"` → `BADARG`;
  `"refused_lease_ceiling"` (the native binding's own, separately
  motivated 5000 ms guard, `kBindingLeaseMaxMs`) → `RANGE` defensively;
  anything else → `UNKNOWN`, matching `protocol.py`'s own
  "unrecognized value falls to UNKNOWN" convention.
- **`on_tlm`'s `"NOW"` mode**: the C++ archetype special-cases `NOW` as
  a non-persisted one-shot read; that nuance lives only in
  `DiffDriveAdapter`'s own comment, not in `protocol.md` itself, and
  neither this ticket's acceptance criteria nor its test list calls for
  it — this port persists every mode the handler hands over, including
  `NOW`, deferring any one-shot-without-changing-subscription behavior
  to whichever "calling application" (ticket 006's `comms.py`) needs
  it later.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/`
- **New tests to write**: fake-diffdrive-stub tests for every adapter
  method, especially the velocity/twist scaling and wheel-swap sign
  test; lease-ceiling rejection test; unknown-name GET/SET tests;
  TLM-mode persistence test (shared across two adapter-facing handler
  instances).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Keep `ProtocolAdapter` a thin translation layer — no
new business logic beyond unit conversion and the lease-ceiling
check; every actual motion/config effect goes through the existing
`MoveQueue`/`ConfigDispatch` objects, unchanged in their own
behavior. Add the name-keyed accessors to `ConfigDispatch` as a small,
additive change (do not yet touch its binary dispatch methods — that
deletion is ticket 006's job, kept separate so this ticket's diff
stays reviewable).

**Files to create**:
- `src/hardware/protocol_adapter.py` — `ProtocolAdapter`.

**Files to modify**:
- `src/core/config.py` — add name-keyed `get_field`/`set_field`
  accessors to `ConfigDispatch` (additive; binary dispatch untouched
  here).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket (the field-name exposure
decision is recorded in this ticket's own completion notes, not a
project doc).
