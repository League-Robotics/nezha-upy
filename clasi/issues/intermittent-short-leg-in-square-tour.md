---
status: pending
---

# Intermittent: one square-tour leg terminated ~408 mm short, unexplained

In one of three consecutive square tours, a single 500 mm leg ended
roughly **408 mm short** of target. The other two tours, and the other
three legs of that same tour, were normal. Recorded in commit `c0d9ad4`.

It has not reproduced since — the tours run at the time of
[[deploy-user-programs-to-the-filesystem-freeze-only-firmware]] gave
legs of -1.7 to -0.1 mm against 500 mm across all four legs.

## Why it is still worth a ticket

A single leg terminating early, while its siblings are millimetre-
accurate, is not a tuning symptom. It looks like an early exit from the
move loop, and the candidate causes are all things that would be
invisible in a normal run:

- ~~**Stall detector.**~~ **Ruled out.** `stall_demand` was set to
  `0.0` (detector OFF) in `c52fd99` at 17:57, and `c0d9ad4` is 19:02 the
  same day — verified by reading `src/demo_square.py` AT `c0d9ad4`,
  where line 446 already reads `"stall_demand": 0.0`. The detector was
  not armed when the short leg happened. This was the leading
  hypothesis; it is dead.
- **Encoder glitch.** `tools/tour_run.py` already rejects samples above
  40 mm/sample host-side, because glitches were observed. A glitch that
  lands *inside* the on-device distance accumulator would terminate the
  move early and would not be filtered — the host filter is downstream
  of the decision.
- **A dropped/duplicated lease reissue** in the rolling 500 ms window.

## First steps

With the stall detector ruled out, the cheap explanation is gone and
this needs instrumentation before it needs theory.

1. **Log the on-device termination REASON per move** (target reached /
   lease timeout / other), not just the distance. Right now a short leg
   and a completed leg are indistinguishable in the telemetry, which is
   why a 408 mm miss produced no diagnostic at all. This is the one step
   that must happen first — everything else is guessing until it does.
2. Log the raw on-device distance accumulator alongside it, so an
   encoder glitch that lands inside the termination decision is
   visible. The existing 40 mm/sample rejection in `tools/tour_run.py`
   is host-side and downstream of that decision — it cleans the plot,
   not the control path.
3. Run the tour N times unattended and count. A one-in-twelve-legs event
   needs repetition, not a single careful run.

## Provenance

Deferred out of [[deploy-user-programs-to-the-filesystem-freeze-only-firmware]].
