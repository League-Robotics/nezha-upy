#!/usr/bin/env bash
# build.sh -- Set up and build micropython-microbit-v2 with our robot overlay.
#
# Run from this directory (micropython/).
# Produces: micropython-microbit-v2/src/MICROBIT.hex
#
# OPTIONS:
#   --with-modrobot   Wire in the modrobot C module (builtin `import robot`)
#   --with-yield      Apply the yield+GC-hook patch (required for kernel fiber)
#   --clean           Delete build directories before building
#
# PREREQUISITES (macOS):
#   brew install --cask gcc-arm-embedded   (arm-none-eabi-gcc in PATH)
#   brew install cmake python3
#   pip3 install intelhex                  (for addlayouttable.py)
#
# FIRST RUN: ~20-40 min (downloads CODAL libraries, builds from scratch)
# SUBSEQUENT RUNS: ~3-5 min incremental

set -e
cd "$(dirname "$0")"

MP_DIR="micropython-microbit-v2"
WITH_MODROBOT=0
WITH_YIELD=0
CLEAN=0

for arg in "$@"; do
  case "$arg" in
    --with-modrobot) WITH_MODROBOT=1 ;;
    --with-yield)    WITH_YIELD=1 ;;
    --clean)         CLEAN=1 ;;
  esac
done

echo "=== Step 1: Initialise git submodules ==="
git -C "$MP_DIR" submodule update --init --depth=1
echo "Submodules done."

if [ "$CLEAN" -eq 1 ]; then
  echo "=== Cleaning build directories ==="
  (cd "$MP_DIR/src" && make clean) || true
  (cd "$MP_DIR/lib/micropython/mpy-cross" && make clean) || true
fi

echo "=== Step 1b: Upgrade vendored CODAL libraries to the standard build's SHAs ==="
# Real Gate 2 execution (docs/handoff/micropython-full-firmware-integration.md
# section 9's recommended path, superseding the reverted hand-relink):
# the four libraries under $MP_DIR/lib/codal/libraries/ were vendored as
# pinned ANCESTORS of src/libraries/* (pure fast-forward, no fork -- verified
# via `git merge-base`). Fast-forward each to the exact standard-repo SHA so
# this build shares codal with src/firm and gains its engineered no-SoftDevice
# link (DEVICE_BLE=0 branch already set in codal_overlay.json; CMakeLists.txt
# picks ld/nrf52833.ld over ld/nrf52833-softdevice.ld, and MicroBitConfig.h's
# no-SD branch uses a FIXED MICROBIT_STORAGE_PAGE=0x7F000 instead of a
# UICR-computed address -- the old pinned codal-microbit-v2 HardFaulted on
# exactly that computed address during KeyValueStorage's static init).
#
# MUST run before `make codal_cmake` (Step 14): codal's CMakeLists.txt
# captures each library's source list via RECURSIVE_FIND_FILE (a
# FILE(GLOB_RECURSE...) with no CONFIGURE_DEPENDS, utils/cmake/util.cmake) at
# configure time, so swapping library contents after configure leaves the
# generated Makefiles compiling a stale file list. INSTALL_DEPENDENCY
# (utils/cmake/util.cmake) only clones a library if its directory is
# missing -- it never re-pins an existing checkout, so this step will not
# fight the normal cmake configure.
#
# MUST run after the --clean block above: `make clean`'s Makefile target
# (micropython-microbit-v2/src/Makefile's `clean:`) does
# `rm -rf $(CODAL_LIBRARIES)`, wiping all four directories outright -- this
# is PRE-EXISTING behavior, not introduced here. Steps 2-13 below (including
# Step 10, which edits codal-nrf52/asm/CortexContextSwitch.s directly) all
# assume the libraries exist, so this step also handles the "directory is
# missing entirely" case itself (a full local `git clone` from
# src/libraries/<lib>, not a wait-for-cmake-to-do-it) rather than deferring
# to cmake's INSTALL_DEPENDENCY -- deferring would clone from the OLD pinned
# GitHub branch in codal.json's target field (unrelated to this upgrade) and
# silently undo it. This makes the step self-sufficient across all three
# cases build.sh can start from: already at the recorded SHA (no-op),
# present at an older SHA (fetch + checkout -f), or entirely absent after
# --clean or a true first-time checkout (clone + checkout -f) -- so a fresh
# clone reproduces the exact same upgraded state in one build.sh run.
#
# -f on the checkout: earlier steps in a from-scratch run may have already
# left an old checkout locally modified (e.g. Step 10's own .thumb_func
# annotation, if this step ever runs after it); that patch is idempotently
# re-derivable from source, so discarding it here to reach the exact
# recorded SHA is safe. The SHA actually landed at HEAD is verified below,
# not assumed.
# macOS ships bash 3.2 (no associative arrays -- `declare -A` is a bash 4+
# feature); use parallel indexed arrays instead so this runs under either.
CODAL_LIB_NAMES=(codal-core codal-nrf52 codal-microbit-nrf5sdk codal-microbit-v2)
CODAL_LIB_SHAS=(
  3d485abe653cf0d4080cce66ac072c7f7096f200
  140d1be88bb0223d1d07b72ab11c7b3a809ed0d4
  4b8abc690f6c9fca6132e6db5ee13a795a263f88
  b907e6a77fece07da84fd73ff83cc2994cd5a0ea
)
for idx in 0 1 2 3; do
  lib="${CODAL_LIB_NAMES[$idx]}"
  sha="${CODAL_LIB_SHAS[$idx]}"
  libpath="$MP_DIR/lib/codal/libraries/$lib"
  if [ ! -d "$libpath/.git" ]; then
    echo "  $lib: not present -- cloning from src/libraries/$lib"
    rm -rf "$libpath"
    git clone -q "../src/libraries/$lib" "$libpath"
  fi
  current="$(git -C "$libpath" rev-parse HEAD)"
  if [ "$current" = "$sha" ]; then
    echo "  $lib already at $sha"
  else
    echo "  $lib: $current -> $sha"
    git -C "$libpath" fetch -q "../src/libraries/$lib" HEAD
    git -C "$libpath" checkout -qf FETCH_HEAD
    actual="$(git -C "$libpath" rev-parse HEAD)"
    if [ "$actual" != "$sha" ]; then
      echo "ERROR: $lib checked out to $actual, expected $sha -- src/libraries/$lib has moved since this step's SHA was recorded; update CODAL_LIB_SHA in build.sh" >&2
      exit 1
    fi
  fi
  # codal-nrf52 carries an nrfx (Nordic SDK) git submodule; a plain
  # `git clone`/`checkout` does not populate it (codal's own
  # INSTALL_DEPENDENCY does this itself, but only on a first-ever clone --
  # our clone/checkout above bypasses that path). Idempotent no-op for the
  # other three libraries, which have no .gitmodules at all. Missing this
  # left codal-nrf52/nrfx/mdk/system_nrf52833.c unresolvable and failed
  # cmake's configure with "Cannot find source file" (verified).
  git -C "$libpath" submodule update --init --recursive
