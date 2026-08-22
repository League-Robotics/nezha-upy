---
id: 009
title: 'Bench bring-up on tovez: TCP REPL mirror proven, USB REPL concurrency'
status: done
use-cases:
- SUC-006
depends-on:
- 008
github-issue: ''
issue: wifi-bring-up-on-tovez-tcp-repl-udp-protocol.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Bench bring-up on tovez: TCP REPL mirror proven, USB REPL concurrency

## Description

First hardware ticket of the WiFi bring-up track: prove the WiFi TCP
`:7654` REPL mirror on real hardware for the first time
(`src/core/wifi_at.py` is code-complete but has never run on
hardware; `tests/test_wifi_at.py` is mock-serial only, and bench step
A.7 has no prior log entry).

**Physical prerequisites (stakeholder-assisted bench session)**:
- The 192.168.4.x AP up and reachable from the bench Mac.
- The WiFi module **power-cycled before this session** — its AT
  state persists across nRF reflashes, so a fresh micro:bit flash
  does NOT reset it (landmine ledger; `docs/bench-acceptance-
  procedures.md` §A.2).
- `wifi_secrets.json` (gitignored) present locally and copied onto
  the device filesystem.
- Build `--clean --with-diffdrive --with-wifi`, deploy to tovez **by
  UID** (`mbdeploy deploy --hex ... <tovez-UID>` — never by mounted
  drive), ~5 s settle before opening any REPL.

**Standing precondition**: every offline (Track A) ticket that has
landed on the branch at the time this session runs is green
(`python3 -m pytest tests/`) — this ticket does not require Track A
to be *complete*, only that whatever *is* on the branch is not
broken.

**Procedure**:
1. Confirm on-device identity first (`ID`/banner via USB REPL or
   `mbdeploy list` by UID) — do not proceed on an unconfirmed board
   (this repo's own precedent: two boards have self-identified as the
   same robot before; see sprint 006's ticket 009 completion notes
   for the exact failure mode this guards against).
2. Using ticket 008's TCP prober (or `nc 192.168.4.11 7654` as a
   cross-check), reach an interactive REPL prompt; evaluate `2+2`.
3. Hold the session open 5 minutes; confirm it stays interactive.
4. Confirm the USB serial REPL stays live and responsive throughout
   — bring-up must never block it.
5. If anything doesn't match the mock's prediction, diagnose via
   `WifiAtLink.state()` at the USB REPL first; fall back to an AT
   trace (`lastCommand`/`lastReply`, the PlanetX driver's pattern) if
   that's insufficient visibility.

## Acceptance Criteria

- [x] On-device identity confirmed before any other step.
- [x] TCP `:7654` reaches an interactive REPL (via the ticket 008
      prober and/or `nc`); `2+2` evaluates correctly.
- [x] Session survives 5 minutes idle.
- [x] USB REPL confirmed live and responsive throughout.
- [x] Any divergence from the mock-serial test's prediction is
      diagnosed (via `state()`/AT trace) and recorded, not just
      worked around silently.
- [x] Findings appended to a tovez bench log in `docs/` (this ticket
      may start that log file; ticket 010 continues it) — e.g.
      `docs/bench-log-tovez-wifi-<date>.md`, matching this repo's
      existing `docs/bench-log-zetuv-2026-08-19.md` naming
      convention.

## Completion Notes (2026-08-21/22)

Full session recorded in `docs/bench-log-tovez-wifi-2026-08-21.md`.
Headline findings:

- tovez's physical WiFi module joined "Busboom Mesh" correctly but got
  DHCP address `192.168.1.196`, not the bench convention's
  `192.168.4.11` (`data/tovez.json`'s `connection.wifi_ip`) -- a
  DHCP-reservation/module-identity mismatch (bench log §8), not a
  firmware defect. Flagged for the stakeholder/ticket 010.
- `mpremote connect ... exec`/`run` soft-resets the board on (most)
  fresh connections, restarting WiFi bring-up from `AT+RST` each time
  -- confirmed empirically (bench log §6). Diagnosis for the rest of
  this session used one continuous `mpremote run <script>` session per
  observation window instead of repeated separate connects.
- Root-caused and fixed a real defect in this sprint's own bring-up
  tooling: `tools/wifi_tcp_probe.py`'s `send_line()` sent a bare `\n`;
  the real WiFi REPL mirror requires `\r` to submit a line, so every
  probe attempt against real hardware silently hung on its own
  "wake the prompt" step. Fixed + regression-tested (bench log §10).
  This was the fix that actually closed acceptance criterion 2.
- Added two small bench-debug accessors needed to diagnose the above:
  `core.boot.last_result()` and `WifiAtLink.debug_trace()` (bench log
  §9), both covered by new offline regression tests.
- No defect found in `src/core/wifi_at.py`'s AT bring-up state machine
  itself -- CIPMUX sequencing, one-CIPSEND-per-datagram, and the join
  logic all matched the mock-serial predictions on real hardware.
- `python3 -m pytest tests/`: 498 passed, 518 subtests passed at the
  end of this session (started at 495 passed).

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (confirm the
  branch is green before starting the hardware session, per the
  standing offline-first precondition).
- **New tests to write**: none offline — this ticket is a hardware
  verification session; its "test" is the bench procedure itself,
  recorded in the findings log.
- **Verification command**: `python3 -m pytest tests/` (pre-session
  gate only).

## Implementation Plan

**Approach**: This ticket is a bench procedure, not a code change —
no `src/` edits are expected unless the session surfaces a real
defect in `wifi_at.py` (code-complete but unproven; a genuine bug
found here should be fixed here, not deferred, since this is exactly
the first-hardware-contact ticket that exists to find such things).

**Files to create**: `docs/bench-log-tovez-wifi-<date>.md` (findings
log, started here).

**Files to modify**: `src/core/wifi_at.py`, only if the session finds
a real defect (unexpected — the design is "code-complete," but bench
reality has a way of disagreeing).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: the bench log itself is the documentation
deliverable.
