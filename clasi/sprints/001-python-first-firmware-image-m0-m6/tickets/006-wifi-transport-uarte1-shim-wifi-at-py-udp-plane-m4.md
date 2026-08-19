---
id: '006'
title: 'WiFi transport: UARTE1 shim + wifi_at.py + UDP plane (M4)'
status: open
use-cases: [UC-009, UC-010]
depends-on: ['001', '005']
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# WiFi transport: UARTE1 shim + wifi_at.py + UDP plane (M4)

## Description

C: a UARTE1 byte-pipe shim — the stock `micropython-microbit-v2` port
never exposes the second UARTE, and `microbit.uart.init(tx,rx)`
retargets the *one* stdio UART, so the WiFi UART needs its own tiny C
shim rather than reusing the stock API. Reuse the proven
`wifi_stdio.cpp` core pattern already present as a reference in
`reference/modrobot/{wifi_stdio.cpp,wifi_stdio.h}` for the stdio
TCP-REPL hook.

Python: `src/wifi_at.py`, an AT state machine (`CIPMUX=1`, UDP :7654)
with per-datagram coalescing — **one CIPSEND per datagram**, never
per-character (the landmine-ledger item: per-char AT sends flood the
module) — and a ≥50 ms telemetry throttle specific to this plane
(spec §8). The UDP v5 plane feeds the **same** `src/comms.py` engine
from ticket 005, not a second protocol engine; READY is handled on
new-peer edge inside the pump.

## Acceptance Criteria

All criteria are offline. `wifi_bench_gate.py --port wifi:
--skip-drive` 9/9 with a live, held-open `nc` REPL session moves to
ticket 009's documented stakeholder procedure — including the
power-cycle-the-module discipline (the WiFi module persists state
across nRF reflashes).

- [ ] `./build.sh --clean` with the UARTE1 shim wired in (a new
      `--with-wifi` flag, or folded into `--with-diffdrive` if that's
      the cleaner seam — programmer's call, documented either way)
      exits 0, links cleanly, flash end still < `_fs_start`.
- [ ] `src/wifi_at.py`'s AT state machine is offline-testable against
      a mock/fake serial object (`tests/test_wifi_at.py`, `python3 -m
      pytest`), covering: `CIPMUX=1` sequencing, one-CIPSEND-per-
      datagram (assert the mock never receives a per-character send),
      the ≥50 ms TLM-throttle timer logic, and READY-on-new-peer-edge
      handling.
- [ ] `python3 -m py_compile src/wifi_at.py` passes; `mpy-cross
      src/wifi_at.py` lints clean.
- [ ] Source review confirms the WiFi UART is on a distinct UARTE1
      shim, not `microbit.uart.init(tx,rx)` (which would collide with
      the USB stdio REPL).
- [ ] Source review confirms the UDP v5 plane calls into `src/
      comms.py`'s existing dispatch entry point (ticket 005) rather
      than duplicating dispatch logic.

## Testing

- **Existing tests to run**: `tests/test_comms_loopback.py` (ticket
  005) should still pass unmodified — this ticket must not fork the
  engine.
- **New tests to write**: `tests/test_wifi_at.py`.
- **Verification command**: `python3 -m pytest tests/test_wifi_at.py`

## Implementation Plan

**Approach**: port the UARTE1 shim and stdio-hook core from
`reference/modrobot/wifi_stdio.cpp` (pattern reference, not a straight
copy — that file targeted the old modrobot module surface). Build
`wifi_at.py`'s AT state machine against a mock serial object for
offline testing, matching the one-CIPSEND-per-datagram and throttle
requirements from the landmine ledger.

**Files to create/modify**: native C shim (location under `native/`,
alongside ticket 004's module or as its own translation unit —
programmer's call), `src/wifi_at.py`, `tests/test_wifi_at.py`, a
`--with-wifi` (or merged) `build.sh` flag.

**Testing plan**: as listed in Acceptance Criteria.

**Documentation updates**: note in `src/wifi_at.py`'s module docstring
the power-cycle discipline requirement (bench-time note, expanded fully
in ticket 009's procedures doc).
