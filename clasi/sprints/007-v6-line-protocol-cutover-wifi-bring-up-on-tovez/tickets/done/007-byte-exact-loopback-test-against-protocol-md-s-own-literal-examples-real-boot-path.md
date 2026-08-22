---
id: '007'
title: Byte-exact loopback test against protocol.md's own literal examples (real boot
  path)
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-005
depends-on:
- '006'
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Byte-exact loopback test against protocol.md's own literal examples (real boot path)

## Description

The golden-vector harness (tickets 001–004) proves `protocol.py`
against a *mock* adapter — it never proves that `boot.py`/`comms.py`
actually wire the *real* `ProtocolAdapter` correctly. This ticket
closes that gap: an offline test that drives the real, boot-assembled
engine (real `Comms`, real `ProtocolHandler` instances, real
`ProtocolAdapter`, a **fake** `diffdrive` module standing in for
hardware — matching this repo's existing `tests/test_boot_sequence.py`
fake-injection convention) and asserts byte-exact output against
`protocol.md`'s own literal examples:

- `sendBanner()` → `device NEZHA2 robot <name> <serial>` (§3, §6).
- `PING` → `pong <now>` (§6, §10.2's cited literal REPL transcript, if
  reachable — otherwise the §6 table's own shape).
- A representative `ok #<id>` and `err #<id> <code>` pair (from a
  `WHEELS`/`STOP` round trip).
- `ID`/`VER`/`STATUS`/`HELP` replies, matching their §6 table row
  exactly (field names, `k=v` order not asserted where the spec says
  order isn't guaranteed — assert *presence* of each key, not
  position, for `STATUS`).

This is the one offline test in the sprint that proves the *wiring*
from ticket 006, not just the *class* from tickets 001–005 in
isolation — mirroring exactly the role `docs/bench-acceptance-
procedures.md`'s existing loopback-test convention plays for other
milestones in this repo.

## Acceptance Criteria

- [x] A test boots the engine with a fake `diffdrive` (no hardware),
      real `ProtocolAdapter`/`ProtocolHandler`/`Comms`, and feeds
      wire lines through a fake transport (matching the existing
      `RadioLink`/in-process-pipe test convention from
      `test_comms_loopback.py`).
- [x] Banner, `ok`/`err`/`id`-carrying reply shapes are asserted
      byte-exact against `protocol.md`'s own literal text, not
      against this port's own prior output (i.e., the assertion
      strings are transcribed from the design doc, not copy-pasted
      from a first passing run).
- [x] `python3 -m pytest tests/` green.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/`
- **New tests to write**: the byte-exact loopback test described
  above.
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Reuse `test_comms_loopback.py`'s existing fake-transport/
fake-diffdrive scaffolding pattern rather than inventing a new one —
this ticket's job is to point that same scaffolding at the new v6
engine and assert the new literal shapes, not to build new
infrastructure.

**Files to create/modify**:
- `tests/test_comms_loopback.py` (already updated for the new shape
  in ticket 006) — add the byte-exact assertions here, or a small
  sibling test file if that keeps the diff more reviewable.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket.
