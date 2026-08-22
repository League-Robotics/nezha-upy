# nezha-upy — Use Cases

Actors: **Developer** (builds/flashes the image, runs offline suites),
**Student** (writes MicroPython on the robot), **Wire client** (host
tooling — rogo, relay, benches — speaking v5 through UC-011, v6 line
protocol from sprint 007 ticket 006 onward; see that sprint's
`sprint.md` for the cutover), **Stakeholder** (bench acceptance on
tovez, radio channel 3, via mbdeploy).

---

## UC-001 — Build the image

- **Actor:** Developer
- **Preconditions:** repo checked out; arm toolchain installed;
  vendored MicroPython source available to `build.sh`.
- **Main flow:** run `./build.sh --clean`; the patch engine applies
  `patches/` over `micropython-microbit-v2` @0697c6d with
  `codal_overlay.json`; a hex is produced.
- **Postconditions:** hex exists; flash end < `_fs_start` (0x6D000);
  version string present.
- **Error flows:** patch failing to apply → build aborts with the
  failing patch named; overlay mismatch → link error, not silent
  truncation.

## UC-002 — Flash and boot to a live REPL

- **Actor:** Developer / Stakeholder
- **Preconditions:** UC-001 hex; micro:bit connected; `mbdeploy`
  installed.
- **Main flow:** deploy by UID with `mbdeploy` to tovez; wait ~5 s
  post-flash settle; open USB serial.
- **Postconditions:** USB REPL answers; boot zero-write has run before
  the VM starts (wheels silent even after reset mid-drive).
- **Error flows:** stale WiFi module state → power-cycle the module
  first; wrong target → deploy is by UID only.

## UC-003 — Student drives wheels from the REPL

- **Actor:** Student
- **Preconditions:** UC-002; robot config loaded (UC-011).
- **Main flow:** call `diffdrive.drive(...)` with a lease (duration in
  **ms**, ceiling 5000); kernel fiber runs the control law at 24 ms
  cadence; wheels move; encoder counts advance with correct signs.
- **Postconditions:** at lease expiry the kernel zeroes duty; `output`
  and `lastError` report state.
- **Error flows:** lease > 5000 ms rejected by the binding;
  `estop()` zeroes immediately; kernel not begun → raises.

## UC-004 — Starvation watchdog protects a blocked student loop

- **Actor:** Student (inadvertently)
- **Preconditions:** UC-003 drive in progress.
- **Main flow:** student code enters a loop that never reaches idle —
  either `while True: pass` or the realistic polling idiom
  `while True: p = radio.receive()`. Kernel fiber cycles stall
  >250 ms with wheels commanded. VM-hook watchdog writes raw zero duty
  (retry ×2) and latches a fault flag.
- **Postconditions:** wheels stopped ≤300 ms after stall; fault bit
  visible in telemetry; display shows a watchdog indication.
- **Error flows:** none — the watchdog never yields and depends only on
  VM-hook execution.

## UC-005 — Reset mid-drive is silenced by boot zero-write

- **Actor:** Student / Developer
- **Preconditions:** drive in progress.
- **Main flow:** hardware reset; on boot, zero duty is written before
  the VM starts.
- **Postconditions:** wheels stop and stay stopped through boot.
- **Error flows:** none tolerated — this is a hard M1 gate case.

## UC-006 — Wire grammar round-trips the golden vectors

*Superseded by the v6 line protocol, sprint 007 (tickets 001-006):
retired `src/core/wire.py`/`src/core/msgs.py` and the binary/COBS
codec entirely — see sprint 007's `sprint.md` for the full cutover
rationale.*

- **Actor:** Developer (offline)
- **Preconditions:** `src/core/protocol.py`,
  `tests/fixtures/protocol_golden_vectors.txt`.
- **Main flow:** run the golden-vector suite under CPython: parse
  every SETUP/IN/EMIT/OUT block and drive `protocol.ProtocolHandler`
  (a mock `Adapter`) through every in-scope verb (`HELLO PING ID VER
  STATUS HELP GET SET TLM WHEELS STOP ESTOP`).
- **Postconditions:** every applicable vector green (the archetype
  fixture's `RUN`/`debug` vectors are out of this sprint's verb scope
  and skipped, not deleted); `mpy-cross` lints `core/protocol.py` and
  `hardware/protocol_adapter.py`.
- **Error flows:** any vector mismatch fails the suite; the
  embedded-NUL divergence and hex-float-rejection cases are pinned as
  explicit tests, not silently passing by accident.

## UC-007 — Host tooling pings the robot over radio (v6 line protocol)

*Superseded by the v6 line protocol, sprint 007. The wire grammar
changed (ASCII text lines, not COBS+CRC binary frames); the relay/
radio transport and the scheduled-pump mechanics beneath it did not.*

- **Actor:** Wire client
- **Preconditions:** v6 image flashed (sprint 007 ticket 006 landed);
  radio transport registered; radio channel per robot JSON (bench: 3),
  group 10.
- **Main flow:** client sends an uppercase command line (e.g. `PING`)
  over radio; `RadioLink.read_line()` hands the reassembled message to
  that transport's OWN `protocol.ProtocolHandler.feed()` (one handler
  per transport, sharing one `ProtocolAdapter` — sprint.md's Design
  Rationale); the handler replies on the same transport (`pong <now>`
  for `PING`).
- **Postconditions:** reply received; REPL on USB stays interactive
  throughout (scheduled pump, one line read per transport per cycle).
- **Error flows:** unknown verb or wrong arity → malformed count
  increments, a reply is sent only if the line's raw last token is a
  well-formed nonzero `#id`; `ESTOP` never replies, even malformed.

## UC-008 — WHEELS over radio produces motion (v6 line protocol)

