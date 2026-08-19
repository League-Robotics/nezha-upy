---
id: '003'
title: Wire codec + msgs.py + golden-vector suite (M2)
status: open
use-cases: [UC-006]
depends-on: []
github-issue: ''
issue: complete-gates-3-7-full-firmware-in-micropython-image.md
completes_issue:
  complete-gates-3-7-full-firmware-in-micropython-image.md: false
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Wire codec + msgs.py + golden-vector suite (M2)

## Description

Port radio-robot's `src/host/robot_radio/io/wire_codec.py` to this
repo's `src/wire.py` nearly verbatim — it is already pure
MicroPython-clean Python per PLAN.md. Hand-seed `src/msgs.py` with a
`GENERATED — do not edit` header matching the same descriptor walk the
real generator (`gen_messages.py --emit-upy`, radio-robot-side, out of
scope this sprint per `docs/design/specification.md` §10.3) will
eventually produce.

Implement the golden-vector suite against the already-present
`tests/fixtures/wire_golden_vectors.txt` (8 cross-language vectors):
decode and encode all 8, and round-trip every binary verb. If
cross-checking against the host's pb2 messages requires read access to
radio-robot's `src/protos/` that isn't available in this environment,
scope the round-trip check to the fixture's own recorded expected
bytes and note the narrower scope explicitly — do not silently skip
the round-trip requirement.

Per `docs/nezha-upy-review.md` §4 (incorporated into
`docs/design/specification.md` §7.4): `micropython-microbit-v2` cannot
load `.mpy` from the filesystem
(`MICROPY_PERSISTENT_CODE_LOAD` unset). Label the `mpy-cross`
compilation step in this ticket's acceptance explicitly as a **lint**,
not a load-path proof — module shipping is `manifest.py` freezing,
which lands in ticket 007 (M5), not here.

Independent of the build (ticket 001) — this ticket is fully offline
under CPython and can run in parallel with 001.

## Acceptance Criteria

- [ ] `src/wire.py` exists, ported from `wire_codec.py`.
- [ ] `src/msgs.py` exists, carries a `GENERATED — do not edit` header.
- [ ] `python3 -m pytest tests/unit/test_wire_golden_vectors.py` is
      8/8 green against `tests/fixtures/wire_golden_vectors.txt`.
- [ ] The same suite asserts byte-exact encode/decode round-trips for
      every binary verb (against host pb2 if available; against the
      fixture's own recorded bytes otherwise, with the narrower scope
      noted in the test file).
- [ ] COBS keyed `0x0A` and CRC-16/CCITT-FALSE (computed over
      `command + ':' + payload`, CRC-then-COBS) match the fixture
      exactly.
- [ ] `python3 -m py_compile src/wire.py src/msgs.py` passes.
- [ ] `mpy-cross src/wire.py src/msgs.py` compiles clean — run and
      reported as a **lint** step (per review §4), with a one-line
      comment in the test output or README noting it does not prove
      on-device loadability.

## Testing

- **Existing tests to run**: none yet in this repo.
- **New tests to write**: `tests/unit/test_wire_golden_vectors.py`.
- **Verification command**: `python3 -m pytest
  tests/unit/test_wire_golden_vectors.py`

## Implementation Plan

**Approach**: port `wire_codec.py` with minimal changes (it's already
MicroPython-clean); hand-write `msgs.py` against the same message
descriptor `wire_codec.py`/the golden vectors imply, with the
generated-file header. Build the golden-vector test harness reading
`tests/fixtures/wire_golden_vectors.txt` directly.

**Files to create/modify**: `src/wire.py`, `src/msgs.py`,
`tests/unit/test_wire_golden_vectors.py`.

**Testing plan**: `python3 -m pytest
tests/unit/test_wire_golden_vectors.py`; `python3 -m py_compile`;
`mpy-cross` lint pass.

**Documentation updates**: note in `src/msgs.py`'s header that it will
be replaced by the real generator once `gen_messages.py --emit-upy`
lands in radio-robot.
