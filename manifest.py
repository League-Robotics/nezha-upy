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

freeze(
    "../../../src",
    (
        "comms.py",
        "config.py",
        "line.py",
        "motion.py",
        "msgs.py",
        "otos.py",
        "radio_shim.py",
        "telemetry.py",
        "wifi_at.py",
        "wire.py",
    ),
)
