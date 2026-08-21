---
status: pending
---

# The move engine exists twice, and the two copies have drifted

The tuned move loop lives in two places:

- `src/demo_square.py` `_move()` — the **shipped** engine, what button A
  runs on the robot.
- `tools/tour_run.py` `DEVICE_SCRIPT` — the **bench** engine, an
  embedded MicroPython source string.

Every square-tour number quoted anywhere in this repo (legs +/-1.7 mm,
turns +/-1.1 deg, closure 24 mm) was produced by the **bench** copy.
None of them measure what actually ships.

## The drift, side by side

| | `demo_square._move()` | `tour_run` DEVICE_SCRIPT |
| --- | --- | --- |
| cycle | `time.sleep_ms(32)`, kernel fiber | `diffdrive.step()` at `cyclePeriod()` |
| brake | `drive(0,0,300)` **then** `neutral()` | `neutral()` only |
| `floor` (pure turn) | 0.15 | 0.36 |
| `dmargin` | 35.0 | 30.0 |
| `ymargin` (pure turn) | 12.0 | 14.0 |

The brake row is the one that matters. `tour_run`'s own source comment
says why it does not use `drive(0,0)`:

> neutral(), NOT drive(0,0): with a 100% rail and kp>0 a commanded zero
> is an ACTIVE hold that reverses past the target — measured a
> consistent -4.2 deg pull-back on turns. neutral() stages a true stop.

`demo_square._move()` still issues exactly that `drive(0.0, 0.0, 300)`,
holds it for 250 ms, and only then calls `neutral()`. If the bench
measurement generalises, the shipped engine pulls back ~4.2 deg on every
turn — four turns per tour.

## Why they diverged, and why it is not a trivial merge

They are in **different kernel modes**. `demo_square` runs the fiber
(`start()`, sleep-paced); `tour_run` is step-driven (`step()`, no
fiber). The constants differ *because* the modes differ, so this cannot
be fixed by deleting one copy and calling the other — the timing
substrate is not the same.

`start()` is also irreversible (the kernel has no `stop()`), and the
mode latches at first use, so a module cannot simply offer both.

## Proposed work

1. **Measure the shipped engine first.** Run `demo_square.run()` on a
   robot and compare per-move overshoot against the bench engine's
   numbers on the same chassis, same session. The -4.2 deg claim is
   inherited from a comment, not re-verified against the current
   tuning — do not act on it before reproducing it.
2. If it reproduces, port the `neutral()` brake into `_move()` and
   re-measure. That is a one-line change to tuned motion code, so it
   needs its own bench pass, not a code review.
3. Decide the end state: either the shipped engine becomes step-driven
   too (one engine, one set of constants), or the fork is made explicit
   — a comment in each copy naming the other and stating that the
   constants are mode-specific and must not be cross-copied.

Option 3's "explicit fork" is a legitimate end state. Two engines for
two kernel modes is defensible; two engines that *look* like one and
silently disagree is not.

## Related

[[intermittent-short-leg-in-square-tour]] — found while adding
termination-reason logging to `_move()`, which `tour_run`'s copy already
had (it prints `STALL`/`TIMEOUT`) and the shipped copy did not. That
asymmetry is what exposed the fork.
