---
status: in-progress
sprint: '007'
tickets:
- 007-001
- 007-002
- 007-003
- 007-004
- 007-005
- 007-006
- 007-007
- 007-011
---

# Port the v6 line protocol (hard cutover from v5)

Stakeholder decision (2026-08-21): **hard cutover**. The v5 engine —
`src/core/wire.py` (COBS+CRC), `src/core/msgs.py`, and `comms.py`'s
binary/cleartext dual-plane dispatch, ack ring, and ×3 repeats — is
replaced by the v6 line protocol. No dual-stack period on the device.

## The authority

`radio-robot-lib/docs/design/protocol.md` is the wire format *and* the
design. The C++ reference implementation is
`radio-robot-lib/src/protocol/protocol_handler.{h,cpp}` (817 lines),
built explicitly as an **archetype to be ported to MicroPython by
reading it and running its fixture** (§9.4). The conformance fixture is
`radio-robot-lib/tests/protocol/golden_vectors.txt` (314 lines,
SETUP/IN/OUT block format documented in its own header).

## Shape of the port

- One grammar, ASCII, `readline()` is the transport: no COBS, no CRC,
  no framing layer. Max line 240 bytes including terminator.
- **Case is direction**: commands UPPERCASE, replies lowercase;
  a lowercase verb is dropped silently (another robot's reply), NOT
  counted malformed.
- Trailing self-marking `#<n>` id; digits-only grammar stricter than a
  data field (`#+5` malformed). Required on `STOP`, optional on
  `SET`/`WHEELS`; `#0` = execute silently (only where optional).
- Malformed-line recovery: if the last token is a well-formed nonzero
  `#id`, reply `err #<id> <code>` even for unknown verbs. `ESTOP` is
  the one exception — never replies, ever.
- Handler/adapter split: the handler owns every wire byte; the adapter
  gets typed args and returns a `Result`. Port both halves — the
  handler as `src/core/protocol.py` (or similar), the adapter backed by
  the same `diffdrive`/config objects `motion.RobotDispatch` wraps
  today.
- Handler is a pure function of its input bytes: no `done` emission,
  no pending state, no 3× repeat (§8/§9.2 — deliberate).

## Port-specific decisions §9.4 requires making deliberately

1. Hex-float rejection: Python's `float()` already refuses `0x1.8p3` —
   no action needed, but pin it with a test.
2. Python's `int()`/`float()` strip whitespace AND accept `_` digit
   separators — the wire grammar admits neither. Guard explicitly.
3. Embedded NUL: the C++ handler's `strcmp` truncation
   (`PING\0extra` == `PING`) is a characterization artifact, NOT
   grammar-correct. The Python port should REJECT (length-aware
   compare is Python's natural behavior); do not reproduce the C
   quirk.

## What retires

- `src/core/wire.py`, `src/core/msgs.py`, the v5 dispatch order,
  ack ring, telemetry emit-policy arithmetic in `comms.py`.
- `tests/unit/test_wire_golden_vectors.py` + the v5 fixture
  `tests/fixtures/wire_golden_vectors.txt`.
- Host-side consequence (accepted): radio-robot's v5 tooling (rogo
  relay path, wifi_bench_gate.py, move_protocol_bench.py) goes dark
  against this firmware until ported. The WiFi bring-up issue
  ([[wifi-bring-up-on-tovez-tcp-repl-udp-protocol]]) therefore carries
  its own self-contained host prober.

## What survives

- The transport contract (`read_line()/send()/send_reliable()`) and
  `radio_shim.py`'s fragment reassembly — v6 rides the same transports.
- The scheduled-pump plumbing (`PumpTimer`, `micropython.schedule`,
  bounded work per tick) — v6's `feed()` slots into the same pump.
- `boot.py`'s six-step assembly, banner/READY sequencing (banner
  format changes to v6's `device NEZHA2 robot <name> <serial>`).

## Gate (offline, no hardware)

- A CPython test harness that parses `golden_vectors.txt`'s block
  format and drives the Python handler with a mock adapter — every
  applicable vector green. Vectors exercising C++-only behavior
  (embedded NUL) get explicit divergence tests instead.
- `mpy-cross` compiles the new module(s).
- Loopback test: banner, ok/err/id shapes byte-exact against the
  design doc's own examples.
