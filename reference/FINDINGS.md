# MicroPython Phase A Exploration — Findings

**Date**: 2026-08-12  
**Objective**: Risk-reduction spike for the MicroPython-as-base migration.  
**Primary goal**: Send wheel commands from Python REPL, see wheels move.

**Build status**: ✅ **Full custom hex produced** (macOS, GCC 15.2.rel1, cmake 4.4.0)  
Binary: 346KB text + 141KB data + 50KB BSS = 537KB total flash image  
Layout: SoftDevice 0x01000–0x1c000 | MicroPython 0x1c000–0x5f328 | Filesystem 0x6d000–0x73000

---

## 1. The Simplest Possible Path — Stock MicroPython (Zero Build)

**Finding**: The Nezha V2 motor board is reachable directly from `microbit.i2c`
in stock MicroPython v2.1.2 with no build changes.

**Steps**:
1. Download the stock hex: https://github.com/microbit-foundation/micropython-microbit-v2/releases/tag/v2.1.2
2. Flash: `cp MICROBIT.hex /Volumes/MICROBIT` (DAPLink drag-drop)
3. Connect via REPL: `mpremote connect /dev/cu.usbmodem...` or `screen /dev/cu.usbmodem... 115200`
4. Type at the REPL:

```python
from microbit import i2c
i2c.write(0x10, bytes([0xFF, 0xF9, 1, 1, 0x60, 50, 0xF5, 0x00]))  # left wheel fwd 50%
i2c.write(0x10, bytes([0xFF, 0xF9, 2, 2, 0x60, 50, 0xF5, 0x00]))  # right wheel fwd 50%
```

Or use the included `robot.py`:
```python
import sys
sys.path.append('/flash')   # if uploading to filesystem
from robot import drive, stop
drive(50, 50)
stop()
```

**Why it works**:
- `microbit.i2c` defaults to P19/P20 (external edge connector I2C) — same pins
  the Nezha V2 uses.
- `microbit_hal_i2c_writeto(addr, buf, len, stop)` → `uBit.i2c.write(addr<<1, ...)`,
  the exact same CODAL call our firmware makes.
- For pure WRITE commands (no encoder reads) there is no timing constraint.
  The Nezha brick latches the last commanded speed until the next write.
- Default 100 kHz I2C frequency works.  `i2c.init(freq=400000)` matches our firmware.

**Key caveat**: This is open-loop.  No PID, no encoders, no stop conditions.
The Nezha brick latches speed on power loss only -- a micro:bit reset while
driving will leave wheels spinning.  Need `stop()` before any reset/power cycle.

**REPL vs. main.py**: Typing at the REPL is interactive.  For a program loop,
put `main.py` on the micro:bit filesystem via `mpremote fs cp robot.py :/robot.py`.

---

## 2. The REPL Interface — Two Options

### Option A: USB REPL (Recommended for this exploration)
Connect directly to the micro:bit USB.  MicroPython's REPL runs on USB serial.
No relay needed.  This is the architecture the issue specifies:
> "REPL on USB, robot protocol on radio."

```
developer laptop -> USB -> micro:bit (MicroPython REPL)
                                    |
                                   I2C -> Nezha -> wheels
```

`mpremote` is the recommended tool:
```
pip install mpremote
mpremote connect /dev/cu.usbmodemXXX
```
Or use `screen /dev/cu.usbmodemXXX 115200`.

### Option B: Radio/relay path to a Python shell
Connect via the radio relay as with the existing firmware, but somehow drop
into a Python shell.  **This does not exist in the stock MicroPython port.**
MicroPython's REPL is USB-only.  Implementing it would require a serial-over-
radio module on the MP side.  Not a sensible path for the spike.

**Decision for this spike**: Use Option A (USB REPL directly).

---

## 3. The Hard Part — Scheduling (The Issue's Phase A Risk)

### 3a. The Problem

`microbit_hal_background_processing()` in `src/codal_app/microbithal.cpp` fires
a CODAL event but NEVER does a fiber context switch:

```cpp
void microbit_hal_background_processing(void) {
    // This call takes about 200us.
    Event(DEVICE_ID_SCHEDULER, DEVICE_SCHEDULER_EVT_IDLE);
    // NO schedule() call here -- other fibers get ZERO CPU
}
```

`mp_hal_delay_ms()` in `codal_port/mphalport.c` loops calling `microbit_hal_idle()`:

```c
void mp_hal_delay_ms(mp_uint_t ms) {
    ...
    while (mp_hal_ticks_ms() - start < ms) {
        mp_handle_pending(true);
        microbit_hal_idle();  // calls background_processing() + no-yield WFI in OLD MP
    }
}
```

