---
status: in-progress
sprint: '001'
tickets:
- 001-001
- 001-002
- 001-003
- 001-004
- 001-005
- 001-006
- 001-007
- 001-009
---

# Complete nezha-upy development per PLAN.md (Python-first)

## Description

Complete development of the nezha-upy MicroPython image.

**Architecture decision (stakeholder, 2026-08-19):** this repo executes
**PLAN.md** — the Python-first rebuild (2026-08-18 stakeholder
decisions, "all fixed"): everything Python except the vendored
DiffDrive C++ kernel + NezhaMotor leaf + minimal shims. The originally
referenced plan,
[docs/micropython-full-firmware-in-the-image-gates-3-7.md](../../docs/micropython-full-firmware-in-the-image-gates-3-7.md)
(2026-08-15, full C++ firmware in the image), is **superseded as
architecture** — it described the radio-robot exploration worktree,
whose firmware sources (`src/firm/core`, `motion/`, `control/`,
`kinematics/`) are not in this repo. Its paid-for lessons carry
forward as constraints where applicable to the Python-first design:

- Rule-A-style AT-channel discipline (single-context WiFi access, one
  CIPSEND per datagram, ≥50 ms TLM throttle on the WiFi plane)
- the zero-only starvation watchdog (VM hook, >250 ms stall with
  wheels commanded → raw zero duty, retry ×2, latch a flag)
- the gopiv true-wiring fix (`left_port: 2, right_port: 1,
  fwd_sign_left: +1, fwd_sign_right: -1`) lands in the config data
- v5-over-USB excluded (REPL owns USB); config persistence via baked
  JSON at boot

Scope: PLAN.md milestones M0–M7 (M0 partially complete — repo seeded,
build machinery forked). Work milestones in risk order; M1
(moddiffdrive native module) is the highest-risk item. Offline
verification (golden vectors, CPython loopback, mpy-cross lint,
`build.sh --clean`) gates each ticket; hardware acceptance is performed
by the stakeholder on master (bench: tovez, radio channel 3, mbdeploy —
see
[test-on-microbit-tovez-radio-channel-3.md](test-on-microbit-tovez-radio-channel-3.md)).

The review findings in `docs/nezha-upy-review.md` (heap-corruption
mechanism closed; polling-idiom starvation case; visible watchdog;
step()-restructure exit; mpy-cross-is-lint / manifest freezing) are
incorporated into the project specification and must shape the M1/M2
gates.
