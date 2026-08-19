---
status: in-progress
sprint: '001'
tickets:
- 001-002
- 001-009
---

# Test on micro:bit "tovez" using radio channel 3

## Description

Hardware testing for this project should run on the micro:bit named
**tovez**, using **radio channel 3**.


Use program `mbdeploy` to deploy the firmware to the micro:bit. 

This fixes the bench target and radio configuration for any
hardware-facing verification (e.g. the Gate 3–7 acceptance work in
[complete-gates-3-7-full-firmware-in-micropython-image.md](complete-gates-3-7-full-firmware-in-micropython-image.md)):
deploy to the device named tovez per the radio-robot bench conventions
(deploy by UID, `--clean` builds, ~5 s post-flash settle, power-cycle
the WiFi module), and configure the radio to channel 3 so tests don't
collide with other benches.
