---
status: pending
---

# tovez: left/right wheel response asymmetry, and a stiction floor below ~10% duty

At identical commanded duty, tovez's right wheel turns roughly 1.6x
faster than its left. At low commanded velocity the left wheel does not
break away at all, so the robot drives on one wheel and veers.

## Measured (sprint 006 ticket 009 bench run, wheels on blocks)

Per-wheel isolation, step-driven, 20 cycles each:

| Command | delta left | delta right | vel left | vel right |
| --- | ---: | ---: | ---: | ---: |
| left only, 20% duty | 361 | 0 | 1437.7 | 0.0 |
| right only, 20% duty | 47 | 656 | 0.0 | 2313.1 |
| both, 20% duty | 406 | 756 | 1559.6 | 2252.3 |

Right/left velocity ratio at equal duty: **~1.6x**.

The consequence showed up in the generator drive leg. Commanding
`v=500` counts/s straight (`twist=0`), the velocity PID settled on
**6% duty**, and over 25 cycles:

- `positionLeft`  = **-0.0**  (left wheel never moved)
- `positionRight` = **452.0**

`velocityLeft` read 0.0 for the entire run while `appliedDutyLeft` was
6.0. So 6% clears the right wheel's break-away threshold and does not
clear the left's stiction floor. On the floor rather than on blocks,
that is a hard veer, not a straight line.

Both motors report `connectedLeft`/`connectedRight` True, `stallHalted`
False, `lastError` ok — nothing flags this as a fault.

## Why it matters

The kernel's velocity PID did not integrate up to overcome the left
wheel's floor within 25 cycles (600 ms). Whether that is a gain issue,
a missing minimum-duty floor, or genuine mechanical asymmetry needs
deciding:

- If **mechanical** (gearbox friction, a tight bearing, wheel rub),
  it is a maintenance fix on this chassis and the calibration should
  not paper over it.
- If **control**, a per-wheel minimum-duty floor (a break-away duty
  applied whenever a non-zero velocity is commanded) would fix the
  whole class, and would help any robot with mismatched motors.

Do not resolve it by raising the commanded velocity — that hides the
floor rather than addressing it, and the demo tours run at low speeds
deliberately.

## Suggested first steps

1. Determine break-away duty per wheel empirically: ramp duty from 0
   in 1% steps, step-driven, and record the duty at which each wheel
   first produces encoder movement.
2. Compare against the other robots. If zetuv and vevov show the same
   ratio, it is a design/control issue; if only tovez does, it is that
   chassis.
3. Decide between a per-wheel `min_duty` config field versus PID gain
   changes, and record the reasoning.

Note this is a calibration/control finding, independent of the
generator-mode work in sprint 006 — the generator mechanism itself
verified correct on the same run.
