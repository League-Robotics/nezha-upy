---
status: pending
---

# Two boards announce the same robot identity; device map is stale

Two physically distinct micro:bits on the bench both identify as
`tovez`, and `config/devices.json` no longer matches reality. Bench
work cannot reliably tell which robot it is driving, and per-robot
wheel calibration is selected by that identity.

## Evidence (bench, 2026-08-20)

Connected boards, by DAPLink UID:

| UID (prefix) | devices.json says | Board actually says |
| --- | --- | --- |
| `...a8fdb5e413abb276` | tovez | on-device `robot.json`: `"robot_name":"tovez"` |
| `...b8e12372c44f4f67` | vevov | v5 `ID` verb: `ID:diffdrive:tovez:1.0.0` |
| `...17449eac613c0332` | getez (relay) | — |
| `...e9d16c3809a44554` | zavaz (relay) | — |

- Two boards claim `tovez`.
- zetuv's registered UID `...312bde85515a72e6` did not appear in any
  enumeration during the session, though the stakeholder reports zetuv
  is the robot on the bench — consistent with the bench robot having
  been flashed or configured with another robot's identity.
- `config/devices.json` `port` fields are stale (it lists tovez at
  `2121102` and vevov at `2121202`; neither matched). Port numbers churn
  across replug, so only the UIDs carry meaning — and the table above
  shows at least one UID mapping is also wrong.
- `data/active_robot.json` points at `data/robots/tovez.json`, but the
  configs live at `data/tovez.json`. That path does not resolve.

## Why this is more than cosmetic

Per-robot wheel calibration is selected by identity:

| config | ticks_per_rev | ticks_per_mm |
| --- | ---: | ---: |
| `data/zetuv.json` | 975 | 3.4484 |
| `data/tovez.json` | 3600 | 12.7602 |

The ratio is 3.70. Commit `6c5f57c` records commanded 500 mm driving
~150 mm — a 3.3x error of exactly this character. That commit's message
and its bench log (`docs/bench-log-zetuv-2026-08-19.md`) describe zetuv,
but the file it actually changed is `data/tovez.json`. A robot driving
one robot's config while carrying another's encoders reproduces this
class of failure, and it will recur silently on the next calibration
session.

Also: `data/vevov.json` does not exist at all, so a board mapped to
vevov has no config to load.

## Proposed work

1. Establish ground truth per board: read the on-device identity
   (`robot.json` over the filesystem, or the `ID` verb over serial)
   rather than trusting `config/devices.json`. This is the only check
   that proved reliable this session.
2. Resolve the collision: decide which physical chassis is zetuv and
   which is tovez, and re-deploy the correct `robot.json` to each.
3. Regenerate `config/devices.json` from live enumeration plus
   on-device identity. Consider dropping the `port` field entirely, or
   marking it advisory, since it is guaranteed to go stale.
4. Fix `data/active_robot.json`'s path, or the loader that reads it.
5. Guard rail: refuse to run a calibration or bench procedure when the
   on-device identity does not match the config file being applied.

Item 5 is the one that would have prevented the 3.3x error.

Related: [[tlm-stream-ignores-tlm-off]] — the telemetry flood is what
prevented identifying these boards by name in the first place.
