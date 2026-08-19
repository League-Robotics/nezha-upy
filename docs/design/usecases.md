# nezha-upy — Use Cases

Actors: **Developer** (builds/flashes the image, runs offline suites),
**Student** (writes MicroPython on the robot), **Wire client** (host
tooling — rogo, relay, benches — speaking v5), **Stakeholder** (bench
acceptance on tovez, radio channel 3, via mbdeploy).

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

## UC-006 — Wire codec round-trips the golden vectors

- **Actor:** Developer (offline)
- **Preconditions:** `src/wire.py`, `src/msgs.py`,
  `tests/fixtures/wire_golden_vectors.txt`.
- **Main flow:** run the golden-vector suite under CPython: decode and
  encode all 8 cross-language vectors; round-trip every binary verb
  against the host pb2.
- **Postconditions:** 8/8; byte-exact encodes; `mpy-cross` lint passes
  on every `src/*.py`.
- **Error flows:** any vector mismatch fails the suite; CRC or COBS
  divergence is a blocker, not a warning.

## UC-007 — Host tooling pings the robot through the relay, unchanged

- **Actor:** Wire client
- **Preconditions:** M3 image flashed; relay running; radio channel per
  robot JSON (bench: 3), group 10.
- **Main flow:** `rogo repl <robot> ping` with completely unchanged
  host tooling; the Python v5 engine parses (relay sigils dropped
  first), acks (ring depth 12, repeats 3), banner byte-frozen.
- **Postconditions:** ping acknowledged; REPL on USB stays interactive
  throughout (scheduled pump, bounded work per call).
- **Error flows:** NACK carries err code; unknown verb → protocol
  error ack, engine keeps running.

## UC-008 — Motion command over radio produces motion and acks

- **Actor:** Wire client
- **Preconditions:** UC-007.
- **Main flow:** WHEELS command over radio → engine dispatches to the
  kernel binding; wheels move under lease; acks emitted; telemetry
  reflects motion.
- **Postconditions:** motion matches command; lease semantics as
  UC-003.
- **Error flows:** quiet host → lease expiry stops wheels (kill test).

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

## UC-010 — UDP v5 plane on WiFi

- **Actor:** Wire client
- **Preconditions:** UC-009 network up.
- **Main flow:** v5 datagrams on UDP :7654; per-datagram coalescing;
  TLM throttled ≥50 ms on this plane; acks survive throttling
  (repeats 3).
- **Postconditions:** `wifi_bench_gate.py --port wifi: --skip-drive`
  9/9 with an `nc` REPL session held open.
- **Error flows:** READY handled on new-peer edge in the pump.

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
