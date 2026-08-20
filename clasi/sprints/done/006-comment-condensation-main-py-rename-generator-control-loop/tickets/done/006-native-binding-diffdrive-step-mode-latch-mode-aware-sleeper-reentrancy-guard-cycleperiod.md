---
id: '006'
title: 'Native binding: diffdrive.step(), mode latch, mode-aware Sleeper, reentrancy
  guard, cyclePeriod'
status: done
use-cases:
- SUC-001
- SUC-002
depends-on:
- '004'
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Native binding: diffdrive.step(), mode latch, mode-aware Sleeper, reentrancy guard, cyclePeriod

## Description

Add the native binding surface the step-driven control-loop mode
needs, alongside the existing background/fiber-mode surface — an
**addition**, not a replacement. Ticket 004 (native/ comment
condensation) lands first so this ticket edits already-condensed
files. No `vendor/` change (the vendored kernel's own
`FiberLauncher` contract already sanctions a step-driven host —
`vendor/differential_drive.h:18-20`, `:107-110` — this ticket only
adds the binding surface to reach it from Python).

1. **Bind `diffdrive.step()`** in `native/moddiffdrive.cpp` +
   `native/moddiffdrive_glue.c`, alongside the existing `configure/
   begin/start/drive/driveDuty/neutral/estop/output/lastError/
   cycleOverrunCount` surface. One kernel cycle inline in the calling
   context (`DifferentialDrive::step()` is already public per
   `vendor/differential_drive.h:344-351`).
2. **Mode latch**: first call of `start()` OR `step()` (whichever
   comes first) latches the mode for the rest of the boot; the other
   entry point then raises. This honors the vendored `FiberLauncher`
   contract (`vendor/differential_drive.h:86-89`) — the injected
   launcher checks the latch and fails loudly if called out of turn.
   `start()` remains irreversible (no `stop()`, `run()` never
   returns), so the latch is boot-scoped, not resettable.
3. **Mode-aware `Sleeper`**: extend `native/platform_ports.{h,cpp}`'s
   `PlatformSleeper` with a flag set once, at latch time, in
   `fiberEntry`. Kernel-fiber caller (background mode) →
   `codal::fiber_sleep()` (unchanged, current behavior). Step-driven
   caller (main context) → `mp_hal_delay_ms()` — this is what reaches
   `microbit_hal_idle()` during a settle, so the comms pump keeps
   running. One class, one flag — not two `Sleeper` subclasses (see
   sprint.md Design Rationale for why).
4. **Reentrancy guard on `step()`**: raise if a step is already in
   flight — a scheduled callback firing during a settle delay could
   otherwise re-enter. Prior art: `reference/modrobot/modrobot.cpp`'s
   `inProgress` guard on `robot_v5_service()` (lines ~1478-1487).
5. **Expose read-only `cyclePeriod`** so Python can pace correctly
   against the kernel's actual configured cycle period, not a
   hardcoded constant.
6. **Leave the VM-hook starvation watchdog (`native/watchdog.h`)
   unmodified.** It already keys off `Output.cycleCount`, which
   advances under either mode — confirmed mode-independent by design,
   not something this ticket needs to touch.

Explicitly out of scope (per the issue): any `vendor/` edit; the
`step()` re-entrant/SWI restructure (spec §7.3, a separate,
radio-robot-owned decision); any change to fiber-mode behavior.

## Acceptance Criteria

- [x] `diffdrive.step()` is bound and callable from Python; one call
      runs exactly one kernel cycle inline in the caller's context (no
      fiber, no fiber switch).
- [x] Mode latch: whichever of `start()`/`step()` is called first
      succeeds; the other then raises, for the rest of that boot.
      Verified in native source review, since a full latch-race test
      needs hardware (ticket 009 covers the hardware leg; this
      ticket's own gate is source review + build, per the issue's own
      "Offline (this repo)" verification split).
- [x] `PlatformSleeper` branches correctly on the mode flag: fiber
      mode still calls `codal::fiber_sleep()`/`codal::schedule()`
      unchanged; step mode calls `mp_hal_delay_ms()`.
- [x] `step()` has a reentrancy guard that raises on re-entry while a
      step is in flight.
- [x] `cyclePeriod` is exposed read-only from Python and reflects the
      kernel's actual configured value (not a duplicated constant).
- [x] `git diff --exit-code -- vendor/` is clean — no vendored file
      touched.
- [x] `./build.sh --clean --with-diffdrive` links successfully with
      `step` present in the `diffdrive` method table (grep/`nm` check
      against the produced object, or a REPL `dir(diffdrive)` smoke
      check on any connected board — this only confirms the binding
      surface exists, not zetuv- or tovez-specific calibration, so it
      does not require the target-robot identity question ticket 009
      resolves).
- [x] `native/watchdog.h` is unmodified (diff shows no change) —
      confirms mode-independence was already structural, not something
      this ticket needed to add.

## Testing

- **Existing tests to run**: `uv run pytest` (223 passed / 518
  subtests baseline) stays green — this ticket touches no Python
  source. `src/tests/diffdrive/` is radio-robot's own gate on the
  vendored kernel and is not re-run here (no `vendor/` change).
- **New tests to write**: none at the Python level (native C++ has no
  existing unit-test harness in this repo beyond the build-gate/
  golden-vector suites) — this ticket's own gate is the build link
  check and source review above, matching the issue's own stated
  "Offline (this repo)" verification.
- **Verification command**: `./build.sh --clean --with-diffdrive`
  (build gate); `uv run pytest` (regression gate).
