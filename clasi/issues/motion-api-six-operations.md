---
status: pending
sprint: 008
---

# Motion API — all six operations, three modes

Stakeholder decision (2026-08-21): implement the **full six-operation
surface** from `radio-robot-lib/docs/design/motion-api.md`, not just
the two primitives.

| method | bounded by | status today |
|---|---|---|
| `wheels_v(left, right, duration)` | time (= lease) | exists (v5 WHEELS path) |
| `wheels_x(left, right, cruise, timeout)` | per-wheel encoder distance | new |
| `move_x(distance, rotation, cruise, timeout)` | displacement + heading | new |
| `move_v(v_x, omega, duration)` | time | new |
| `go_to_r(x, y, speed, arrive, timeout)` | arrival tolerance | new |
| `go_to_w(x, y, speed, arrive, timeout)` | arrival tolerance | new |

## The design in one sentence

Every motion is one or more **constant-ratio wheel segments**, each
bounded by a displacement or a time; the four body/position forms are
coordinate changes over `wheels_x`/`wheels_v` (motion-api.md §2), so
build the two primitives and the segment/profiler machinery first and
compose the rest.

## Load-bearing rules (measured, not chosen — cite motion-api.md)

- `b = trackwidth / rotational_slip` — effective track width, derived
  at boot, never stored. Never bend `trackwidth` to make turns land.
- CCW-positive everywhere; `twist = (right - left) / 2`. Needs a test
  that fails if the wheels are swapped (shipped-and-patched-4× bug).
- `move_x`: |rotation| ≥ 50° → stop, pivot, then travel; < 50° → one
  blended segment. Never replace an in-flight arc with a pivot at
  speed — ramp to rest first. Pivot rate is derived: `2·speed/b`.
- The profiler plans ONE scalar λ; each wheel commands `λ·u_w`, so the
  ratio (and the heading it sweeps) cannot drift during ramps. The
  control block is `{uLeft, uRight (normalized), cruise, stop, limit,
  deadline, id}`.
- `go_to_r` is supervisory: re-solve the arc as the robot proceeds;
  re-issue only on material change (|Δomega| > 0.05 rad/s, |Δs| >
  15 mm, or half the arc covered). Final heading is a consequence,
  not an argument.
- `go_to_w` = pose read + world-to-body + `go_to_r`. Pose source
  pluggable: OTOS when fitted, else midpoint-arc encoder odometry with
  the positionEpoch zero-credit guard and UNWRAPPED heading.
- No unbounded form exists. V-forms: `duration` is the lease. X-forms:
  displacement + required `timeout` backstop.
- `stop()` acts on the current motion (never queues);
  `stop(immediate=True)` zeroes the target now; `estop()` latches and
  is the fault path only. Catch-and-estop-and-re-raise, not a bare
  finally.
- Three modes = same post/tick, differing in who ticks: A fiber,
  B caller-iterated (generator), C blocking with optional callback.
  The loop has exactly one owner; `m.reason` ∈
  {stop, timeout, estop, aborted}.
- Over the wire, tick = drain pushed telemetry, NEVER poll (a poll
  mid-move measured 197.5 mm → 0.3 mm).

## Wire mapping (v6 — depends on [[port-v6-line-protocol-hard-cutover-from-v5]])

Six new verbs, one per operation (`WHEELS_X` … `GO_TO_W`), one adapter
method per verb — motion-api.md §9. Degrees at the API, milliradian
integers on the wire; the conversion lives in the binding, once.
`STOP` gains an optional `now` token before the id.
`MOVE`/`GO_TO`, the v5-shaped discriminated verbs in today's
`motion.py` `RobotDispatch`, retire with v5.

## Relationship to existing code

`motion.py`'s `MoveQueue`/`Move`/`drive()` generator and
`demo_square._move()`'s tuned loop are prior art, not the target shape
(see [[move-engine-forked-between-demo-square-and-tour-run]] — this
work is the natural point to end that fork: one segment engine,
mode-explicit). The kernel is untouched: everything lands above
`diffdrive.drive/step/neutral/estop`.

## Gate

- Offline: unit tests for the kinematic translations (§2's four
  equations), the 50° threshold behavior, ratio normalization,
  wheel-swap sign test, odometry epoch/unwrap tests, mode-ownership
  (double-tick raises). `mpy-cross` compiles everything.
- Hardware (tovez): `move_x(400, 0)` and `move_x(0, 90)` land within
  the tolerances the bench procedures already use; a square tour via
  the new API matches or beats `demo_square`'s current numbers.
