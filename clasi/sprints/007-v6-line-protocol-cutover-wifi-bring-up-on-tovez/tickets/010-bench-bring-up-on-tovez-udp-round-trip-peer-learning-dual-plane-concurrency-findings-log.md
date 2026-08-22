---
id: '010'
title: 'Bench bring-up on tovez: UDP round-trip, peer-learning, dual-plane concurrency,
  findings log'
status: done
use-cases:
- SUC-007
depends-on:
- 009
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

- [x] UDP round-trip confirmed, peer-learned from the first datagram.
- [x] Dual-plane concurrency confirmed: TCP REPL session stays
      interactive while UDP traffic flows, and vice versa.
- [x] Telemetry throttle ≥50 ms observed (or the discrepancy recorded
      precisely if not). (Discrepancy recorded: NOT actually enforced
      on the v6 WiFi plane — see bench log §20-21.)
- [x] No per-character AT send pattern observed in any available
      capture/trace.
- [x] USB REPL confirmed live throughout.
- [x] Findings appended to the tovez bench log (continuing ticket
      009's file).

## Completion Notes (2026-08-22)

Full session recorded in `docs/bench-log-tovez-wifi-2026-08-21.md`
(sections 16-26, continuing ticket 009's file). Headline findings:

- **Central finding — real crash, found and fixed**:
  `src/core/protocol.py`'s `ProtocolHandler._on_line_complete()`/
  `_append_byte()` used `del self._line_buf[...]` (slice deletion on a
  `bytearray`) to reset/trim its line buffer. This is `protocol.py`'s
  first-ever execution on real MicroPython hardware (all offline tests
  are CPython; ticket 009 only exercised the TCP REPL mirror, which
  bypasses this module entirely), and this MicroPython build's
  `bytearray` does not support `__delitem__` at all — confirmed live on
  tovez (`TypeError: 'bytearray' object doesn't support item deletion`)
  and independently against the vendored MicroPython unix interpreter.
  Consequence was more severe than one dropped reply: the exception,
  raised inside the scheduled-pump callback, silently wedged the ENTIRE
  pump (WiFi servicing included) for the rest of that session — a
  90-second on-device watch showed the AT trace completely static
  afterward. Fixed by reassigning/slice-copying instead of `del`
  (bench log §18); verified end-to-end after a `--clean` rebuild +
  reflash (§19); regression-pinned at the interpreter-semantics level
  (`tests/upy/test_runtime_semantics.py::
  test_bytearray_does_not_support_del`).
- **Found, not fixed — flagged for the stakeholder/ticket 011**: the
  WiFi-plane ≥50 ms telemetry throttle (`wifi_at.TlmThrottle`/
  `send_telemetry()`, built, unit-tested, and named explicitly in
  `PLAN.md`'s M4 gate) is never wired into the v6 `comms.py`/
  `protocol.py` telemetry-emission path, which instead calls the
  unthrottled `send_reliable()` on every ~24 ms pump tick. This is very
  likely an unflagged regression from the v6 cutover, not a deliberate
  decision. `WifiAtLink._send_queue` grows without bound for as long as
  TLM stays non-`"off"` — confirmed directly (disabling TLM after just
  8-25 s of it enabled got no `ack` reply within a 5 s timeout both
  times). Not fixed here because a correct fix is an architecture
  decision (how `protocol.Sink`'s `write()` contract should distinguish
  a periodic telemetry push from a direct reply), not a small patch —
  bench log §20-21/§26 has the full analysis and an honestly-flagged
  open detail (one drain pattern this session could not fully
  characterize without another destructive reset).
- Small tool gap fixed: `tools/wifi_udp_probe.py` only generated
  generic `PROBE N` placeholders, which the v6 engine cannot parse as
  any verb and therefore never answers — added a repeatable `--line
  TEXT` flag to send an exact protocol verb (`HELLO`) instead (bench
  log §17).
- Dual-plane concurrency (TCP REPL held open while UDP telemetry
  flowed) confirmed with an explicitly wall-clock-instrumented repeat
  after an initial, less rigorously-timed attempt raised a question
  this session then resolved (bench log §22).
- Peer-learning from the first datagram, and the WiFi TLM
  peer-known/DHCP-mismatch landmines ticket 009 found, all re-confirmed
  unchanged.
- `python3 -m pytest tests/`: 500 passed at the end of this session
  (started at 498).

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
