---
status: in-progress
sprint: '007'
tickets:
- 007-008
- 007-009
- 007-010
- 007-011
---

# WiFi bring-up on tovez — TCP REPL + UDP protocol plane, proven on hardware

The four-channel communication shape is decided and already
implemented in code, but the WiFi half has **never run on hardware**
(`tests/test_wifi_at.py` is mock-serial only; bench step A.7 has never
been executed — no entry in any bench log):

| channel | role | status |
|---|---|---|
| USB serial | stock MicroPython REPL | proven |
| radio | protocol link | proven (v5 today) |
| WiFi TCP :7654 | REPL mirror | code complete, unproven |
| WiFi UDP :7654 | protocol plane (discovery :7655) | code complete, unproven |

Target: **tovez** (stakeholder 2026-08-21; module fitted). Static IP
192.168.4.11 per `data/tovez.json`.

## What exists

- `src/core/wifi_at.py` (728 lines): full AT state machine —
  CIPMUX=1, TCP server, UDP socket link 4 mode 2, peer learned from
  extended `+IPD`, one CIPSEND per datagram, ≥50 ms TLM throttle,
  READY-on-new-peer-edge. Deliberately CIPMODE=0/CIPMUX=1 (NOT the
  PlanetX C++ driver's CIPMODE=1 transparent passthrough — passthrough
  is a single pipe and cannot carry TCP-REPL and UDP simultaneously).
- `native/modwifiuart.cpp` + `codal_app/wifi_uart_pipe.cpp` +
  `wifi_stdio_hook.cpp`: UARTE1 byte pipe + stdio REPL mirror ring,
  wired by `build.sh --with-wifi`.
- `boot.py` step 3 registers `WifiAtLink` as a comms transport iff
  `wifi_secrets.json` exists on the device filesystem.
- Reference oracle: `reference/modrobot/wifi_stdio.cpp` and the
  PlanetX `wifi_link.cpp` bring-up findings (probe sweep, +IPD
  parsing, timings).

## What this issue delivers

1. **A self-contained host prober in this repo** (`tools/`), since the
   v5 cutover ([[port-v6-line-protocol-hard-cutover-from-v5]]) retires
   radio-robot's `wifi_bench_gate.py`. Two halves:
   - TCP: open :7654, get a REPL prompt, eval `2+2`, hold the session.
   - UDP: send a datagram to the robot's :7654 from the fixed host
     port :7655, verify the robot learns the peer and datagrams
     round-trip. Protocol-agnostic at first (raw lines); becomes the
     v6 smoke test once the port lands.
2. **The bench bring-up itself**, following
   `docs/bench-acceptance-procedures.md` A.2 discipline: `--clean
   --with-diffdrive --with-wifi` build, deploy by UID, ~5 s settle,
   **power-cycle the WiFi module first** (AT state persists across nRF
   reflashes — landmine ledger), `wifi_secrets.json` copied to the
   device filesystem.
3. Debugging whatever the mock didn't predict, with findings recorded
   in the bench log. First diagnostics: `WifiAtLink.state()` via the
   USB REPL, and the AT trace (`lastCommand`/`lastReply` pattern from
   the PlanetX driver is the model if visibility is insufficient).
4. Concurrency proof: TCP REPL session held open **while** UDP
   traffic flows (dual-plane on one module is the design's claim).

## Sequencing

Stakeholder: run this **in parallel** with the v6 port — this track
proves the physical/AT layer using raw/v5 lines; the join point is
swapping the UDP payload to v6 at the end.

## Bench prerequisites (physical acts, stakeholder-assisted)

- The 192.168.4.x AP up and reachable from the bench Mac.
- `wifi_secrets.json` (gitignored) present locally and copied to the
  device.
- WiFi module power-cycle before each session.

## Gate

- TCP: `nc 192.168.4.11 7654` (or the prober) reaches an interactive
  REPL; survives 5 minutes idle; survives concurrent UDP traffic.
- UDP: round-trip datagrams host↔robot with the robot having learned
  the host from its first datagram; telemetry throttled ≥50 ms.
- USB REPL stays live throughout (bring-up must not block the cycle).
- Findings appended to a tovez bench log in `docs/`.
