# nezha-upy

MicroPython-first firmware for micro:bit V2 + ElecFreaks Nezha robots:
**everything is Python** — drivers, boot, config, telemetry, motion, the
v5 protocol engine — **except the differential drive**, which is the
vendored C++ DiffDrive kernel running on its own CODAL fiber at 24 ms.

The full execution plan, architecture, milestone ladder (M0–M7), and
verification gates are in [PLAN.md](PLAN.md). Agent orientation and
repo conventions are in [CLAUDE.md](CLAUDE.md).

## Build prerequisites

```
brew install --cask gcc-arm-embedded   # arm-none-eabi-gcc in PATH
brew install cmake python3
pip3 install --user --break-system-packages intelhex
```

`intelhex` (used by `addlayouttable.py`) is not self-bootstrapped by
`build.sh` — install it once per machine. Homebrew's Python is
PEP 668 externally-managed, so a plain `pip3 install intelhex` refuses
with an `externally-managed-environment` error; `--user
--break-system-packages` installs to user site-packages (on `python3`'s
default import path) without touching the Homebrew-managed environment,
per pip's own recommended override.

`micropython-microbit-v2/` (the upstream checkout `build.sh` builds
over, pinned at commit `0697c6d`) does **not** need a manual clone —
`build.sh`'s first step clones and pins it automatically on first run
if absent, and is idempotent (a no-op) on every run after. It is
gitignored and never committed; `arm-none-eabi-gcc` and `cmake` must
already be on `PATH` as above.

## Layout

```
PLAN.md      the execution plan (mirrored from radio-robot's issue doc)
vendor/      DiffDrive kernel + Nezha motor leaf — SYNCED from
             radio-robot by src/scripts/sync_upy.py there; never edited
             here
tests/       golden-vector fixture (synced), CPython loopback tests
src/         the Python firmware        (built by milestones M2–M5)
native/      the C/C++ MicroPython module over the vendored kernel (M1)
build.sh, codal_overlay.json, patches/   forked MP build machinery (M0)
```

## Relationship to radio-robot

[radio-robot](https://github.com/League-Robotics/radio-robot) remains
the single source of the kernel (`src/firm/diffdrive/`, guarded by its
`src/tests/diffdrive/` suite), the Nezha leaf, the wire schema and its
code generator, and all host tooling (rogo, the bench scripts, the
relay). This repo consumes vendored copies and must keep them
sync-clean.

Secrets (`wifi_secrets.json`) are never committed — provide locally at
bench time; see `.gitignore`.
