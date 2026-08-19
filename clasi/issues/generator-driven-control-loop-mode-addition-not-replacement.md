---
status: pending
---

# Generator-driven control loop mode (addition, not replacement)

## Description

Add a second, stakeholder-approved way to execute the wheel-kernel
control loop: move commands as Python generators, where each `next()`
runs one kernel cycle (`step()`) and the generator owns the 24 ms
pacing. The existing background mode (kernel on a CODAL fiber) stays
and remains the explicit-`start()` path; if `start()` was never
called, the generator mode drives the kernel instead. The two modes
are mutually exclusive per boot (`start()` is irreversible — no
`stop()` exists and `run()` never returns).

Stakeholder decisions already taken:

- Approved as an **addition**, not a replacement.
- Ticket 004 (moddiffdrive native module, M1) stays frozen — the
  binding additions land as a small follow-on ticket after 004
  closes, before ticket 007 needs them.
- This resolves spec §10 open item 4 (teaching-framework loop
  ownership, "decide before M5") at the **mechanism** level: neither
  `on_tick()` nor raw student `while True:` — framework-owned cadence
  inside move generators, student-owned loop body. Which mode is the
  *primary* teaching posture is deferred until M1 hardware evidence
  (safety triple plus a generator-mode bench leg); ticket 007 builds
  both surfaces.

## Cause

The background execution story is cooperative-only: the kernel fiber
advances only when Python reaches `microbit_hal_idle()`, so 24 ms is
a target, not a guarantee. `docs/nezha-upy-review.md` §2 (spec §7.2)
shows the realistic student idiom `while True: p = radio.receive()`
starves it **routinely**, and the only mitigation in that mode is the
zero-only starvation watchdog. In generator mode Python and the
kernel share one thread, so this starvation cannot occur while a move
is being iterated.

Feasibility is already settled by the vendored kernel's own contract
(no `vendor/` change needed):

- `vendor/differential_drive.h:18-20` — port contract: "FiberLauncher
  … OPTIONAL: a host that owns its own loop never calls start() and
  drives step() directly instead."
- `vendor/differential_drive.h:344-351` — `step()` is public: one
  full kernel cycle inline in the caller's context. The fiber body
  `run()` is just `step()` plus absolute-deadline pacing
  (`vendor/differential_drive.cpp:354-378`).
- `vendor/differential_drive.h:107-110` — command readiness is
  granted by `begin()`, **not** `start()`, explicitly so a host can
  command and `step()` without ever launching the fiber. The whole
  `drive/driveDuty/neutral/estop` surface already works step-driven.
- `dt` is measured per cycle (`vendor/differential_drive.cpp:522-530`)
  and pacing is absolute-deadline, so variable re-entry cadence
  "costs nothing in the control law" (review §3). Jitter from student
  code between `next()` calls degrades gracefully and is visible via
  `cycleOverrunCount_`.
- The heap-corruption landmine is about **fiber switches** from
  VM/GC hooks; generator mode does no fiber switch at all — `step()`
  is called from a normal Python call frame at main context.
  KeyboardInterrupt is safe there (live nlr context), dissolving the
  `allowRaise` two-context contortion the old modrobot spike needed.

Known accepted cost: `step()` blocks ~9–10 ms per call (two 4 ms
encoder settles, `vendor/differential_drive.cpp:591-597`), so each
`next()` costs ≥10 ms, paced to the 24 ms period — fine for a
cooperative teaching mode. The settle sleeps run via
`mp_hal_delay_ms` in this mode, so the comms pump is serviced during
them.

## Proposed fix

**1. Native binding additions** (new follow-on ticket, after 004 and
before 007; ticket 004 itself is not modified):

- Bind `diffdrive.step()` alongside the 004 surface.
- Mode latch: first use of `start()` OR `step()` latches the mode;
  the other entry then raises. Honors the vendored FiberLauncher
  contract (`vendor/differential_drive.h:86-89`): the injected
  launcher checks the latch and fails loudly.
- Mode-aware Sleeper: kernel-fiber caller → CODAL `fiber_sleep`;
  step-driven caller (main context) → `mp_hal_delay_ms` (reaches
  `microbit_hal_idle()`). One implementation with a flag set in
  `fiberEntry`.
