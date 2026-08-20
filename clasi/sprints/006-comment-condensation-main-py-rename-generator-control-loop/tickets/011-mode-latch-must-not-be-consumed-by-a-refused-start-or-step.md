---
id: '011'
title: Mode latch must not be consumed by a refused start() or step()
status: done
use-cases:
- SUC-001
- SUC-002
depends-on:
- '006'
github-issue: ''
issue: generator-driven-control-loop-mode-addition-not-replacement.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Mode latch must not be consumed by a refused start() or step()

## Description

Defect found on real hardware during ticket 009's bench run (tovez,
wheels on blocks) — the offline suite could not catch this; see
ticket 009's `exception` block for the measured evidence. Ticket 009
is thrown and will be re-run once this ticket and 012 both land.

**Measured**: on a fresh boot, `diffdrive.start()` called before
`begin()` returns the status string `refused_not_begun` — it launches
no fiber and does nothing — yet it still latches fiber mode for the
rest of the boot. A subsequent `configure()` + `begin()` + `step()`
then raises `RuntimeError: step() refused: start() already latched
fiber mode this boot`. Generator mode is silently locked out for that
boot by a call that was refused and did nothing.

**Site**: `native/moddiffdrive.cpp`, `diffdrive_start_fn` (currently
around lines 271-283 — ticket 004's concurrent comment-condensation
pass may shift these line numbers; locate by function name, not by
line number alone). The current shape: check `g_mode == Mode::kStep`
and raise; then `if (g_mode == Mode::kUnlatched) { g_mode =
Mode::kFiber; ... }`; only *after* that does the function call
`g_kernel->start()` and return its status. The latch fires
unconditionally, before the kernel has decided whether `start()` will
actually do anything — `g_kernel->start()`'s own refusal (e.g.
`DiffDrive::Status::kRefusedNotBegun`, `vendor/
differential_drive.h:107`) is discovered only after the mode is
already claimed.

**The rule to encode**: a call that returns a refusal leaves the mode
exactly as it found it. Only a call that does the thing claims the
mode.

**Fix, `start()`**: reorder so the latch is set only once `start()` is
known to have actually launched the fiber — i.e. call
`g_kernel->start()` (or otherwise determine it will not refuse) before
setting `g_mode = Mode::kFiber`, not before. `g_mode == kStep` conflict
detection stays first (that is a real, correct refusal reason and must
keep blocking `start()` outright — it is not the bug).

**Fix, `step()`, symmetric** (`diffdrive_step_fn`, currently around
line 289-311): `DifferentialDrive::step()` returns `void`
(`vendor/differential_drive.h:351`), so it cannot report a refusal via
its return value the way `start()` can — the check has to happen
*before* calling `step()`/before latching, using the kernel's own
begun-state. `DiffDrive::DifferentialDrive::Output.ready` ("begun +
calibrated", `vendor/differential_drive.h:217`, already readable via
`g_kernel->output()`) is one avenue — confirm it is the right check
(or find the correct one) and use it to gate the latch the same way
`start()`'s fix gates its own. Note the two existing refusal checks in
`step()` today (the `g_mode == kFiber` conflict, and the
`g_stepInFlight` reentrancy guard) already run *before* the current
latch-set line, so they are not the bug — the gap is that nothing
today checks "has `begin()` actually run" before latching to `kStep`,
so a `step()` called before `begin()` would claim the latch for
nothing, exactly mirroring `start()`'s defect.

Explicitly out of scope: any change to `vendor/`; any change to the
reentrancy guard or the `kFiber`/`kStep` conflict-detection logic
themselves (both already correct); ticket 012's `Move.stop()`/context-
manager work (independent, lands separately).

## Acceptance Criteria

- [x] `start()`: a refused call (any refusal reason — unconfigured,
      not-begun, or any other) leaves `g_mode` unchanged from
      whatever it was before the call. Only a `start()` that actually
      launches the fiber sets `g_mode = kFiber`.
- [x] `step()`: a refused call (kFiber conflict, reentrancy, or
      not-begun) leaves `g_mode` unchanged. Only a `step()` that
      actually runs a kernel cycle sets `g_mode = kStep`.
- [x] The existing `kFiber`/`kStep` mutual-exclusion behavior for a
      call that *would* succeed is unchanged — this ticket fixes when
      the latch fires, not whether the two modes still exclude each
      other once one is legitimately claimed.
- [ ] **Bench repro** (targeted hardware check, on the current
      confirmed bench robot — identify it the same way ticket 009
      does, from the device's own `robot.json`/`ID` response, not
      `config/devices.json`): on a fresh boot, `start()` called before
      `begin()` returns `refused_not_begun`; a following
      `configure()` + `begin()` + `step()` then **succeeds** (no
      `RuntimeError`), instead of raising as it does today. This is a
      narrow, targeted check — not the full ticket 009 procedure,
      which is re-run separately once this ticket and 012 both close.
      NOT run by the programmer per task instructions ("Do NOT run the
      hardware repro yourself") — pending team-lead's bench pass
      against this ticket's built image.
- [x] `./build.sh --clean --with-diffdrive` links clean.
- [x] `git diff --exit-code -- vendor/` is clean — no vendored file
      touched.
- [x] `uv run pytest tests/` stays at 237 passed / 518 subtests —
      unchanged from the current baseline (244 passed / 0 failed after
      ticket 012's own baseline shift; no regression, no Python test
      changed by this ticket).

## Testing

- **Existing tests to run**: `uv run pytest tests/` (237 / 518
  baseline) — this ticket's own Python-visible surface (status
  strings, raised exceptions) is exercised indirectly through any
  existing motion/diffdrive-binding tests; confirm none regress.
- **New tests to write**: no new Python unit test is expected to
  reach this bug directly (it lives entirely in the native binding's
  internal `g_mode` state, not observable from a CPython-side fake
  stub) — the proof is the bench repro above plus a source-level
  review confirming the reordering. If a native-level test harness
  exists or is added, exercise it there instead of asserting this is
  untestable by default.
- **Verification command**: `./build.sh --clean --with-diffdrive`
  (build gate); `uv run pytest tests/` (regression gate); the bench
  repro above (hardware gate).