*Superseded by the v6 line protocol, sprint 007. Accepted behavior
change (sprint.md Design Rationale): `WHEELS` now commands velocity
through `countsPerLength`, not v5's raw open-loop duty.*

- **Actor:** Wire client
- **Preconditions:** UC-007.
- **Main flow:** `WHEELS <left> <right> <duration> [#id]` over radio →
  the handler tokenizes/validates, then `ProtocolAdapter.on_wheels()`
  scales `[mm/s]` by `countsPerLength` into `[counts/s]`, splits into
  velocity/twist, and calls `MoveQueue.diffdrive.drive()` DIRECTLY —
  no queue involved (`protocol.md` Sec 5.1: "there is no queue in this
  library").
- **Postconditions:** wheels move under the commanded lease; the
  5000 ms duration ceiling is enforced by the adapter ABOVE the kernel
  call, before `drive()` is ever reached.
- **Error flows:** quiet host → lease expiry stops wheels (kill test);
  a duration over the ceiling → `err ... 3` (RANGE), refused before
  any kernel call.

## UC-009 — WiFi REPL mirror session

- **Actor:** Student / Developer
- **Preconditions:** M4 image; WiFi module power-cycled; secrets
  provided locally (gitignored).
- **Main flow:** module joins network (AT state machine, CIPMUX=1);
  TCP :7654 mirrors the REPL via the C stdio hook; user holds an `nc`
  session open.
- **Postconditions:** interactive REPL over TCP concurrent with USB.
- **Error flows:** module state stale across reflash → power-cycle
  discipline; AT flood avoided (one CIPSEND per datagram).

## UC-010 — UDP v6 plane on WiFi

*Superseded by the v6 line protocol, sprint 007 — the join point is
this UDP payload swapping from v5 binary frames to v6 ASCII lines;
`wifi_at.py`'s AT state machine, per-datagram coalescing, and TLM
throttle beneath it are UNCHANGED (sprint.md: "no new source module").*

- **Actor:** Wire client
- **Preconditions:** UC-009 network up; v6 image (sprint 007 ticket
  006 landed).
- **Main flow:** v6 ASCII lines on UDP :7654, one datagram per line;
  per-datagram coalescing (one `AT+CIPSEND` per datagram, never per
  character); `TLM` throttled ≥50 ms on this plane
  (`wifi_at.TlmThrottle`).
- **Postconditions:** `wifi_bench_gate.py`'s framing/peer-learning
  mechanics validate unmodified against the v6 payload — the prober is
  built protocol-agnostic (raw text lines) specifically so it needs no
  v6-awareness of its own (sprint.md Design Rationale).
- **Error flows:** READY handled on new-peer edge in the pump
  (`wifi_at.pump()` → `comms.send_ready()`, unchanged mechanism —
  still a raw "READY" broadcast, not a v6 wire verb).

## UC-011 — Robot config loads fail-closed at boot

- **Actor:** Developer / Student
- **Preconditions:** per-robot JSON (schema per
  `robot_config.schema.json`) on the filesystem; wiring fix present
  (`left_port: 2, right_port: 1, fwd_sign_left: +1,
  fwd_sign_right: -1`).
- **Main flow:** `config.py` validates required keys fail-closed; maps
  `wheel_control` → `DiffDrive::Config` (travel_calib×10); applies
  radio channel/group.
- **Postconditions:** kernel configured before first drive; CONFIG /
  SET_FIELD / GET_CONFIG live over the wire; no on-flash persistence
  (baked JSON rules at boot).
- **Error flows:** missing/invalid key → motion refused (fail-closed
  boot test), REPL still available for diagnosis.

## UC-012 — Telemetry stream

- **Actor:** Wire client
- **Preconditions:** M5 image.
- **Main flow:** telemetry emits all 22 fields; policy AUTO =
  silent-while-parked, 25 ms period, pending acks force emission;
  includes watchdog fault bit and `cycleOverrunCount_` (from M1).
- **Postconditions:** OTOS pose sane in TLM; cadence-loss evidence
  available.
- **Error flows:** emit policy change via wire verb; inbound TLM is a
  cleartext mode verb.

## UC-013 — Queued motion sequencing

- **Actor:** Wire client / Student
- **Preconditions:** M5 image.
- **Main flow:** motion.py queues moves (5-deep) with stop conditions,
  GO_TO, SEED/POSE, CALIBRATE; every duration in **ms**; replace
  semantics; timeout fault.
- **Postconditions:** `move_protocol_bench.py` full pass over the radio
  path.
- **Error flows:** queue overflow → protocol error; timeout → fault
  reported, motion zeroed.

## UC-014 — Stakeholder acceptance sweep (M6)

- **Actor:** Stakeholder
- **Preconditions:** all prior gates green offline; master built
  `--clean`; bench = tovez, channel 3, mbdeploy.
- **Main flow:** `wifi_bench_gate` 9/9; `move_protocol_bench` full;
  quiet-host kill test; power-cycle boot-zero test; 10-min dual-plane
  soak; RAM/flash checkpoint (frozen-manifest heap delta).
- **Postconditions:** acceptance recorded; radio-robot
  `git diff master -- src/firm` = diffdrive-only.
- **Error flows:** any failure → issue filed, milestone reopened.

## UC-015 — Vendor sync stays clean

- **Actor:** Developer
- **Preconditions:** radio-robot is the single source of `diffdrive/`
  and the leaf; `sync_upy.py` lives there.
- **Main flow:** kernel/schema changes happen in radio-robot, gated by
  `src/tests/diffdrive/`; sync copies kernel pair + leaf + fixture and
  regenerates `msgs.py`; commit here.
- **Postconditions:** sync-diff check clean; `vendor/` never edited in
  this repo.
- **Error flows:** local vendor edit → sync-diff gate fails the sprint.
