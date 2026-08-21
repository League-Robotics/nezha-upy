---
id: '010'
title: 'Bench bring-up on tovez: UDP round-trip, peer-learning, dual-plane concurrency,
  findings log'
status: open
use-cases: [SUC-007]
depends-on: ['009']
github-issue: ''
issue: wifi-bring-up-on-tovez-tcp-repl-udp-protocol.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Bench bring-up on tovez: UDP round-trip, peer-learning, dual-plane concurrency, findings log

## Description

Second hardware ticket of the WiFi bring-up track, same bench session
family as ticket 009 (same physical prerequisites — AP up, WiFi
module power-cycled, `wifi_secrets.json` on-device, tovez deployed —
do not re-power-cycle mid-session unless a genuine reset is needed;
state what happened either way in the findings log).

**Procedure**:
1. Using ticket 008's UDP prober, send a datagram to the robot's
   `:7654` from the host's fixed source port `:7655`.
2. Confirm the robot learns the host as its peer from that first
   datagram (extended `+IPD` parsing) — check via `WifiAtLink.state()`
   at the USB REPL if not directly observable from the host side.
3. Confirm datagrams round-trip host↔robot.
4. Hold a TCP REPL session open (ticket 009's proven mechanism)
   **concurrently** with UDP traffic — this is the dual-plane claim
   the design is built on (`wifi_at.py`'s CIPMODE=0/CIPMUX=1 choice,
   deliberately not the PlanetX driver's single-pipe CIPMODE=1); it
   is not a before/after check, both channels must be live at once.
5. Confirm telemetry-shaped traffic (whatever the current engine on
   the branch emits — v5 or v6, per the standing protocol-agnostic
   convention) is throttled ≥50 ms, and that no per-character AT
   flooding occurs (one `CIPSEND` per datagram is a tested invariant
   of `tests/test_wifi_at.py`, offline/mocked only — a live capture
   disagreeing with that is worth recording precisely).
6. Append findings to the tovez bench log ticket 009 started.

## Acceptance Criteria

- [ ] UDP round-trip confirmed, peer-learned from the first datagram.
- [ ] Dual-plane concurrency confirmed: TCP REPL session stays
      interactive while UDP traffic flows, and vice versa.
- [ ] Telemetry throttle ≥50 ms observed (or the discrepancy recorded
      precisely if not).
- [ ] No per-character AT send pattern observed in any available
      capture/trace.
- [ ] USB REPL confirmed live throughout.
- [ ] Findings appended to the tovez bench log (continuing ticket
      009's file).

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (pre-session
  gate — confirm the branch is still green).
- **New tests to write**: none offline — bench procedure, recorded in
  the findings log.
- **Verification command**: `python3 -m pytest tests/` (pre-session
  gate only).

## Implementation Plan

**Approach**: Same posture as ticket 009 — a bench procedure, not a
planned code change. A genuine defect found here (e.g. peer-learning
not firing, throttle not holding under concurrent TCP load) gets
fixed in `src/core/wifi_at.py` as part of this ticket, with the fix
and its bench verification both recorded in the findings log.

**Files to modify**: `src/core/wifi_at.py`, only if the session finds
a real defect.

**Files to create/append**: the tovez bench log (continuing ticket
009's file).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: the bench log itself.