done

echo "=== Step 2: Apply config overlay to codal.json ==="
python3 patches/apply_overlay.py \
  "$MP_DIR/src/codal_app/codal.json" \
  codal_overlay.json
echo "codal.json patched."

echo "=== Step 3: Reduce GC heap 64->40 KB ==="
python3 - << 'PYEOF'
path = "micropython-microbit-v2/src/codal_port/main.c"
with open(path) as f:
    src = f.read()
patched = src.replace("static char heap[64 * 1024]", "static char heap[40 * 1024]")
if patched == src:
    print("  GC heap already 40KB or pattern not found -- check main.c")
else:
    with open(path, 'w') as f:
        f.write(patched)
    print("  GC heap reduced 64->40 KB in main.c")
PYEOF

echo "=== Step 3b: NLR via newlib setjmp (arm-gcc 15 breaks v1.18 nlr_thumb) ==="
python3 - << 'PYEOF'
path = "micropython-microbit-v2/src/codal_port/mpconfigport.h"
with open(path) as f:
    src = f.read()
if "MICROPY_NLR_SETJMP" not in src:
    src = src.replace(
        "#define MICROPY_ALLOC_PATH_MAX                  (128)",
        """#define MICROPY_ALLOC_PATH_MAX                  (128)

// Use newlib setjmp/longjmp for NLR instead of the hand-written thumb asm.
// v1.18's nlr_thumb.c miscompiles/misbehaves under arm-gcc 15.2: raising
// ANY exception delivered a constant-garbage nlr.ret_val and HardFaulted in
// mp_obj_exception_add_traceback (gopiv 2026-08-14, reproduced on an
// otherwise stock build; also the vevov spike's \"exception paths wedge\").
#define MICROPY_NLR_SETJMP                      (1)""")
    with open(path, "w") as f:
        f.write(src)
    print("  MICROPY_NLR_SETJMP=1 applied")
else:
    print("  MICROPY_NLR_SETJMP already set")
PYEOF

echo "=== Step 4: Apply GCC 12+ / Clang compiler compat fixes ==="
# Suppress -Wdangling-pointer (GCC 15 rejects MicroPython's volatile stack
# trick in stackctrl.c with -Werror).
python3 - << 'PYEOF'
path = "micropython-microbit-v2/src/codal_port/Makefile"
with open(path) as f:
    src = f.read()
old = "CWARN = -Wall -Werror"
new = "CWARN = -Wall -Werror -Wno-dangling-pointer"
if old in src and "-Wno-dangling-pointer" not in src:
    with open(path, 'w') as f:
        f.write(src.replace(old, new))
    print("  Added -Wno-dangling-pointer to codal_port/Makefile")
else:
    print("  codal_port/Makefile already patched")
PYEOF

if [ "$WITH_YIELD" -eq 1 ]; then
  echo "=== Step 5: Apply yield + GC-hook patch ==="
  python3 patches/apply_yield.py || echo "WARN: yield patch already applied"