`microbit_hal_idle()` calls `background_processing()` (event, no switch) then
`__WFI()` (CPU sleep until next interrupt).  A kernel fiber gets ZERO CPU while
Python runs except during interrupt handlers.

The v2.1.2 mphalport.c was updated to call `microbit_hal_idle()` directly (not
`__WFI` separately), and microbithal.cpp's idle just fires an event.  A robot
kernel fiber running on a separate CODAL fiber would be completely starved.

**Measured baseline** (from the issue): our kernel does ~9-11 ms of real work
per 50 ms cycle at 20% duty.  In MicroPython with NO yield patch, the kernel
fiber gets 0% CPU.

### 3b. The Fix

Two-line patch to `src/codal_app/microbithal.cpp` (see `patches/yield.patch`):

```cpp
void microbit_hal_background_processing(void) {
    Event(DEVICE_ID_SCHEDULER, DEVICE_SCHEDULER_EVT_IDLE);
    schedule();   // ADD: cooperative yield to CODAL fiber scheduler
}

void microbit_hal_idle(void) {
    fiber_sleep(1);   // ADD: yield for 1ms minimum instead of busy-WFI
    microbit_hal_background_processing();
}
```

`schedule()` is a CODAL function that runs the fiber scheduler without a sleep
timeout -- yields if another fiber is ready, returns immediately if not.
`fiber_sleep(1)` is the cooperative primitive that's equivalent to our firmware's
`sleeper.sleepMs(1)`.

**Risk**: The VM hook fires every 64 bytecodes (`MICROPY_VM_HOOK_COUNT=64`).
For pure Python tight loops, this fires frequently enough.  The risk is long-
running C operations inside MP (big string join, flash write, `.mpy` import)
that don't hit the VM hook for extended periods, which is exactly the
adversarial test the issue's Phase A gate calls for.

**The gate measurement**: Under adversarial Python (tight while-True, big string
join, flash .mpy import, display.scroll, forced GC), does the 50ms kernel fiber
maintain ≤54ms delivered period?  If yes → Option 1 (yield patch is enough).
If no → Option 3 (hybrid: bounded actuation at ISR priority, planner at fiber).

### 3c. The GC Hook (Missing from Current Port)

Pybricks adds a GC-loop hook to keep control alive during a heap sweep:

```c
#define MICROPY_GC_HOOK_LOOP \
    do { microbit_hal_background_processing(); } while (0)
```

This should be added to `mpconfigport.h`.  Without it, a full GC sweep (which
scans 40KB RAM at ~4KB/ms) could black out the kernel for ~10ms.

**Action needed**: Add `MICROPY_GC_HOOK_LOOP` with a `schedule()` call to
`mpconfigport.h`.  This is a one-liner that the final implementation needs.

---

## 4. Memory — Numbers from the Issue (Confirmed Good)

| Resource      | Budget         | Use              | Margin        |
|---------------|---------------|-----------------|---------------|
| Flash 512KB   | ~311KB MP+FS   | +~80KB kernel   | ~80-120KB     |
| RAM 128KB     | 40KB GC heap   | ~15KB kernel    | ~45-55KB CODAL heap |

**Key levers already in our codal.json**:
- `DEVICE_BLE: 0` — drops SoftDevice/DFU, saves ~180KB flash + ~8.2KB RAM
- `MICROBIT_RADIO_MAX_PACKET_SIZE: 250` — matches our relay protocol

**GC heap reduction** (64→40KB): Not a codal.json key.  Edit in
`codal_port/main.c`:
```c
#define MICROBIT_HEAP_SIZE (40 * 1024)   // was 64 * 1024
```
This frees 24.6KB of CODAL heap.

---

## 5. The uBit Singleton — Not a Problem for the Spike

For the minimal spike (pure I2C motor commands, no full kernel), there is NO
singleton conflict.  MicroPython's `main.cpp` owns `MicroBit uBit` and we
access the I2C bus through `microbit.i2c` (Python) or `microbit_hal_i2c_writeto`
(C module).  We do not construct a second `MicroBit` instance.

For Phase B (kernel-as-guest), the resolution is:
- Delete our `src/firm/main.cpp` from the MP build
- `composeRobot()` takes a `MicroBitI2C&` reference (not a `MicroBit&`) so
  it naturally accepts `uBit.i2c` from MP's main
- The `static MicroBit uBit` lives only in MP's `codal_app/main.cpp`

---

## 6. Radio Conflict — Blocks Full Kernel, Not the Spike

