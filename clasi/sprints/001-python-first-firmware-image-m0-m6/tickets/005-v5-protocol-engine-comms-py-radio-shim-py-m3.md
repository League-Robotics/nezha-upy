---
id: '005'
title: 'v5 protocol engine: comms.py + radio_shim.py (M3)'
status: open
use-cases: [UC-007, UC-008]
depends-on: ['003']
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# v5 protocol engine: comms.py + radio_shim.py (M3)

## Description

Port `src/comms.py`, mirroring radio-robot's `dispatchLine()` order
byte-for-byte: relay sigils dropped first; TLM/SEED/DBG intercepted
before the binary branch; TLM inbound is a cleartext mode verb.
Implement the ack ring (depth 12, packed `corr_id<<4|err`, 3 repeats)
and the telemetry emit policy (default AUTO = silent-while-parked,
25 ms period, pending acks force emission); the banner/boot/READY
sequence is byte-frozen.

Implement the scheduled-pump plumbing: a timer drives
`micropython.schedule(pump)`; the pump does bounded work per call,
sized against **~14 ms** of the ~24 ms kernel cycle (review §7.5 /
spec §7.5 correction — the real occupied cycle is ~10 ms, not the
documented `>= 2*kSettle + margin`, so size against the actual
available window, not the nominal 24 ms); a stdin-wait patch ensures
pending callbacks run while the REPL blocks so USB REPL stays
interactive throughout.

`src/radio_shim.py` wraps MicroPython's `radio` module (`length=250,
queue=4, channel=<from robot config>, group=10`) with fragment
reassembly per `microbit_radio_link.cpp`'s framing (`[SEQ][FLAGS]
[LEN]`, MTU 247).

Per the sprint's Architecture Design Rationale: `comms.py` must
dispatch into the firmware layer through an interface, not direct
`moddiffdrive` calls, so this ticket's own offline gate (a CPython
loopback test) doesn't require the native module, which can't load
under CPython at all. Define that dispatch interface here even though
the concrete firmware-layer modules (`motion.py`, etc.) don't exist
yet — ticket 007 backs it with the real implementation, this ticket's
test backs it with a stub.

## Acceptance Criteria

All criteria are offline. `rogo repl <robot> ping` via the relay with
unchanged host tooling, and WHEELS-over-radio hardware verification,
move to ticket 009's documented stakeholder procedure.

- [ ] A CPython loopback test (`tests/test_comms_loopback.py`, `python3
      -m pytest`) exercises `src/comms.py` against a host-side v5
      client built on ticket 003's `wire.py`/`msgs.py`, asserting
      byte-exact banner and ack sequences.
- [ ] The same test asserts dispatch order matches `dispatchLine()`:
      relay sigils dropped first; TLM/SEED/DBG intercepted before the
      binary branch.
- [ ] Ack-ring behavior (depth 12, `corr_id<<4|err` packing, 3 repeats)
      is asserted.
- [ ] Telemetry emit-policy defaults (AUTO, silent-while-parked, 25 ms
      period, ack-forces-emission) are asserted against a stubbed
      telemetry source.
- [ ] `src/radio_shim.py`'s fragment reassembly is unit-tested offline
      against synthetic/captured on-air byte sequences (`[SEQ][FLAGS]
      [LEN]` framing, MTU 247) without requiring radio hardware.
- [ ] The comms.py-to-firmware-layer dispatch interface is defined and
      exercised via a stub in the loopback test (no dependency on
      ticket 004's native module for this ticket's own gate).
- [ ] `python3 -m py_compile src/comms.py src/radio_shim.py` passes.
- [ ] `mpy-cross src/comms.py src/radio_shim.py` lints clean (labelled
      as a lint per review §4, same as ticket 003).

## Testing

- **Existing tests to run**:
  `tests/unit/test_wire_golden_vectors.py` (ticket 003) should still
  pass unmodified.
- **New tests to write**: `tests/test_comms_loopback.py`,
  `tests/test_radio_shim_fragments.py`.
- **Verification command**: `python3 -m pytest
  tests/test_comms_loopback.py tests/test_radio_shim_fragments.py`

## Implementation Plan

**Approach**: port `comms.py`'s dispatch logic from radio-robot's
`comms.cpp`/`telemetry.cpp` semantics into Python, built on `src/
wire.py`/`src/msgs.py` (ticket 003 — hence the dependency). Build the
CPython-side loopback harness as a host-side v5 client that talks to
`comms.py` over an in-process byte pipe, standing in for the real
serial/radio transport.

**Files to create/modify**: `src/comms.py`, `src/radio_shim.py`,
`tests/test_comms_loopback.py`, `tests/test_radio_shim_fragments.py`.

**Testing plan**: as listed in Acceptance Criteria.

**Documentation updates**: note the dispatch-interface contract (what
ticket 007's firmware-layer modules must implement) in a short
docstring or `src/README.md` section, since ticket 007 depends on it.