fi

if [ "$WITH_MODROBOT" -eq 1 ]; then
  echo "=== Step 6: Wire in modrobot C++ module ==="
  cp modrobot/modrobot.cpp "$MP_DIR/src/codal_port/modrobot.cpp"
  cp modrobot/modrobot_glue.c "$MP_DIR/src/codal_port/modrobot_glue.c"
  cp modrobot/wifi_stdio.cpp "$MP_DIR/src/codal_app/wifi_stdio.cpp"
  cp modrobot/wifi_stdio.h "$MP_DIR/src/codal_app/wifi_stdio.h"
  ROBOT_CONFIG="${ROBOT_CONFIG:-data/robots/gopiv.json}" python3 ../src/scripts/gen_boot_config.py
  ROBOT_CONFIG="${ROBOT_CONFIG:-data/robots/gopiv.json}" python3 - <<'PYEOF'
import json
import os
from pathlib import Path

repo = Path.cwd().parent
robot_path = os.environ.get("ROBOT_CONFIG", "data/robots/gopiv.json")
robot = Path(robot_path)
if not robot.is_absolute():
    robot = repo / robot_path
cfg = json.loads(robot.read_text())
conn = cfg.get("connection", {})
ssid = str(conn.get("wifi_ssid", "") or "")
ip = str(conn.get("wifi_ip", "") or "")
gateway = str(conn.get("wifi_gateway", "") or "")
netmask = str(conn.get("wifi_netmask", "") or "")
port = int(conn.get("wifi_port", 7654) or 7654)
channel = int(conn.get("wifi_jack", 0) or 0)
baud = int(conn.get("wifi_baud", 115200) or 115200)
password = ""
secrets_path = repo / "config" / "wifi_secrets.json"
if secrets_path.exists() and ssid:
    secrets = json.loads(secrets_path.read_text())
    networks = secrets.get("networks") if isinstance(secrets, dict) else None
    if isinstance(networks, dict):
        password = str(networks.get(ssid, "") or "")

def c_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\"')

out = Path("micropython-microbit-v2/src/codal_app/wifi_stdio_config.h")
content = "\n".join([
    "#pragma once",
    "",
    f'constexpr char kWifiStdioSsid[33] = "{c_string(ssid)}";',
    f'constexpr char kWifiStdioPassword[64] = "{c_string(password)}";',
    f'constexpr char kWifiStdioIp[16] = "{c_string(ip)}";',
    f'constexpr char kWifiStdioGateway[16] = "{c_string(gateway)}";',
    f'constexpr char kWifiStdioNetmask[16] = "{c_string(netmask)}";',
    f'constexpr unsigned short kWifiStdioPort = {port};',
    f'constexpr unsigned char kWifiStdioChannel = {channel};',
    f'constexpr unsigned int kWifiStdioBaud = {baud};',
    "",
])
out.write_text(content)
print("  wifi_stdio_config.h refreshed")
PYEOF

  python3 - << 'PYEOF'
# Patch Makefile: add firmware includes, CXX+C sources, CXXFLAGS, OBJ rule, QSTR_DEFS
path = "micropython-microbit-v2/src/codal_port/Makefile"
with open(path) as f:
    src = f.read()

changed = False

# 1. Add firmware include path
if "INC += -I$(abspath ../../../../src/firm)" not in src:
    src = src.replace(
        "INC += -I$(TOP)\n",
        "INC += -I$(TOP)\nINC += -I$(abspath ../../../../src/firm)\n"
    )
    changed = True

# 2. Add modrobot_glue.c to SRC_C and full SRC_CXX block with sensor sources
if "modrobot_glue.c" not in src:
    src = src.replace(
        "$(abspath $(LOCAL_LIB_DIR)/sam/debug.c) \\\n\n",
        "$(abspath $(LOCAL_LIB_DIR)/sam/debug.c) \\\n\tmodrobot_glue.c \\\n\nSRC_CXX += \\\n\tmodrobot.cpp \\\n\t$(abspath ../../../../src/firm/hardware/nezha/nezha_motor.cpp) \\\n\t$(abspath ../../../../src/firm/hardware/generic/real_otos.cpp) \\\n\t$(abspath ../../../../src/firm/hardware/planetx/color_sensor.cpp) \\\n\t$(abspath ../../../../src/firm/hardware/planetx/line_sensor.cpp) \\\n\n"
    )
    changed = True

# 3. Add CXXFLAGS and OBJ rule for SRC_CXX (must come after OBJ = $(PY_O))
if "CXXFLAGS =" not in src:
    src = src.replace(
        "OBJ = $(PY_O)\n",
        "CXXFLAGS = $(INC) -std=gnu++20 $(CFLAGS_ARCH) $(COPT) $(CFLAGS_EXTRA) -fno-rtti -fno-exceptions -Wno-register -Wno-deprecated\nOBJ = $(PY_O)\n"
    )
    changed = True

