---
status: pending
---

# Adopt `crawlPulse` sub-breakaway dithering from pxt-nezha-diffdrive

`pxt-nezha-diffdrive` carries a `crawlPulse` mechanism this port never
adopted, and it is the most likely remaining lever on turn scatter.

## What it does there

When the velocity controller's demand falls **below a wheel's break-away
duty**, holding that duty produces no motion at all — the wheel just
sits in stiction while the integrator winds. `crawlPulse` instead
*dithers*: it alternates between a duty above break-away and zero, at a
duty ratio that averages out to the demanded (sub-break-away) speed. The
wheel creeps in small steps rather than not moving and then lurching.

## Why it matters here

Two places in this port hit exactly that regime:

1. **End-of-move taper.** `_move()`'s taper deliberately winds the
   demand down as it approaches the target. Below break-away the wheel
   stops responding, so the last few mm are governed by whatever the
   wheel does when the taper releases it.
2. **Pure turns.** They run at the lowest commanded velocities of any
   move, and residual turn error is the larger of the two remaining
   error terms (+0.12 to +1.13 deg vs legs at -1.7 to -0.1 mm).

## The complication: `applySpeedFloor`

The kernel's `applySpeedFloor` rescales **BOTH** wheels up to `vMin`,
proportionally. That means a taper crawl below `vMin` does not actually
slow the robot down — it gets rescaled back up. Any `crawlPulse` work
has to reckon with that first: either the floor has to become per-wheel
and pulse-aware, or `crawlPulse` has to live below the floor's
intervention point.

Since the floor lives in the kernel, and `vendor/` is SYNCED from
radio-robot and never edited here, a kernel-side change means doing it
in radio-robot behind its own tests and re-syncing.

## First steps

1. Measure break-away duty per wheel (this is also step 1 of
   [[tovez-left-right-wheel-response-asymmetry]] — do it once, use it
   for both).
2. Decide whether `crawlPulse` belongs kernel-side (with the floor) or
   host-side in `_move()`'s taper.
3. Re-run the square tour and compare turn scatter specifically; leg
   accuracy is already at +/-1.7 mm and is not the thing to optimize.

## Provenance

Deferred out of [[deploy-user-programs-to-the-filesystem-freeze-only-firmware]].
Source repo: `/Volumes/Proj/proj/RobotProjects/pxt-nezha-diffdrive`.
