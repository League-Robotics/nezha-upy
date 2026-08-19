# native/ — moddiffdrive

The only C/C++ this repo ships beyond the vendored kernel (`vendor/`,
never edited — see `CLAUDE.md`). Implements PLAN.md/spec M1: exposes the
vendored `DiffDrive::DifferentialDrive` kernel to Python as a
lease-bounded wheel API, on its own CODAL fiber, plus the safety
machinery the kernel does not provide by itself (boot zero-write,
VM-hook starvation watchdog, a binding-level lease ceiling).

Built by `./build.sh --clean --with-diffdrive` (implies `--with-yield`).

## Layout

| File | Role |
|---|---|
| `hal/device_types.h`, `hal/device_config.h`, `hal/i2c_bus.h`, `hal/motor.h` | The minimal `Hal::` contract `vendor/nezha_motor.{h,cpp}` and `vendor/motor_armor.h` need to compile, reverse-engineered from their own `override` lists — **not** a copy of radio-robot's live `src/firm/hal/*.h`, which has already diverged from the vendored snapshot (see `hal/device_types.h`'s own header for the specifics). |
| `hardware/nezha/nezha_motor.h` | One-line router so `vendor/nezha_motor.cpp`'s own `#include "hardware/nezha/nezha_motor.h"` resolves to `vendor/nezha_motor.h` without touching `vendor/`. |
| `i2c_broker.h` / `.cpp` | `I2cBroker` — the **one shared** `Hal::I2CBus` implementation (per-device `lastEnd`/`readyAt` clearance ledger, ported from `reference/modrobot/modrobot.cpp`'s `HalI2CBus`). Every I2C transaction on the device — kernel-fiber Nezha traffic and `robotio.i2c_xfer()` alike — goes through `I2cBroker::instance()`. |
| `platform_ports.h` / `.cpp` | `PlatformClock`/`PlatformSleeper`/`PlatformFiberLauncher` — the three of `differential_drive.h`'s four ports that aren't the motor leaf, each a thin wrapper over a CODAL primitive (`mp_hal_ticks_us()` extended to 64-bit, `fiber_sleep()`/`schedule()`, `create_fiber()`). |
| `nezha_leaf.h` | `NezhaLeaf` — the `DiffDrive::Motor` port adapter: a one-line forwarding wrapper (the pattern `differential_drive.h`'s own file header names) over the vendored `Hardware::MotorArmor(Hardware::NezhaMotor(...))`, compiled unedited. |
| `nezha_wire.h` | The raw Nezha zero-duty write frame, factored out once (ported as data from `vendor/nezha_motor.cpp`'s `writeMotorRun()`) so the boot zero-write and the watchdog's fault response can each write an unconditional hardware zero without going through a `DifferentialDrive` object that might not exist yet or might be stalled. |
| `watchdog.h` / `.cpp` | `Watchdog` — the VM-hook zero-only starvation watchdog. |
| `moddiffdrive.cpp` / `moddiffdrive_glue.c` | The MicroPython binding: module lifecycle, Python API, the boot zero-write and VM-hook entry points `main.c`/`mpconfigport.h` call into. |

## Python API

### `diffdrive`

```
diffdrive.configure(left_port, right_port, fwd_sign_left=1, fwd_sign_right=1,
                     max_duty=0.0, full_duty_velocity=0.0, cycle_period_ms=24)
    -> status:str
```
Constructs the kernel (placement-new into static storage — see
`moddiffdrive.cpp`'s own comment on why, and its documented single-call
scope for this ticket; ticket 007 owns a real guarded reconfigure). Binds
`left_port`/`right_port`/the two `fwd_sign_*` values generically, per this
ticket's scope — the gopiv wiring *values* live in config data (ticket
002); ticket 007 wires config data to this call. **Every authority
default is fail-closed** (`max_duty=0.0`, `full_duty_velocity=0.0`,
matching `DiffDrive::Config`'s own "EVERY DEFAULT IS FAIL-CLOSED"
contract) — a bare `configure(left_port=2, right_port=1)` still refuses
every drive/driveDuty call until real authority values are supplied.

```
diffdrive.begin() -> status:str
diffdrive.start() -> status:str
```
`begin()` primes both encoders and freezes `cyclePeriod`. `start()`
launches the kernel fiber. Both return `"refused_unconfigured"` if
`configure()` was never called.

```
diffdrive.drive(velocity, twist, lease_ms) -> status:str      # [counts/s] [counts/s] [ms]
diffdrive.driveDuty(dutyLeft, dutyRight, lease_ms) -> status:str  # [-1,1] [-1,1] [ms]
```
`lease_ms` is a **duration**, not an absolute time. **5000 ms binding
ceiling, enforced by rejection, never clamping**: `lease_ms > 5000`
returns `"refused_lease_ceiling"` immediately, without calling into the
kernel at all — a caller's units bug (PLAN.md's landmine ledger L4: a
sec/ms slip once ran wheels 8+ minutes) is a visibly refused command, not
a silently truncated one. This is independent of, and far tighter than,
the kernel's own `DifferentialDrive::kLeaseMax` (3,600,000 ms).

```
diffdrive.neutral() -> None
diffdrive.estop() -> None
```

```
diffdrive.output() -> dict
```
A subset of `DiffDrive::DifferentialDrive::Output` (cycle counters,
per-wheel position/velocity, applied duty, the `ready`/`estopped`/
`leaseExpired`/`stallHalted`/`connected*` flags) plus this ticket's own
`watchdogFault`/`watchdogTripCount` fields — **not** part of the vendored
`Output` struct (a `vendor/` type this repo never edits); this is the
binding's own visible-fault addition (spec Section 7.2). Full 22-field
telemetry-frame integration is ticket 007's job; the counter/fault fields
this ticket's acceptance criteria require are present now.

```
diffdrive.lastError() -> status:str
diffdrive.cycleOverrunCount() -> int
```
`cycleOverrunCount()` is a raw accessor redundant with
`output()["cycleOverrunCount"]`, present because this ticket's acceptance
criteria ask for "at minimum a raw accessor."

Every `status:str` is one of: `"ok"`, `"refused_unconfigured"`,
`"refused_not_begun"`, `"refused_estopped"`, `"refused_non_finite"`,
`"cadence_preserved"` (the kernel's own `DifferentialDrive::Status`
values) or `"refused_lease_ceiling"` (this binding's own addition).
Refusals are returned, never raised — see `moddiffdrive.cpp`'s own file
header for why (`reference/vevov-micropython-spike-handoff.md`'s
Challenge 2 documents this C++/MicroPython NLR interaction as fragile in
this exact binding shape).

### `robotio`

```
robotio.i2c_xfer(address, write_data=b'', read_len=0, repeated=False,
                  pre_clear=0, post_clear=0)
    -> status:int                    # read_len == 0 (write-only)
    -> (status:int, data:bytes)      # read_len > 0 (write [if any], then read)
```
The one shared I2C ledger's Python-facing door (spec Section 5): goes
through the **same** `I2cBroker` instance the kernel's Nezha traffic
uses, so per-device `lastEnd`/`readyAt` clearance timers and the
TWIM-errata gap are shared state between Python sensor code and the
kernel fiber, not two independent bookkeeping copies. `read_len` is
capped at 64 bytes (this is a Nezha/OTOS/line/color-class sensor bus, not
a bulk transfer).

## Safety machinery

### Boot zero-write

`moddiffdrive_boot_zero_write()` (`moddiffdrive.cpp`) runs from
`main.c`, wired in **before** `gc_init()`/`mp_init()` — before the VM
exists at all, so before any Python (including a student's own boot
code) can run. The Nezha brick latches its last commanded speed across
an nRF52 reset, so a reset mid-drive must be silenced immediately. The
robot's real wiring isn't known this early (Python hasn't called
`configure()` yet), so this defensively sweeps ports 1–4 rather than only
the two a given robot uses.

### VM-hook zero-only starvation watchdog

`moddiffdrive_vm_hook()` is called from `MICROPY_VM_HOOK_POLL`
(`mpconfigport.h`) — the **existing, stock** hook this port already fires
roughly every 64 bytecodes (confirmed, by diffing a fresh checkout
against its own git history, to be upstream default behavior, not one of
this project's own patches). Extending this hook, rather than inventing a
new one, is deliberate: `docs/nezha-upy-review.md` Section 1 / spec
Section 7.1 close the "find a better hook point" question permanently.

`Watchdog::poll()` (`watchdog.h`/`.cpp`) **never yields, sleeps, or
triggers a fiber switch** — no `schedule()`, `fiber_sleep()`, or
`create_fiber()` anywhere in its call graph. It tracks the kernel's
`Output.cycleCount` (cheap-throttled to one seq-consistent copy per
20 ms, not one per hook firing) and, if that counter stalls for
≥ 250 ms while the kernel's own last-known state says wheels are
commanded (`ready && !leaseExpired && !estopped && !stallHalted`), writes
an unconditional raw zero-duty frame (retry ×2) directly through the
`I2cBroker` — bypassing the `DifferentialDrive` object entirely, because
that object's own fiber is exactly what might be dead. The fault latches
(`watchdogFault` in `output()`) and lights a fixed diagonal-X pattern on
the LED matrix (spec Section 7.2: "a silent stop at 250 ms is
indistinguishable from a hardware fault to a student").

**Both M1 safety-case shapes are covered by the same mechanism, with no
special-casing between them:**
- **Busy-wait** — `drive(...)` then `while True: pass`. Never reaches
  `microbit_hal_idle()`; `Output.cycleCount` stops advancing.
- **Polling idiom** — `drive(...)` then
  `while True: p = radio.receive()`. `radio.receive()` returns
  immediately and allocates every call; the loop still never reaches
  `microbit_hal_idle()`, so `Output.cycleCount` still stops advancing.
  This is the realistic trigger (`docs/nezha-upy-review.md` Section 2) —
  the pathological busy-wait is not the only case that matters.

The actual ≤ 250 ms-to-zero timing is a hardware measurement (ticket
009's stakeholder procedure), not something source review can assert;
what this ticket's acceptance criteria verify by source review is that
the watchdog path never yields and that its design covers both trigger
shapes identically (it does — `poll()` has no branch on *how* the stall
happened, only on *whether* `cycleCount` has advanced).

### The one safe yield point

`microbit_hal_idle()` (`patches/apply_yield.py`, applied by
`--with-yield`, which `--with-diffdrive` implies) is the **only** place
this image ever calls `codal::fiber_sleep()`/`schedule()`. See
`patches/apply_yield.py`'s own module docstring for why this is a
corrected version of the old exploration's `patches/yield.patch`
diff, not a literal re-application of it — the short version: the stock
`MICROPY_VM_HOOK_POLL` already calls
`microbit_hal_background_processing()`, so adding a fiber switch to
*that* function (what the old diff did) puts a fiber switch on the VM
hook path, which is the exact landmine
`docs/nezha-upy-review.md` Section 1 describes. This build's version
touches only `microbit_hal_idle()` itself.

## Deliberately out of scope for this ticket

- The `step()` re-entrant-state-machine / pended-SWI restructure
  (`docs/nezha-upy-review.md` Section 3) — a `vendor/` change, belongs in
  radio-robot, contingent on how the (stakeholder-run) M1 safety triple
  reads.
- Full per-robot config mapping (`DiffDrive::Config`'s remaining ~15
  fields, `Hal::MotorConfig`'s write-shaping fields beyond the bench
  defaults `configure()` currently substitutes) — ticket 007.
- A live, guarded `reconfigure()` — `configure()` is single-call-scoped
  for this ticket; see `moddiffdrive.cpp`'s own comment.