# 4. Add OBJ += SRC_CXX (after OBJ += LIB_SRC_C line)
if "$(SRC_CXX:.cpp=.o)" not in src:
    src = src.replace(
        "OBJ += $(addprefix $(BUILD)/, $(LIB_SRC_C:.c=.o))\n",
        "OBJ += $(addprefix $(BUILD)/, $(LIB_SRC_C:.c=.o))\nOBJ += $(addprefix $(BUILD)/, $(SRC_CXX:.cpp=.o))\n"
    )
    changed = True

# 5. Add qstrdefs_robot.h to QSTR_DEFS
if "qstrdefs_robot.h" not in src:
    src = src.replace(
        "QSTR_DEFS = qstrdefsport.h",
        "QSTR_DEFS = qstrdefsport.h qstrdefs_robot.h"
    )
    changed = True

with open(path, 'w') as f:
    f.write(src)
if changed:
    print("  Makefile patched for modrobot C++ build")
else:
    print("  codal_port/Makefile already patched")
PYEOF

  python3 - <<'PYEOF'
path = "micropython-microbit-v2/src/codal_port/Makefile"
with open(path) as f:
    src = f.read()
if "../../../../src/firm/config/boot_config.cpp" not in src:
    src = src.replace(
        "\tmodrobot.cpp \\\n",
        "\tmodrobot.cpp \\\n\t$(abspath ../../../../src/firm/config/boot_config.cpp) \\\n\t$(abspath ../../../../src/firm/messages/wire.cpp) \\\n\t$(abspath ../../../../src/firm/messages/wire_runtime.cpp) \\\n\t$(abspath ../../../../src/firm/platform/microbit/microbit_uart.cpp) \\\n"
    )
src = src.replace("\t$(abspath ../../../../src/firm/platform/microbit/microbit_uart.cpp) \\n", "")
src = src.replace("	$(abspath ../../../../src/firm/platform/microbit/microbit_uart.cpp) \
", "")
with open(path, "w") as f:
    f.write(src)
print("  codal_port/Makefile refreshed for Wi-Fi support sources")
PYEOF

  python3 - <<'PYEOF'
path = "micropython-microbit-v2/src/codal_port/Makefile"
with open(path) as f:
    src = f.read()
src = src.replace('-std=c++14', '-std=gnu++20')
with open(path, 'w') as f:
    f.write(src)
print("  codal_port/Makefile CXX standard refreshed")
PYEOF
  # Write qstrdefs_robot.h with the robot module's qstr identifiers
  cat > "$MP_DIR/src/codal_port/qstrdefs_robot.h" << 'QEOF'
// qstrdefs_robot.h -- qstrs for the built-in robot module
Q(robot)
Q(drive)
Q(move)
Q(turn)
Q(go_to)
Q(move_wheels)
Q(set_wheels)
Q(stop)
Q(encoders)
Q(otos)
Q(line)
Q(color)
Q(servo)
Q(enter_v5)
Q(wifi_status)
Q(ping)
Q(tlm)
QEOF
  echo "  qstrdefs_robot.h refreshed"

  python3 - << 'PYEOF'
# Patch mpconfigport.h
path = "micropython-microbit-v2/src/codal_port/mpconfigport.h"
with open(path) as f:
    src = f.read()
if "robot_module" not in src:
    src = src.replace(
        "extern const struct _mp_obj_module_t utime_module;",
        "extern const struct _mp_obj_module_t robot_module;\nextern const struct _mp_obj_module_t utime_module;"
    )
    src = src.replace(
        "#define MICROPY_PORT_BUILTIN_MODULES \\\n",
        "#define MICROPY_PORT_BUILTIN_MODULES \\\n    { MP_ROM_QSTR(MP_QSTR_robot), MP_ROM_PTR(&robot_module) }, \\\n"
    )
    with open(path, 'w') as f:
        f.write(src)
    print("  robot_module registered in mpconfigport.h")
else:
    print("  robot_module already registered")
PYEOF

  python3 - <<'PYEOF'
path = "micropython-microbit-v2/src/codal_app/mphalport.cpp"
with open(path) as f:
    src = f.read()
if "#include \"wifi_stdio.h\"" not in src:
    src = src.replace('#include "microbithal.h"\n', '#include "microbithal.h"\n#include "wifi_stdio.h"\n')
if 'extern "C" void mp_sched_keyboard_interrupt(void);' not in src:
    src = src.replace('extern "C" void mp_handle_pending(bool);\n', 'extern "C" void mp_handle_pending(bool);\nextern "C" void mp_sched_keyboard_interrupt(void);\n')
if 'extern "C" void robot_v5_service(void);' not in src:
    src = src.replace('extern "C" void mp_sched_keyboard_interrupt(void);\n', 'extern "C" void mp_sched_keyboard_interrupt(void);\nextern "C" void robot_v5_service(void);\n')