MP's `main.cpp` redirects RADIO_IRQn to its own handler:
```cpp
NVIC_SetVector(RADIO_IRQn, (uint32_t)microbit_radio_irq_handler);
```

Our `Radio` class also owns RADIO_IRQn.  Two owners = one works, one doesn't.
**For the spike** (I2C motor commands from REPL): radio is NOT used.  No conflict.

**For Phase B**: Remove the `NVIC_SetVector` line from MP's `main.cpp` and
drop `modradio.c` from the build.  Our `Radio` driver then owns the vector.
The bench relay and rogo tooling continue to work unchanged (same PHY, our framing).

---

## 7. The `com/` Layer — Replaced by MessageRingTransport

For Phase B+, `com/Radio` and `com/SerialPort` cannot coexist with MicroPython.
MP owns the USB serial (REPL) and the radio IRQ.

**Replacement**: `MessageRingTransport` — an in-memory SPSC ring pair (~1.7KB
for depth-4 × 211B frames both ways) implementing `App::Transport` (the same
interface `FakeTransport` in the sim test suite implements).  `App::Comms` and
everything above are unchanged.

**For the spike**: Not needed.  Pure REPL motor commands don't use the comms layer.

---

## 8. Build System — What Goes in the Repo

**Files to commit** (in `micropython/`):
- `robot.py` — pure Python motor driver, works on stock hex
- `build.sh` — build script: submodule init → config overlay → yield patch → build
- `patches/apply_overlay.py` — JSON overlay merge helper
- `patches/yield.patch` — the two-line yield fix for microbithal.cpp
- `patches/modrobot_wire.patch` — documentation of how modrobot wires in
- `modrobot/modrobot.c` — the C extension module (wired in by build.sh)
- `codal_overlay.json` — our config overlay (DEVICE_BLE=0, radio 250, etc.)

**Do NOT commit**: `micropython-microbit-v2/` (the clone itself -- too large,
pinned as a known version, fetched by `build.sh` on first run).

**Add to .gitignore**:
```
micropython/micropython-microbit-v2/
micropython/micropython-microbit-v2/src/build/
```

---


## 8b. Build System — macOS Compat Issues (GCC 15 + cmake 4.4)

Four compat issues were found and fixed during the spike build on macOS with
ARM GNU Toolchain 15.2.rel1 and cmake 4.4.0. All fixes are applied by `build.sh`
steps 8-11.

### Issue 1 — cmake 4.4 policy version minimum

`cmake_minimum_required(VERSION 2.8...)` in `lib/codal/CMakeLists.txt` is too old.
cmake 4.4 made it a hard error (not just a warning).

