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

---

## Update — re-measured on healthy power (2026-08-20)

The original table was taken while the Nezha driver board was in the
wedged state that later required a power cycle (I2C 0x10 not ACKing —
it mimics a dead battery). **The 1.6x figure is not trustworthy.**

`tools/plant_id.py` (new — duty sweep with alternating direction, so a
chassis lean cannot bias one direction) re-measured on healthy power:

| | left | right | mean |
| --- | ---: | ---: | ---: |
| `full_duty_velocity` [counts/s] | 9554 | 11875 | **10715** |

Ratio **1.24x**, not 1.6x. Real, but a quarter, not two-thirds.

### The control branch is now taken, and it works

`src/demo_square.py` carries per-wheel feedforward gains derived
directly from the above — `wheel_gain_left` 0.892, `wheel_gain_right`
1.108 — plus `v_min = 20 mm/s`, `pid_kp` 0.6 (was 0.0, i.e. pure-I) and
a measured `full_duty_velocity` that had been 3.3x under-scaled. The
tour result: legs -1.7 to -0.1 mm against 500 mm, turns +0.12 to
+1.13 deg. The veer described above does not occur.

### What is left of this issue

Two things, and they are narrower than the original scope:

1. **Break-away duty per wheel was never actually measured** (original
   step 1). `plant_id.py` sweeps duty but reports a full-duty velocity
   fit; it does not report the duty at which each wheel first moves.
   That number is also the prerequisite for
   [[crawlpulse-sub-breakaway-dithering]] — measure it once, use it
   twice.
2. **`applySpeedFloor` rescales BOTH wheels** up to `vMin`,
   proportionally. So the per-wheel floor this issue asks for cannot
   simply be added host-side: below `vMin` the kernel overrides. And
   `applySpeedFloor` lives in the kernel, which is SYNCED from
   radio-robot and never edited here — a change there is a radio-robot
   change, gated by its own tests, then re-synced.

Original step 2 (compare zetuv and vevov) is still open and still the
right way to tell "this chassis" from "this design".

### Also unresolved, found while measuring

`correctedCommand` indexes `wheelGain[wheel][accel/decel]` using
`|desired|` — the SIGN is discarded, so forward and reverse share one
gain. The alternating-direction sweep in `plant_id.py` exists precisely
because of that, and it averages the asymmetry away rather than
characterizing it. If forward and reverse differ materially, the current
single-gain-per-wheel model cannot express it.