src = src.replace("""uintptr_t mp_hal_stdio_poll(uintptr_t poll_flags) {
    uintptr_t ret = 0;
    if (poll_flags & MP_STREAM_POLL_RD) {
        if (uBit.serial.isReadable()) {
            ret |= MP_STREAM_POLL_RD;
        }
    }
    if (poll_flags & MP_STREAM_POLL_WR) {
        if (uBit.serial.isWriteable()) {
            ret |= MP_STREAM_POLL_WR;
        }
    }
    return ret;
}
""", """uintptr_t mp_hal_stdio_poll(uintptr_t poll_flags) {
    uintptr_t ret = 0;
    RobotWifi::service();
    RobotWifi::flushOutput();
    robot_v5_service();
    if (poll_flags & MP_STREAM_POLL_RD) {
        if (uBit.serial.isReadable() || RobotWifi::readable()) {
            ret |= MP_STREAM_POLL_RD;
        }
    }
    if (poll_flags & MP_STREAM_POLL_WR) {
        if (uBit.serial.isWriteable() || RobotWifi::connected()) {
            ret |= MP_STREAM_POLL_WR;
        }
    }
    return ret;
}
""")
src = src.replace("""void mp_hal_stdout_tx_strn(const char *str, size_t len) {
    uBit.serial.send((uint8_t*)str, len, SYNC_SPINWAIT);
}
""", """void mp_hal_stdout_tx_strn(const char *str, size_t len) {
    // USB first, blocking: ASYNC-behind-isWriteable() silently DROPPED any
    // string that didn't fit the TX buffer, which truncated long prints and
    // broke mpremote's raw-REPL handshake mid-banner.
    uBit.serial.send((uint8_t*)str, len, SYNC_SPINWAIT);
    RobotWifi::service();
    RobotWifi::writeToSocket(reinterpret_cast<const uint8_t*>(str), len);
}
""")
src = src.replace("""int mp_hal_stdin_rx_chr(void) {
    for (;;) {
        while (!uBit.serial.isReadable()) {
            mp_handle_pending(true);
            microbit_hal_idle();
        }
        int c = uBit.serial.read(SYNC_SPINWAIT);
        if (c == last_interrupt_char && num_interrupt_chars) {
            --num_interrupt_chars;
        } else {
            return c;
        }
    }
}
""", """int mp_hal_stdin_rx_chr(void) {
    for (;;) {
        while (!RobotWifi::readable() && !uBit.serial.isReadable()) {
            // Main context: the ONLY places the Wi-Fi bridge (RobotWifi::
            // service()/flushOutput()) runs are here and mp_hal_stdio_poll --
            // never VM/GC hooks or event handlers. The REPL sits in this loop
            // exactly when its output burst is complete, so echo + result +
            // prompt leave as one send. robot_v5_service() is the one
            // exception: it ALSO runs from microbit_hal_background_processing
            // (the VM hook) -- safe only because it carries its own
            // reentrancy guard and never calls RobotWifi::service() itself.
            RobotWifi::service();
            RobotWifi::flushOutput();
            robot_v5_service();
            mp_handle_pending(true);
            microbit_hal_idle();
        }
        // Drain Wi-Fi bytes whenever they exist -- NOT gated on connected().
        // Buffered bytes with no live client otherwise make readable() true
        // while this branch is skipped, and the for(;;) busy-spins without
        // ever reaching microbit_hal_idle()/service(): the Wi-Fi state
        // machine freezes and the board never joins when running headless.
        {
            uint8_t c = 0;
            if (RobotWifi::read(&c, 1) == 1) {
                // Interactive TCP clients (nc, raw telnet) send bare LF as
                // Enter, but this MicroPython's readline only acts on CR --
                // bare-LF input was echoed and NEVER EXECUTED (gopiv
                // 2026-08-14: Eric's nc sessions echoed every line and ran
                // none). Map LF->CR, and swallow the LF of a CRLF pair so
                // CRLF clients don't double-Enter.
                static uint8_t prevWifiChar = 0;
                const uint8_t raw = c;
                if (c == '\\n') {
                    if (prevWifiChar == '\\r') {
                        prevWifiChar = raw;
                        continue;
                    }
                    c = '\\r';
                }
                prevWifiChar = raw;
                if (last_interrupt_char != -1 && c == (uint8_t)last_interrupt_char) {
                    mp_sched_keyboard_interrupt();
                    continue;
                }
                return c;
            }
        }
        if (uBit.serial.isReadable()) {
            int c = uBit.serial.read(SYNC_SPINWAIT);
            if (c == last_interrupt_char && num_interrupt_chars) {
                --num_interrupt_chars;
                continue;
            }
            return c;
        }
    }
}
""")
with open(path, "w") as f:
    f.write(src)
print("  mphalport.cpp refreshed for Wi-Fi stdio")
PYEOF

  python3 - <<'PYEOF'
path = "micropython-microbit-v2/src/codal_app/microbithal.cpp"
with open(path) as f:
    src = f.read()
if "#include \"wifi_stdio.h\"" not in src:
    src = src.replace('#include "neopixel.h"\n', '#include "neopixel.h"\n#include "wifi_stdio.h"\n')
