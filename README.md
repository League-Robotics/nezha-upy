# nezha-upy

MicroPython-first firmware for micro:bit V2 + ElecFreaks Nezha robots:
**everything is Python** — drivers, boot, config, telemetry, motion, the
v5 protocol engine — **except the differential drive**, which is the
vendored C++ DiffDrive kernel running on its own CODAL fiber at 24 ms.

The full execution plan, architecture, milestone ladder (M0–M7), and
verification gates are in [PLAN.md](PLAN.md). Agent orientation and
repo conventions are in [CLAUDE.md](CLAUDE.md).

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
