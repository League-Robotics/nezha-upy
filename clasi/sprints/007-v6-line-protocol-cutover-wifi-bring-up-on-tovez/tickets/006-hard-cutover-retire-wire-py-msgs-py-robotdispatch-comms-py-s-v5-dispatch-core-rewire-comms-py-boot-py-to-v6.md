---
id: '006'
title: 'Hard cutover: retire wire.py/msgs.py/RobotDispatch/comms.py''s v5 dispatch
  core; rewire comms.py + boot.py to v6'
status: open
use-cases: [SUC-001, SUC-002, SUC-003, SUC-004]
depends-on: ['005']
github-issue: ''
issue: port-v6-line-protocol-hard-cutover-from-v5.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Hard cutover: retire wire.py/msgs.py/RobotDispatch/comms.py's v5 dispatch core; rewire comms.py + boot.py to v6

## Description

The cutover itself: the one ticket where the device stops being able
to run v5 at all. No dual-stack period — this ticket lands as one
unit.

**Delete**: `src/core/wire.py`, `src/core/msgs.py`,
`tests/unit/test_wire_golden_vectors.py`,
`tests/fixtures/wire_golden_vectors.txt`. Delete
`motion.RobotDispatch` and its `_handle_move`/`_handle_wheels`/
`_handle_stop`/`_handle_estop`/`_handle_go_to`/`_handle_calibrate`
methods (superseded by `ProtocolAdapter`, ticket 005) — leave
`motion.Move`/`MoveQueue`/the generator-driven move mode completely
untouched (per sprint.md scope: `MOVE`/`GO_TO`/`CALIBRATE` are out of
scope for v6 entirely; a later sprint rebuilds a motion API). Delete
`config.ConfigDispatch`'s binary `handle_command`/`_handle_set_field`/
`_handle_config`/`_handle_get_config`/`build_cfg_reply` (their
`wire.encode_frame()` dependency is gone) — keep the class itself and
ticket 005's new name-keyed accessors.