with open(path, "w") as f:
    f.write(src)
print("  microbithal.cpp include refreshed")
PYEOF

# background_processing pumps robot_v5_service() (the v5 UDP engine,
# modrobot.cpp) -- but NOT RobotWifi::service()/schedule(): a fiber switch
# from this VM/GC hook context still corrupts the heap, and robot_v5_service
# never calls RobotWifi::service() itself for exactly that reason. Its own
# reentrancy guard is what makes running it from here safe.
  python3 - <<'PYEOF'
# Idempotent against BOTH a pristine stock checkout (matches the stock text
# below) and an already-patched one (skipped once "robot_v5_service" is
# present anywhere in the file, whether from this step or an earlier
# hand-edit that predated it -- two earlier sessions broke this file's
# build.sh patch by editing the WORKING TREE without updating the matching
# patch step here, which is exactly the drift this guard is for).
path = "micropython-microbit-v2/src/codal_app/microbithal.cpp"
with open(path) as f:
    src = f.read()
if "robot_v5_service" not in src:
    src = src.replace(
        """#include "microbithal.h"

void microbit_hal_background_processing(void) {
    // This call takes about 200us.
    Event(DEVICE_ID_SCHEDULER, DEVICE_SCHEDULER_EVT_IDLE);
}
""", """#include "microbithal.h"

extern void robot_v5_service(void);

void microbit_hal_background_processing(void) {
    // STOCK semantics -- fire the idle event only. This runs from the VM
    // hook (every N bytecodes), so nothing here may switch fibers or touch
    // the Wi-Fi bridge: the vevov-era schedule() call (added for a kernel
    // fiber this build does not run) and the RobotWifi::service() call both
    // belong in main-context call sites (mp_hal_stdin_rx_chr's wait loop,
    // mp_hal_stdio_poll), where they now live.
    // robot_v5_service() runs on the main fiber from BOTH this VM hook and
    // idle (there is no separate GC hook in this build) -- its own
    // reentrancy guard is what makes that safe. It keeps the v5 UDP plane
    // (protocol-v5 over the dedicated ESP-AT link, modrobot.cpp) alive
    // while Python code runs, independent of whether the interactive TCP
    // REPL is also in use.
    robot_v5_service();
    // This call takes about 200us.
    Event(DEVICE_ID_SCHEDULER, DEVICE_SCHEDULER_EVT_IDLE);
}
""")
    with open(path, "w") as f:
        f.write(src)
    print("  microbit_hal_background_processing patched to pump robot_v5_service()")
else:
    print("  microbit_hal_background_processing already pumps robot_v5_service()")
PYEOF

  python3 - <<'PYEOF'
# microbit_hal_poll_ctrl_c: non-blocking Ctrl-C scan modrobot's drive loops
# use. Append to microbithal.cpp if a fresh clone lacks it.
path = "micropython-microbit-v2/src/codal_app/microbithal.cpp"
with open(path) as f:
    src = f.read()
if "microbit_hal_poll_ctrl_c" not in src:
    src = src.replace(
        "void microbit_hal_reset(void) {",
        """extern "C" bool microbit_hal_poll_ctrl_c(void) {
    if (!uBit.serial.isReadable()) {
        return false;
    }
    int c = uBit.serial.read(ASYNC);
    return (c == 3);
}

void microbit_hal_reset(void) {""")
    with open(path, "w") as f:
        f.write(src)
    print("  microbit_hal_poll_ctrl_c added")
else:
    print("  microbit_hal_poll_ctrl_c already present")
PYEOF
fi

echo "=== Step 7: Pre-build mpy-cross (host tool) with Clang compat flags ==="
# mpy-cross is the host-side Python cross-compiler. On macOS with Clang, the
# -Werror in its Makefile fails on several Clang-specific warnings that GCC
# accepts. Build it separately without -Werror before the main build.
(cd "$MP_DIR/lib/micropython/mpy-cross" && \
  make CWARN="-Wall -Wno-unused-parameter -Wpointer-arith" 2>&1 | tail -3) \
  && echo "  mpy-cross built OK" \
  || echo "  WARN: mpy-cross build failed -- frozen modules will not compile"

echo "=== Step 8: cmake 4.x compat: add policy version minimum to src/Makefile ==="
python3 - << 'INNERPY'
path = "micropython-microbit-v2/src/Makefile"
with open(path) as f:
    src = f.read()
old = "(cd $(BUILD) && cmake ../$(CODAL_DIR) -DCMAKE_BUILD_TYPE=MinSizeRel)"
new = "(cd $(BUILD) && cmake ../$(CODAL_DIR) -DCMAKE_BUILD_TYPE=MinSizeRel -DCMAKE_POLICY_VERSION_MINIMUM=3.5)"
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  Added -DCMAKE_POLICY_VERSION_MINIMUM=3.5 to cmake invocations in src/Makefile")
else:
    print("  cmake policy flag already present in src/Makefile")
