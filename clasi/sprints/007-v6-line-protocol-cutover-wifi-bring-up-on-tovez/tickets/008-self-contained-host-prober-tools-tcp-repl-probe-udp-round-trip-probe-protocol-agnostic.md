---
id: '008'
title: 'Self-contained host prober (tools/): TCP REPL probe + UDP round-trip probe,
  protocol-agnostic'
status: open
use-cases: [SUC-006, SUC-007]
depends-on: []
github-issue: ''
issue: wifi-bring-up-on-tovez-tcp-repl-udp-protocol.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Self-contained host prober (tools/): TCP REPL probe + UDP round-trip probe, protocol-agnostic

## Description

Build the host-side instrument the WiFi bring-up bench sessions
(tickets 009–011) need, since the v6 cutover retires radio-robot's
own `wifi_bench_gate.py` (it goes dark against this firmware — an
accepted consequence of the hard cutover). This tool has **zero
import dependency on `src/`** and is deliberately protocol-agnostic:
raw text lines in, raw text lines out — it proves socket-level
mechanics (connection, framing, peer-learning), not v5 or v6 verb
semantics. That decoupling is what lets tickets 009/010 run
independent of Track A's own progress (sprint.md Design Rationale).

Two halves:
- **TCP prober**: open a TCP connection to `<host>:7654`, expect an
  interactive REPL prompt, send `2+2\n`, expect a `4` echoed back
  somewhere in the response, and support holding the session open
  indefinitely (for the 5-minute-idle and dual-plane-concurrency bench
  cases).
- **UDP prober**: bind the *host's own* fixed source port `7655`
  (the issue's own spec — the robot learns the peer from the first
  datagram's source, so the host side must be a fixed, known port,
  not an ephemeral one), send a line to the robot's `:7654`, and
  report whether/what came back — supporting a simple round-trip
  check (send N distinct lines, confirm N distinct replies or echoes,
  whatever "protocol-agnostic" observation is possible before v6
  lands) and a "how long between sends" throttle-observation mode for
  ticket 010's ≥50 ms TLM-throttle check.

Both halves should be independently unit-testable against a local
mock/loopback socket (no hardware needed to verify the tool's own
socket-handling and CLI parsing logic) — the tool's *value* is only
proven on hardware (tickets 009/010), but its *correctness as a
program* doesn't require it.

## Acceptance Criteria

- [ ] `tools/wifi_tcp_probe.py` (or similar) implements the TCP half:
      connect, expect-prompt, send-expression, hold-open modes.
- [ ] `tools/wifi_udp_probe.py` (or similar) implements the UDP half:
      fixed source port `7655`, send-to-`:7654`, round-trip
      reporting, inter-send timing report (for throttle observation).
- [ ] Both tools run as standalone CLI scripts (no `src/` import) and
      have offline unit tests against a local mock/loopback socket.
- [ ] Both tools' `--host`/`--port` (or equivalent) are parameterized
      — not hardcoded to `192.168.4.11` — so they can be pointed at
      tovez or exercised against a local test server.
- [ ] `python3 -m pytest tests/` green (the tool's own offline tests).

## Testing

- **Existing tests to run**: `python3 -m pytest tests/`
- **New tests to write**: offline tests for both probers against a
  local `socketserver`/loopback TCP and UDP server (no hardware).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Keep both tools small and dependency-free (standard
library `socket` only — no new third-party dependency for a bench
instrument). Model the TCP half loosely on `nc`'s own interactive
behavior (the issue explicitly names `nc 192.168.4.11 7654` as the
reference baseline) rather than trying to be cleverer than a raw
socket relay.

**Files to create**:
- `tools/wifi_tcp_probe.py`
- `tools/wifi_udp_probe.py`
- Their offline unit tests (`tests/test_wifi_tcp_probe.py`/
  `tests/test_wifi_udp_probe.py` or similar).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none this ticket (usage notes belong in
the bench log ticket 010 produces, once there's a real session to
document against).