**Fix**: Add `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` to the cmake invocation in
`src/Makefile` (the Makefile's `codal_cmake` and `codal_build` targets both call cmake).

### Issue 2 — macOS `-arch` flag injected into cross-compiler

cmake on macOS applies platform-specific `-arch <host>` flags even when building
for a cross-compile target. `CMAKE_OSX_ARCHITECTURES=""` alone is not sufficient
because cmake's macOS platform file (`Platform/Darwin.cmake`) defaults to the
host architecture.

**Fix**: In `lib/codal/utils/cmake/toolchains/ARM_GCC/toolchain.cmake`, add:
```cmake
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR ARM)
```
This tells cmake "this is NOT a macOS target" and suppresses all OSX-specific
platform handling including the `-arch` injection.

**Symptom**: `arm-none-eabi-g++: error: unrecognized command-line option '-arch'`
at the very first source file compiled.

### Issue 3 — CortexContextSwitch.s missing `.thumb_func` (GCC 15 strict ld)

GCC 15's linker (`ld`) is stricter about ARM/Thumb interworking.  The CODAL
context-switch assembly in `codal-nrf52/asm/CortexContextSwitch.s` exports four
global labels (`swap_context`, `save_context`, `save_register_context`,
`restore_register_context`) without `.thumb_func` annotations, so the linker
can't determine their instruction-set type.

**Fix**: Add `.thumb_func` before each exported label.

**Symptom**: 
```
libcodal-nrf52.a(CortexContextSwitch.s.obj)(save_context): Unknown destination type (ARM/Thumb)
CodalFiber.cpp: dangerous relocation: unsupported relocation
```

### Issue 4 — addlayouttable.py doesn't parse RAM symbol addresses

The post-build script `addlayouttable.py` reads the linker map to locate
`__data_start__` and `__data_end__` (RAM addresses starting `0x20...`), but its
parser only matches lines starting with `0x00` (flash range).

**Fix**: Change the condition to `line.startswith("0x00") or line.startswith("0x20")`.

**Symptom**:
```
TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'
```
at `symbols["__data_end__"] - symbols["__data_start__"]`.

---

## 9. How to Flash and Test

### Quick demo (stock hex, no build):
```bash
# Download stock hex
curl -L https://github.com/microbit-foundation/micropython-microbit-v2/releases/download/v2.1.2/micropython-microbit-v2.hex \
     -o /tmp/micropython-v2.1.2.hex

# Flash (DAPLink)
cp /tmp/micropython-v2.1.2.hex /Volumes/MICROBIT

# Upload robot.py to the micro:bit filesystem
pip install mpremote
mpremote fs cp micropython/robot.py :/robot.py

# Connect to REPL
mpremote

# At REPL:
# from robot import drive, stop
# drive(50, 50)    # both wheels forward
# stop()
```

### Built hex (with yield patch + modrobot):
```bash
cd micropython
./build.sh --with-yield --with-modrobot

# Flash
cp micropython-microbit-v2/src/MICROBIT.hex /Volumes/MICROBIT

# At REPL:
# import robot
# robot.drive(50, 50)
# robot.stop()
```

---

## 10. Open Questions / Phase B Prerequisites

1. **Yield gate measurement**: Run the adversarial Python programs and measure
   the kernel fiber's delivered period histogram.  This is the Phase A gate.

2. **GC hook**: Add `MICROPY_GC_HOOK_LOOP` → `schedule()` to mpconfigport.h.
   Without it, a GC sweep could stall the kernel for ~10ms.

3. **Kernel fiber stack size**: CODAL's shared 2KB physical stack is small.
   MP's codal.json already sets `DEVICE_STACK_SIZE: 8192` -- but the kernel
   fiber needs its OWN stack allocation.  `create_fiber(fn, arg, stack_size)`
   is the CODAL API.  4-8KB is appropriate.

4. **I2C frequency**: Confirm 100kHz vs 400kHz matters for Nezha commands
   under load.  `i2c.init(freq=400000)` before any motor calls in robot.py.

5. **Motor stop on program exit**: When the Python program exits (or Ctrl-C),
   the Nezha brick latches its last commanded speed.  Need an atexit/finally
   stop() in robot.py, or a deadman in the kernel fiber.

6. **mpremote workflow**: The MicroPython filesystem editor (mu-editor or
   mpremote) is the standard student interface.  Confirm it works with the
   built hex.

7. **I2C bus contention**: Full kernel (Phase B) will be driving the Nezha on
   the I2C bus from the kernel fiber while Python can call `microbit.i2c`.
   Need a bus ownership policy.  Options: (a) kernel owns I2C, Python's
   microbit.i2c disabled; (b) lock primitive; (c) Python I2C only when kernel
   idle.  For the spike this is moot (no kernel fiber, pure Python I2C).

---

## 11. Summary — Recommended Next Steps

| Step | Action | Complexity |
|------|--------|------------|
| A1 | Flash stock hex + REPL motor demo (robot.py) | **1 hour** |
| A2 | Run `build.sh --with-yield` to get a built hex | **4-8 hours first build (compat issues solved)** |
| A3 | Measure yield gate: fiber period under adversarial Python | **2 hours** |
| A4 | Add GC hook to mpconfigport.h | **30 min** |
| A5 | Wire in modrobot.c as a builtin C module | **1 hour** |
| B1 | MessageRingTransport implementation | **1-2 sprints** |
| B2 | composeRobot() called from MP's main | **1 sprint** |

The Phase A gate (A3) is the decision point: if the 50ms kernel fiber holds
≤54ms under adversarial Python, the yield patch is sufficient and Phase B
proceeds with the fiber-based kernel.  Otherwise, the hybrid ISR approach
(motor actuation at interrupt priority, planner at fiber) is the fallback.

---

## 12. Phase A Completion — Full Sensor Integration Achieved (2026-08-12)

### Status: All subsystems verified on Bebop test rig

All five hardware subsystems are now accessible from the MicroPython REPL
via `import robot`:

| Function | Result | Notes |
|----------|--------|-------|
| `robot.move(30,30,600)` | `(1428, 1478)` | Motor ran drum, encoders non-zero ✓ |
| `robot.stop()` | `(N, N)` | Returns encoder counts ✓ |
| `robot.encoders()` | `(0, 0)` or live counts | ✓ |
| `robot.otos()` | `(-1.22, 36.6, 0.0)` after motion | Tracks translation ✓ |
| `robot.line()` | `(253, 37, 33, 54)` | All 4 channels read ✓ |
| `robot.color()` | `(399, 619, 263, 1297)` | RGBC from PlanetX chip ✓ |
| `robot.servo(1, 90)` | OK | Servo responds ✓ |

### Build system architecture (final)

The C++ firmware drivers cannot use `MP_DEFINE_CONST_FUN_OBJ_*` macros directly
because those macros use C99 designated struct initializers that are invalid in
C++14. Solution: two-file split.

**`modrobot/modrobot.cpp`** — C++14: all implementation classes + `extern "C"`
Python-callable functions (`robot_move_fn`, `robot_drive_fn`, etc.).

**`modrobot/modrobot_glue.c`** — C99: `MP_DEFINE_CONST_FUN_OBJ_*` declarations,
module globals table, `robot_module` definition.

**`codal_port/qstrdefs_robot.h`** — Manual qstr list for the robot module's
9 string keys (robot/drive/move/stop/encoders/otos/line/color/servo). These
cannot be auto-extracted via `SRC_QSTR` because adding `SRC_CXX` to `SRC_QSTR`
corrupts the qstr scan (the C preprocessor's handling of complex C++ headers
with CODAL/MicroPython includes breaks qstr extraction).

**`build.sh --with-modrobot`** handles all of this: copies both source files,
patches the Makefile (CXXFLAGS, SRC_CXX, modrobot_glue.c in SRC_C, QSTR_DEFS),
creates `qstrdefs_robot.h`, and registers `robot_module` in `mpconfigport.h`.

### Key technical issues solved

**`MicroBit.h` not available in Makefile-compiled C++**:
The `codal_port/Makefile` does not include the CODAL library include paths
(those come from cmake-built `codal_app`). Fix: don't include `MicroBit.h` at
all; use `system_timer_current_time_us()` → `(uint64_t)mp_hal_ticks_us()` instead,
and use `microbit_hal_pin_*` functions for servo PWM instead of `NRF52Pin`.

**C++ name mangling of MicroPython C functions**:
Wrapping `#include "py/runtime.h"` and `#include "microbithal.h"` in `extern "C"
{ ... }` in the `.cpp` file prevents the C++ compiler from mangling names like
`mp_hal_ticks_us()` and `microbit_hal_i2c_writeto()`.

**Stale `modrobot.P` dependency file**:
When switching from `modrobot.c` (old C version) to `modrobot.cpp`, the
cached `.P` dependency file in `build/` still referenced `modrobot.c`. Build
failed with "No such file or directory". Fix: delete `build/modrobot.P` and
`build/modrobot.o` before rebuilding.

**Qstr database corruption from `SRC_CXX` in `SRC_QSTR`**:
Adding C++ source files to `SRC_QSTR` causes the qstr extraction step (which
uses `$(CC) -E` not `$(CXX) -E`) to mishandle C++ headers. The result is a
truncated qstr database that drops dozens of standard MicroPython qstrs.
Fix: keep C++ files OUT of `SRC_QSTR`; manually declare robot qstrs in
`qstrdefs_robot.h`.

**`microbit_hal_poll_ctrl_c` not declared in `microbithal.h`**:
This function was added to `microbithal.cpp` in a previous spike pass but
was not in the header. Added it to `microbithal.h`. Without this, the C++
`extern "C"` declaration inside a function body caused a compile error
("expected unqualified-id before string constant").

### Binary size (final)
```
text:   352920 bytes
data:   140823 bytes
bss:     50244 bytes
total:  543987 bytes (0x84CF3)
```
Flash budget: SoftDevice 0x01000–0x1c000 + MicroPython 0x1c000–0x610E0 +
Layout table 0x61FC0–0x62000 + Filesystem 0x6D000–0x73000.
Fits in 512KB with BLE disabled (DEVICE_BLE:0 in codal.json overlay).

### OTOS behaviour note
The OTOS returns (0.0, 0.0, 0.0) when stationary (correct: pose is relative to
init position). It correctly tracks translational motion when the drum spins
(confirmed: (-1.22mm, 36.6mm, 0.0) after 600ms move at 25%). The servo that
tilts the OTOS mount does NOT change heading because the OTOS IMU heading tracks
yaw (in-plane rotation), not the servo's tilt axis. Physical OTOS use requires
the sensor to be within a few mm of a flat textured surface.

### Delivery summary
Everything needed to drive wheels, read encoders, read all sensors, and
command a servo from a USB Python REPL is working. The `build.sh` script is
fully self-contained and idempotent. A future implementer needs only:
1. `cd micropython && ./build.sh --with-modrobot --with-yield`
2. `mbdeploy deploy --hex micropython/micropython-microbit-v2/src/MICROBIT.hex <UID>`
3. `mpremote connect /dev/<port>`