INNERPY

echo "=== Step 9: ARM_GCC toolchain: suppress macOS -arch flag ==="
# cmake on macOS injects -arch <host> into cross-compile flags unless the
# toolchain declares CMAKE_SYSTEM_NAME Generic (non-macOS target).
python3 - << 'INNERPY'
path = "micropython-microbit-v2/lib/codal/utils/cmake/toolchains/ARM_GCC/toolchain.cmake"
with open(path) as f:
    src = f.read()
if "CMAKE_SYSTEM_NAME" not in src:
    fix = "set(CMAKE_SYSTEM_NAME Generic)\nset(CMAKE_SYSTEM_PROCESSOR ARM)\n"
    src = src.replace('set(CMAKE_OSX_SYSROOT "/")', fix + 'set(CMAKE_OSX_SYSROOT "/")')
    src = src.replace('set(CMAKE_OSX_ARCHITECTURES "" CACHE STRING "" FORCE)', '')
    with open(path, "w") as f:
        f.write(src)
    print("  Added CMAKE_SYSTEM_NAME Generic to ARM_GCC toolchain.cmake")
else:
    print("  ARM_GCC toolchain.cmake already patched")
INNERPY

echo "=== Step 10: CortexContextSwitch.s: add .thumb_func annotations (GCC 15 strict ld) ==="
python3 - << 'INNERPY'
path = "micropython-microbit-v2/lib/codal/libraries/codal-nrf52/asm/CortexContextSwitch.s"
with open(path) as f:
    src = f.read()
funcs = ["swap_context", "save_context", "save_register_context", "restore_register_context"]
changed = False
for fn in funcs:
    label = f"\n{fn}:\n"
    annotated = f"\n    .thumb_func\n{fn}:\n"
    if label in src and f"    .thumb_func\n{fn}:" not in src:
        src = src.replace(label, annotated)
        changed = True
if changed:
    with open(path, "w") as f:
        f.write(src)
    print("  Added .thumb_func annotations to CortexContextSwitch.s (GCC 15 linker fix)")
else:
    print("  CortexContextSwitch.s already patched")
INNERPY

echo "=== Step 11: addlayouttable.py: parse RAM (0x20) symbol addresses ==="
python3 - << 'INNERPY'
path = "micropython-microbit-v2/src/addlayouttable.py"
with open(path) as f:
    src = f.read()
old = '            elif parse_symbols and line.startswith("0x00"):'
new = '            elif parse_symbols and (line.startswith("0x00") or line.startswith("0x20")):'
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  Fixed addlayouttable.py to also parse 0x20 (RAM) symbol addresses")
else:
    print("  addlayouttable.py already patched")
INNERPY

echo "=== Step 12: addlayouttable.py: make the SoftDevice layout row conditional ==="
# _binary_softdevice_bin_start only exists in the map when DEVICE_BLE=1 links
# a SoftDevice; this no-SD build never defines it. Re-applied per the real
# Gate 2 plan (docs/handoff/micropython-full-firmware-integration.md section
# 9's recommended path) -- same shape as the hand-relink attempt that was
# reverted 2026-08-15, now paired with the codal-library upgrade (Step 1b)
# instead of a raw ld-file swap against the OLD pinned codal-microbit-v2.
python3 - << 'INNERPY'
path = "micropython-microbit-v2/src/addlayouttable.py"
with open(path) as f:
    src = f.read()
changed = False

old_symbols = '''    sd_start = symbols["_binary_softdevice_bin_start"]
    sd_end = symbols["__isr_vector"]'''
new_symbols = '''    # _binary_softdevice_bin_start only exists when DEVICE_BLE=1 links the
    # SoftDevice; a no-SD build (this MicroPython overlay) never defines it,
    # so it is optional -- treat its absence as "no SoftDevice region" rather
    # than crashing on a None subtraction.
    sd_start = symbols["_binary_softdevice_bin_start"]
    sd_end = symbols["__isr_vector"]'''
# Guard every replacement on the TARGET (new) text being absent, not just
# the old text being present: `old_region`'s search string is a 4-space-
# indented line, which is also a substring of the already-patched 8-space-
# indented line (Python `in` is substring-based, not line-based), so an
# old-text-only guard double-applies on a file that is already patched --
# reproduced 2026-08-15, corrupted addlayouttable.py with a duplicated,
# mis-indented `if sd_start is not None:` block. Verified fixed by adding
# the new-text-absent half of each guard below.
if old_symbols in src and new_symbols not in src:
    src = src.replace(old_symbols, new_symbols)
    changed = True

old_region = '''    layout.add_region(1, sd_start, sd_end - sd_start, FlashLayout.REGION_HASH_NONE)
    layout.add_region(
        2, mp_start, mp_end - mp_start, FlashLayout.REGION_HASH_PTR, mp_version
    )'''
new_region = '''    if sd_start is not None:
        layout.add_region(1, sd_start, sd_end - sd_start, FlashLayout.REGION_HASH_NONE)
    layout.add_region(
        2, mp_start, mp_end - mp_start, FlashLayout.REGION_HASH_PTR, mp_version
    )'''
