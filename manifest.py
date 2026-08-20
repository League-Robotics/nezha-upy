# manifest.py -- FROZEN_MANIFEST source for this repo's own Python
# firmware layer, M5 stabilisation (PLAN.md / docs/design/
# specification.md Sec 7.4, sprint 001 ticket 007).
#
# This file is TRACKED HERE (repo root, alongside build.sh/
# codal_overlay.json/patches/ -- the other project-owned build inputs)
# and copied verbatim by build.sh into
# `$MP_DIR/src/codal_port/manifest.py` (the gitignored, vendored
# micropython-microbit-v2 checkout's own FROZEN_MANIFEST target --
# codal_port/Makefile: `FROZEN_MANIFEST ?= manifest.py`) -- see
# build.sh's own "Freeze this repo's src/*.py modules" step. A straight
# `cp`, matching the established precedent for project-owned files that
# must land inside that gitignored checkout (build.sh's earlier
# `cp modrobot/modrobot.cpp "$MP_DIR/.../modrobot.cpp"` step).
#
# WHY freezing at all, and why HERE (not earlier): this port's
# micropython-microbit-v2 build does not define
# MICROPY_PERSISTENT_CODE_LOAD, so it cannot import `.mpy` from the
# filesystem at all -- module shipping is frozen bytecode compiled into
# ROM, not filesystem `.py`/`.mpy` files (spec Sec 7.4). Freezing costs
# a firmware rebuild+reflash per Python change, which would have slowed
# tickets 003-006's filesystem-based iteration -- so sprint 001's
# architecture decision (sprint.md "Freeze-point tradeoff") defers the
# switch to THIS ticket's stabilisation point, once every src/*.py
# module this sprint builds is stable. This is a ONE-WAY switch within
# the sprint: once frozen, further Python source changes need a full
# `./build.sh --clean` + reflash, not a filesystem copy.
#
# EVERY src/*.py module built so far is listed explicitly below (one
# name per line, not a directory-wide wildcard freeze) so that
# `tests/test_manifest_freeze.py`'s diff/grep check against the actual
# `src/` directory listing can catch a module silently left on the
# filesystem-only path -- this ticket's own acceptance criterion. The
# filesystem itself stays reserved for the robot JSON and student code
# (spec Sec 7.4: "reserve the ~30 KB filesystem for the robot JSON and
# student code").
#
# `neopixel.py` (the stock micropython-microbit-v2 default manifest's
# only frozen module -- `freeze("modules", "neopixel.py", opt=3)`) is
# deliberately DROPPED here: nothing in this project references it
# (grepped, confirmed), and every byte of frozen ROM is scarce on this
# build (MICROBIT_HEAP_SIZE is cut to 40 KB, spec Sec 7.4, to buy CODAL
# headroom) -- freezing unused stock example code has no upside here.
#
# `boot.py` (sprint 001 ticket 010) is frozen here like every other
# module -- NOT run automatically by virtue of being frozen (see its own
# module docstring: `micropython-microbit-v2`'s `mp_main()` only
# auto-execs a FILESYSTEM `main.py`, never a frozen one). `build.sh`'s
# own "Wire the frozen boot module into main.c's power-on sequence" step
# patches `main.c` to `mp_import_name()` this module and call its
# `run()` explicitly.
#
# `src/demo_square.py` (sprint 002 ticket 002) IS frozen below.
# It was deliberately absent for several sprints -- it is a bench demo
# SCRIPT, not a framework module -- and was added later. As of sprint 006 ticket 001, a bare `import demo_square` no
# longer auto-runs anything by itself (its own module docstring's
# "Auto-run trigger" section) -- production callers (src/main.py) call
# `demo_square.run()`/`run_single_leg()` explicitly. It remains off
# this freeze list regardless: freezing would need a full `--clean`
# rebuild+reflash unrelated to this ticket's own scope, and its
# standalone bench-debug entry point
# (`mpremote run src/demo_square.py`, source upload + execute) still
# needs no freezing at all. See that module's own docstring and
# `tests/test_manifest_freeze.py`'s `_BENCH_ONLY_MODULES` for the same
# reasoning encoded as a test.

# PACKAGE LAYOUT (out-of-process reorganisation, 2026-08-20): src/ is
# split into `core` (boot/protocol/transports/telemetry/config),
# `hardware` (drivetrain control) and `devices` (I2C sensors). The demo
# scripts stay at root: bench-measured, importing demo_square through a
# package costs enough heap at press time to fault the drive with
# MemoryError (3072 bytes) where a flat import drives cleanly.
# Each package's `__init__.py` MUST be frozen alongside its modules or
# the package is not importable at all on device.
#
# `src/boot.py` stays a root-level module and is frozen under the bare
# name `boot`: build.sh patches main.c to `mp_import_name(MP_QSTR_boot,
# mp_const_empty_tuple, 0)` at power-on, and an empty fromlist makes a
# dotted import return the top-level package rather than the submodule.
# It is a three-line shim re-exporting `core.boot.run`.

freeze(
    "../../../src",
    (
        "boot.py",
        "demo_square.py",
        "demo_util.py",
        "core/__init__.py",
        "core/boot.py",
        "core/comms.py",
        "core/config.py",
        "core/msgs.py",
        "core/radio_shim.py",
        "core/telemetry.py",
        "core/wifi_at.py",
        "core/wire.py",
        "hardware/__init__.py",
        "hardware/motion.py",
        "devices/__init__.py",
        "devices/line.py",
        "devices/otos.py",
    ),
)
