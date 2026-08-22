---
id: '006'
title: 'Hard cutover: retire wire.py/msgs.py/RobotDispatch/comms.py''s v5 dispatch
  core; rewire comms.py + boot.py to v6'
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-003
- SUC-004
depends-on:
- '005'
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

- [x] `src/core/wire.py`, `src/core/msgs.py`,
      `tests/unit/test_wire_golden_vectors.py`,
      `tests/fixtures/wire_golden_vectors.txt` deleted.
- [x] `motion.RobotDispatch` and its six `_handle_*` methods deleted;
      `git diff` shows `motion.Move`/`MoveQueue`/generator-mode
      functions byte-identical.
- [x] `config.ConfigDispatch`'s binary dispatch methods deleted; its
      name-keyed accessors (ticket 005) remain and are what
      `ProtocolAdapter` now calls exclusively.
- [x] `comms.py`'s `Comms` builds one `ProtocolHandler` per transport
      at `add_transport()` time, sharing one `ProtocolAdapter`; the
      old v5 dispatch/ack-ring/telemetry-policy code is gone, not
      dead-code-left-in-place.
- [x] `boot.py` wires `ProtocolAdapter` as step 2/3's dispatch object;
      banner updated to `device NEZHA2 robot <name> <serial>`.
- [x] `tests/test_comms_loopback.py`, `tests/test_boot_sequence.py`,
      `tests/test_motion.py` updated and green.
- [x] `python3 -m pytest tests/` fully green; `git diff --exit-code --
      vendor/` stays clean (no vendored kernel touched).
- [x] `./build.sh --clean --with-diffdrive` still links (confirms no
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

## Completion Notes

- **id_line/banner resolution**: `boot.py` no longer builds a banner
  or `id_line` string of its own at all. `core/protocol.py`'s
  `ProtocolHandler.send_banner()`/`_handle_id()`/`_handle_ver()`
  already format "device NEZHA2 robot &lt;name&gt; &lt;serial&gt;" /
  "id &lt;drivetrain&gt; &lt;profile&gt; &lt;version&gt;" / "ver
  &lt;version&gt;" ON DEMAND from the shared `ProtocolAdapter.
  identity()` — so boot only has to hand the adapter the right
  scalars once, at construction. This is the simpler of the two
  options the ticket named, and is what makes a static `id_line`
  string genuinely obsolete (nothing can go stale relative to what the
  wire reports, since `identity()` is called fresh every time).
- **Identity field mapping** (boot's own call — `robot_config.
  schema.json` names none of these "the v6 identity fields" itself):
  `name` = `identity.uid` (falls back to `robot_name`) — chosen over
  `robot_name` because `data/tovez_nocal.json`'s own
  `identity.robot_name` is the two-word string "tovez nocal", and a
  banner field containing a space would misparse under protocol.md's
  space-delimited grammar; `profile` = `identity.robot_name` (which
  named config variant is loaded); `drivetrain` =
  `identity.get("drivetrain_type", "differential")` — `data/
  togov.json` already carries `"drivetrain_type": "mecanum"`, so
  reading it when present reports that robot's real hardware without
  this port needing to understand mecanum kinematics; `serial` =
  `connection.serial_last_6` (unchanged from v5); `counts_per_length`
  = `wheels.ticks_per_mm` (falls back to `1.0` when absent/`null`/
  non-positive — `data/togov.json` carries an explicit JSON `null`
  here, not just a missing key).
- **Fail-closed adapter, not a `None` dispatch**: v5's `NullDispatch`
  had a "no dispatch wired at all" option; v6's `ProtocolHandler`
  does not (`__init__` takes an `Adapter` positionally, not optional),
  and Step 3 brings up comms/REPL unconditionally even on a bad
  config. `boot.py` adds a small private `_NullDiffDrive` (drive() ->
  `"refused_unconfigured"`, the exact status string `protocol_adapter.
  py`'s own `_STATUS_TO_RESULT` table already maps to
  `Result.NOT_CONFIGURED`) so a real `ProtocolAdapter` — never `None`
  — is always what `Comms` gets, on every boot path. `BootResult.
  dispatch` is therefore always a `ProtocolAdapter` now, a change from
  v5 where it could be `None`.
- **Telemetry-emission cadence** (underspecified above the ticket
  level — sprint.md records the one-handler-per-transport/shared-
  adapter decision, not a column-projection contract, and no
  `ProtocolAdapter` telemetry-columns method exists or was added):
  `comms.py`'s cadence gates `emit_telemetry()` on the shared
  adapter's own `status()`-reported `tlm` mode (off/auto/on, using
  `active` for auto — the v5 2000 ms coast-holdoff grace window is
  deliberately NOT reproduced) so `TLM:OFF` actually silences the
  stream, and projects a small column set straight from `status()`'s
  own fields (ready/active/connL/connR/otos/wedge/flags). `src/core/
  telemetry.py`'s full 22-field frame builder is untouched — it was
  built for v5's own `emit_callback` contract and wiring it to v6's
  `emit_telemetry(columns)` shape is future work, not this ticket's.
- **wifi_at.py surface preserved**: `wifi_at.pump()`'s
  READY-on-new-peer-edge call (`comms.send_ready()`) still works
  unchanged — `Comms.send_ready()` stays a raw, handler-bypassing
  broadcast of the literal text `"READY"` (v6's 12-verb scope has no
  READY verb and `ProtocolHandler` has no unsolicited-emission method
  for one, unlike `send_banner()`).
- **Also deleted, tightly coupled to what the ticket named**:
  `motion.py`'s `_corr_id_or_none()`/`ERR_*` constants (existed only
  to serve `RobotDispatch`); `config.py`'s `_corr_id_or_none()`/
  `_pack_f32_le()`/`CONFIG_GROUP_WHEEL_CONTROL`/`ERR_*` and
  `ConfigDispatch`'s now-orphaned `add_transport()`/`_transports`/
  `transports=` constructor param (existed only to broadcast the
  deleted `GET_CONFIG`'s `CFG` reply frame). `tests/test_config.py`
  also needed trimming (its CONFIG/SET_FIELD/GET_CONFIG dispatch
  section exercised exactly the deleted binary methods) even though
  the ticket's own file list didn't name it explicitly.
- **Verification**: `python3 -m pytest tests/` → 446 passed, 11
  skipped, 518 subtests passed (down from the pre-ticket 521/11/518 —
  the difference is entirely deleted v5-only tests: the whole wire
  golden-vector suite, `RobotDispatch`'s tests in `test_motion.py`,
  and the binary CONFIG/SET_FIELD/GET_CONFIG tests in
  `test_config.py` — net of the new comms.py wiring tests added).
  `git diff --exit-code -- vendor/` clean. `./build.sh --clean
  --with-diffdrive` exit 0; `text 331076 / data 8 / bss 126992 / dec
  458076` bytes; MicroPython layout `0x00000..0x50d44`, well under
  `_fs_start` (0x6D000).
- **Pre-existing bug noticed, NOT fixed (out of this ticket's
  scope)**: `boot.py`'s radio-channel selection reads
  `result.robot_config` AFTER it has already been released to `None`
  a few lines above (Step 3), so `config.radio_channel()` is dead
  code and every boot silently uses `DEFAULT_RADIO_CHANNEL` (7)
  regardless of the robot JSON's own `connection.radio_channel`
  (tovez: 3). This predates ticket 006 and is orthogonal to the v6
  cutover; left untouched per "don't fix unrelated bugs while
  rewiring" — worth its own ticket/issue.