if old_region in src and new_region not in src:
    src = src.replace(old_region, new_region)
    changed = True

old_print = '''        fmt = "{:13} 0x{:05x}..0x{:05x}"
        print(fmt.format("SoftDevice", sd_start, sd_end))
        print(fmt.format("MicroPython", mp_start, mp_end))'''
new_print = '''        fmt = "{:13} 0x{:05x}..0x{:05x}"
        if sd_start is not None:
            print(fmt.format("SoftDevice", sd_start, sd_end))
        else:
            print("SoftDevice    none (DEVICE_BLE=0, no-SoftDevice link)")
        print(fmt.format("MicroPython", mp_start, mp_end))'''
if old_print in src and new_print not in src:
    src = src.replace(old_print, new_print)
    changed = True

if changed:
    with open(path, "w") as f:
        f.write(src)
    print("  addlayouttable.py: SoftDevice row made conditional")
else:
    print("  addlayouttable.py already patched (SoftDevice row already conditional)")
INNERPY

echo "=== Step 13: src/Makefile: drop the now-redundant neopixel timing patch call ==="
# neopixel_ws2812b_timing.patch no longer applies: the standard-repo SHA
# codal-nrf52 was upgraded to (Step 1b) already carries this exact fix
# (inc/WS2812B.h: WS2812B_LOW=0x8000|5, WS2812B_HIGH=0x8000|12,
# WS2812B_PWM_FREQ=800000) -- `git apply` on the patch fails with "patch does
# not apply" (verified against the new codal-nrf52) because the "before"
# context it expects is gone. Dropping the call is a pure no-op on the
# resulting binary since the values match; it only stops `make codal_build`
# aborting on an unappliable patch.
python3 - << 'INNERPY'
path = "micropython-microbit-v2/src/Makefile"
with open(path) as f:
    src = f.read()
old = """codal_build: libmicropython
	$(call CODAL_PATCH)
	$(call CODAL_LIBRARIES_CODAL_NRF52_PATCH)
	make -C $(BUILD)
	$(call CODAL_LIBRARIES_CODAL_NRF52_CLEAN)
	$(call CODAL_CLEAN)
	arm-none-eabi-size $(CODAL_BUILD)/MICROBIT
	$(PYTHON) addlayouttable.py $(SRC_HEX) $(SRC_MAP) -o $(DEST_HEX)"""
new = """codal_build: libmicropython
	$(call CODAL_PATCH)
	make -C $(BUILD)
	$(call CODAL_CLEAN)
	arm-none-eabi-size $(CODAL_BUILD)/MICROBIT
	$(PYTHON) addlayouttable.py $(SRC_HEX) $(SRC_MAP) -o $(DEST_HEX)"""
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  src/Makefile: neopixel timing patch call removed from codal_build")
elif new in src:
    print("  src/Makefile already patched")
else:
    print("  WARNING: src/Makefile codal_build recipe shape not recognized -- check manually")
INNERPY

echo "=== Step 13b: microbithal.cpp: MicroBitIO.face renamed to .logo upstream ==="
# API drift from the real Gate 2 codal-microbit-v2 upgrade: model/MicroBitIO.h
# renamed the touch-sensitive logo-pad field from `face` to `logo` (still
# P1_04 / MICROBIT_PIN_LOGO_TOUCH -- a pure rename, no behavioral change).
# Stock MicroPython port file, not modrobot-specific, so this runs
# unconditionally (not gated on --with-modrobot).
python3 - << 'INNERPY'
path = "micropython-microbit-v2/src/codal_app/microbithal.cpp"
with open(path) as f:
    src = f.read()
old = "    &uBit.io.face,"
new = "    &uBit.io.logo, // renamed from `face` in the standard codal-microbit-v2 upgrade (real Gate 2)"
if old in src:
    with open(path, "w") as f:
        f.write(src.replace(old, new))
    print("  microbithal.cpp: io.face -> io.logo")
elif new in src:
    print("  microbithal.cpp already patched")
else:
    print("  WARNING: microbithal.cpp pin_obj shape not recognized -- check manually")
INNERPY

echo "=== Step 14: Build ==="
# codal_cmake downloads CODAL libraries and configures cmake (first run only).
# codal_build compiles everything and links with libmicropython.a -> MICROBIT.hex
(cd "$MP_DIR/src" && make codal_cmake PYTHON=python3 2>&1 | tail -3)
(cd "$MP_DIR/src" && make codal_build PYTHON=python3 2>&1)

echo ""
echo "=== Done ==="
ls -lh "$MP_DIR/src/MICROBIT.hex" 2>/dev/null && echo "Hex ready." || echo "Hex not found -- check errors above."
echo ""
echo "Flash: cp $MP_DIR/src/MICROBIT.hex /Volumes/MICROBIT"
echo "REPL:  mpremote connect /dev/cu.usbmodemXXX"