- Reentrancy guard on `step()`: raise if a step is already in flight
  (a scheduled callback during the settle delay could otherwise
  re-enter). Prior art: `robot_v5_service()`'s `inProgress` guard,
  `reference/modrobot/modrobot.cpp:1478-1487`.
- Expose the frozen `cyclePeriod` (read-only) so Python paces
  correctly.
- The zero-only VM-hook starvation watchdog stays mode-independent:
  it keys off kernel cycle progress with wheels commanded, which
  covers a student who commands motion then stops iterating the
  generator (>250 ms stall → raw zero write). Same safety net, both
  modes.

**2. Python motion layer** (`src/motion.py`, ticket 007 / M5 — amend
its scope; depends on the new binding ticket). Move commands become
generators; illustrative shape:

```python
def drive(v, twist, duration_ms):
    end = ticks_add(ticks_ms(), duration_ms)
    cycle = ticks_ms()
    try:
        while ticks_diff(end, ticks_ms()) > 0:
            wait = ticks_diff(cycle, ticks_ms())
            if wait > 0: sleep_ms(wait)          # generator owns pacing
            cycle = ticks_add(cycle, PERIOD_MS)   # absolute deadlines,
            diffdrive.drive(v, twist, LEASE_MS)   # mirroring run()'s rule
            diffdrive.step()
            yield diffdrive.output()              # student reads progress
    finally:
        diffdrive.neutral()
        diffdrive.step()   # one landing cycle so the staged zero reaches the bus
```

- Student loop body runs between `next()` calls (~14 ms budget per
  cycle; overrunning just lands the step late — measured `dt`
  absorbs it).
- `break` out of the `for` loop → GeneratorExit → `finally` → clean
  stop. Teachable invariant: **wheels move only while you keep
  iterating.**
- Lease renewed each cycle with a short lease (~3× period), so an
  abandoned generator decays to neutral on the next step or, if
  steps stop entirely, the watchdog zeroes duty.
- Generators are plain-CPython testable against a fake `diffdrive`
  (step/output stub) — the same interface-seam pattern ticket 005
  uses for `comms.py`, so the M5 gate for motion logic runs offline.

**3. Ticket 009 amendments**: the student-facing contract note
documents both modes ("background mode: wheel control requires
reaching idle"; "generator mode: wheels move while you iterate"), and
the stakeholder bench procedure gains a generator-mode hardware leg
(step-driven drive with encoder-sign check; break-mid-move stops;
abandon-generator watchdog zero). The primary-vs-alternative
positioning call is made here, from the M1 evidence.

**4. Spec update**: record against open item 4 in
`docs/design/specification.md` §10 — mechanism decided, positioning
deferred to M1 evidence.

Explicitly out of scope:

- Any `vendor/` edit (the sync-diff-clean gate stands). The `step()`
  re-entrant/SWI restructure remains a radio-robot decision gated on
  M1 hardware evidence — this mode neither needs it nor forecloses
  it.
- No new yield/hook points (review §1 closed that permanently).
- No change to fiber-mode behavior; it remains the
  explicit-`start()` path.

## Verification

- Offline (this repo): `./build.sh --clean --with-diffdrive` links
  with `step` in the method table; `git diff --exit-code -- vendor/`
  clean; source review of latch/guard/sleeper in the style of ticket
  004's criteria; CPython unit tests for motion generators against
  the fake binding (pacing, lease renewal, `finally` stop, break
  semantics).
- Hardware (stakeholder, ticket 009): generator-mode drive leg —
  encoder signs correct, `cycleOverrunCount_` sane while iterating,
  break-mid-move stops within one cycle, abandoned generator zeroed
  by the watchdog within ~250 ms.

## Related

- `vendor/differential_drive.h` / `vendor/differential_drive.cpp` —
  the kernel's step-driven-host contract (never edited here).
- `docs/nezha-upy-review.md` §§1–3 and
  `docs/design/specification.md` §7, §10 open item 4.
- Sprint 001 tickets: 004 (moddiffdrive native module — frozen),
  007 (motion.py — scope amendment), 009 (bench procedures and
  student-facing API contract — amendment).
- `reference/modrobot/modrobot.cpp` — prior art for reentrancy guard
  and the two-context `allowRaise` problem this mode dissolves.
