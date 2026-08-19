---
status: in-progress
sprint: '001'
tickets:
- 001-002
---

# Copy robot configurations from radio-robot-elite

## Description

Copy the robot configuration files from
`/Volumes/Proj/proj/RobotProjects/radio-robot-elite/data/robots` into
this repo to provide the parameters needed for configuration and
testing.

The source directory currently holds:

- `robot_config.schema.json` — the config schema
- `tovez.json` (and `tovez_nocal.json`) — the bench test target (see
  [test-on-microbit-tovez-radio-channel-3.md](test-on-microbit-tovez-radio-channel-3.md))
- `gopiv.json` — carries the true-wiring fix (`left_port: 2,
  right_port: 1, fwd_sign_left: +1, fwd_sign_right: -1`) that rides the
  Gate-5 flash per
  [complete-gates-3-7-full-firmware-in-micropython-image.md](complete-gates-3-7-full-firmware-in-micropython-image.md)
- `togov.json`
- `active_robot.json` — active-robot selector

These configs supply the baked-at-boot tuning parameters (config
persistence is disabled in the MicroPython image, so the baked JSON
rules at boot) and the per-robot wiring/calibration data used for
hardware testing. Decide during planning whether they are vendored
(synced like `vendor/`, with radio-robot-elite as the source of truth)
or copied once — the sync-not-edit convention for vendored content
suggests the former.
