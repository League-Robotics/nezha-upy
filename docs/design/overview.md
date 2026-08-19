# nezha-upy — Project Overview

**One line:** a MicroPython-first firmware image for the micro:bit-based
Nezha robot — everything is Python except the proven C++ DiffDrive
kernel, which runs on its own CODAL fiber.

## What this is

nezha-upy inverts the radio-robot firmware around its one
measurement-derived core. The DiffDrive extraction in radio-robot proved
the pattern: a self-contained C++ kernel behind four small ports,
everything else replaceable. This repo rebuilds the robot firmware with
**MicroPython as the base**: drivers, boot, config, telemetry, motion
sequencing, and the v5 protocol engine are Python; the C++ payload is
the vendored `DiffDrive` kernel + `NezhaMotor` leaf + minimal shims —
nothing else.

The v5 wire protocol stays byte-for-byte compatible, so all existing
host tooling (rogo, relay, benches) works unchanged. Transports: v5 on
radio (primary), REPL on USB and WiFi, and the UDP v5 plane on WiFi.

## Why

- Students get a live REPL and Python-level hackability on the robot.
- The control law that took months of measurement to derive
  (`differential_drive.cpp`, anti-latch motor shaping) is vendored
  intact from radio-robot, never re-derived, and stays gated by
  radio-robot's own test suite.
- The prior MicroPython exploration (38 commits) paid for a landmine
  ledger (L1–L9) that this build inherits instead of rediscovering.

## Governing documents

- **`PLAN.md`** — the execution plan: architecture, milestones M0–M7
  (risk-ordered, each gate a command), stakeholder decisions
  (2026-08-18, fixed). Confirmed as governing by the stakeholder on
  2026-08-19.
- **`docs/design/specification.md`** — full consolidated specification
  (PLAN.md detail + the 2026-08-18 architecture review findings +
  bench/process decisions).
- **`docs/design/usecases.md`** — numbered use cases.
- `docs/micropython-full-firmware-in-the-image-gates-3-7.md` —
  **superseded as architecture** (2026-08-15 full-C++-firmware plan from
  the radio-robot exploration worktree); retained for its carried-over
  constraints.

## Ground rules

- `vendor/` is synced from radio-robot and never edited here.
- Offline verification before hardware, always. The stakeholder
  performs hardware acceptance on master (bench: micro:bit "tovez",
  radio channel 3, deploy with `mbdeploy`).
- No secrets in the repo (`wifi_secrets.json` gitignored, provided
  locally).