**Rewire `comms.py`**: slim `Comms` down to transport registration
and the scheduled-pump loop. Replace `_dispatch_line()`/
`_dispatch_cleartext()`/the ack ring/`TelemetryPolicy`/`DbgAction`/
`SeedRequest`/`Status`/`_send_status`/`_send_help`/`_send_pose`/
`_send_tlm_reply`/`_classify_tlm_arg`/`_classify_dbg_arg`/
`_parse_float_prefix`/`_parse_leading_uint` with: one
`protocol.ProtocolHandler` instance per registered transport, sharing
one `ProtocolAdapter` instance (sprint.md Design Rationale — this is
the load-bearing decision this ticket implements, not just tidies
around). `add_transport()` now also constructs and stores that
transport's own handler. `pump()`/`_pump_once()` becomes: for each
`(transport, handler)` pair, `line = transport.read_line()`; if not
`None`, `handler.feed(line + b"\n")` (feed() expects the terminator;
transports strip it — see sprint.md's note on why the multi-line
buffering in `feed()` isn't exercised by real transports today).
`send_banner()`/`send_ready()` iterate every handler, calling
`sendBanner()`/`sendReady()` on each (mirrors the old
`_broadcast_reliable` shape). Telemetry emission on the scheduled
cadence likewise iterates every handler.

**Rewire `boot.py`**: step 3 builds one `ProtocolAdapter` (backed by
the `MoveQueue`/`ConfigDispatch` step 2 already built) and passes it
to the new `Comms` constructor/wiring instead of the old
`RobotDispatch`. Update the banner string to v6's `device NEZHA2
robot <name> <serial>` (was `DEVICE:NEZHA2:robot:<name>:<serial>`) —
`_identity_lines()`'s docstring/format changes; the `id_line` format
also changes to v6's `id <drivetrain> <profile> <version>` shape
(served by the handler's `ID` verb now, not a static banner line
`boot.py` builds — confirm whether `boot.py` still needs to construct
an `id_line` string at all, or whether that's now entirely the
adapter's `identity()` responsibility called on demand; resolve
whichever is simpler and note the choice in this ticket's completion
notes).

**Update existing tests** for the new shape:
`tests/test_comms_loopback.py` (its `BANNER = "DEVICE:NEZHA2:..."`
fixture is now stale — update to v6's format), `tests/
test_boot_sequence.py` (asserts on `BootResult.dispatch`, which is
now a `ProtocolAdapter`, not a `RobotDispatch`), `tests/test_motion.py`
(drop `RobotDispatch`-specific tests; keep `MoveQueue`/`Move`/
generator-mode tests unchanged).

## Acceptance Criteria

- [ ] `src/core/wire.py`, `src/core/msgs.py`,
      `tests/unit/test_wire_golden_vectors.py`,
      `tests/fixtures/wire_golden_vectors.txt` deleted.
- [ ] `motion.RobotDispatch` and its six `_handle_*` methods deleted;
      `git diff` shows `motion.Move`/`MoveQueue`/generator-mode
      functions byte-identical.
- [ ] `config.ConfigDispatch`'s binary dispatch methods deleted; its
      name-keyed accessors (ticket 005) remain and are what
      `ProtocolAdapter` now calls exclusively.
- [ ] `comms.py`'s `Comms` builds one `ProtocolHandler` per transport
      at `add_transport()` time, sharing one `ProtocolAdapter`; the
      old v5 dispatch/ack-ring/telemetry-policy code is gone, not
      dead-code-left-in-place.
- [ ] `boot.py` wires `ProtocolAdapter` as step 2/3's dispatch object;
      banner updated to `device NEZHA2 robot <name> <serial>`.
- [ ] `tests/test_comms_loopback.py`, `tests/test_boot_sequence.py`,
      `tests/test_motion.py` updated and green.
- [ ] `python3 -m pytest tests/` fully green; `git diff --exit-code --
      vendor/` stays clean (no vendored kernel touched).
- [ ] `./build.sh --clean --with-diffdrive` still links (confirms no
      accidental native-binding breakage from the Python-side
      refactor — this ticket touches no native code, but the gate
      should still be run once as a sanity check).

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (the whole
  suite — this ticket is the widest-blast-radius one in the sprint).
- **New tests to write**: none new beyond updating the existing
  loopback/boot/motion tests for the new shape; if the
  N-handlers-per-transport wiring needs its own direct test (e.g.
  "two transports get two independent handlers sharing one adapter"),
  add it here rather than assuming ticket 003's isolation test
  already covers the `comms.py`-level wiring (that test covered
  `protocol.py` in isolation, not `comms.py`'s construction of it).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Do the deletions first (wire.py/msgs.py/RobotDispatch/
ConfigDispatch's binary methods) and confirm the resulting import
errors point at exactly the call sites that need rewiring — that's
the cheapest way to find every place `comms.py`/`boot.py` still
assumed the v5 shape. Then rewire `comms.py`, then `boot.py`, then
fix up the three test files last (they're the easiest to get wrong
first and right last, since they'll fail loudly against the new
shape).

**Files to modify/delete**:
- Delete: `src/core/wire.py`, `src/core/msgs.py`,
  `tests/unit/test_wire_golden_vectors.py`,
  `tests/fixtures/wire_golden_vectors.txt`.
- `src/hardware/motion.py` — delete `RobotDispatch` and its handlers.
- `src/core/config.py` — delete `ConfigDispatch`'s binary dispatch
  methods.
- `src/core/comms.py` — the rewiring described above.
- `src/boot.py` — step 2/3 wiring, banner string.
- `tests/test_comms_loopback.py`, `tests/test_boot_sequence.py`,
  `tests/test_motion.py` — updated for the new shape.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: this is also the natural point to update
`docs/design/specification.md`'s protocol section and
`docs/design/usecases.md`'s UC-006/007/008/010 prose to describe v6
instead of v5 (sprint.md's Use Cases section flags these as stale as
of this sprint but explicitly not auto-rewritten by the sprint
process itself, since design-doc opt-in is disabled for this
project) — fold that documentation pass into this ticket since it's
the ticket that makes the description true.
