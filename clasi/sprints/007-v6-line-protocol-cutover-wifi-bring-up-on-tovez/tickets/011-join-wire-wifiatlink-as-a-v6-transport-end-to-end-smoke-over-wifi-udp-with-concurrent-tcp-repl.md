---
id: '011'
title: 'Join: wire WifiAtLink as a v6 transport, end-to-end smoke over WiFi UDP with
  concurrent TCP REPL'
status: done
use-cases:
- SUC-008
depends-on:
- '010'
- '013'
github-issue: ''
issue:
- port-v6-line-protocol-hard-cutover-from-v5.md
- wifi-bring-up-on-tovez-tcp-repl-udp-protocol.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Join: wire WifiAtLink as a v6 transport, end-to-end smoke over WiFi UDP with concurrent TCP REPL

## Description

The join point both tracks have been building toward: with the v6
protocol offline-proven (tickets 001–007) and the WiFi hardware/AT
layer proven on raw traffic (tickets 008–010), confirm the two
together — v6 traffic actually flowing over the WiFi UDP plane on
real hardware, with the TCP REPL mirror concurrently live.

By this point `boot.py` (ticket 006) already registers `WifiAtLink`
as a `Comms` transport whenever `wifi_secrets.json` is present, and
`Comms.add_transport()` already gives it its own `ProtocolHandler`
instance sharing the one `ProtocolAdapter` (same mechanism the radio
transport uses) — so there should be **no new source code** required
purely to "wire WifiAtLink as a v6 transport"; if this ticket finds
that untrue (e.g. `WifiAtLink`'s `read_line()`/`send()` don't compose
cleanly with `feed()`'s expectations under real AT-layer framing),
that is exactly the kind of gap this join ticket exists to catch and
fix.

**Procedure** (same bench prerequisites as tickets 009/010 — AP up,
module power-cycled, secrets on-device, tovez deployed at this
sprint's HEAD):
1. Confirm the branch is at a state where both tracks are complete
   (tickets 001–010 all done).
2. Using ticket 008's probers (now exercising real v6 verb content —
   the "protocol-agnostic" posture ends here, by design), send
   `HELLO`/`PING` over the UDP plane; confirm typed `device NEZHA2
   robot ...`/`pong <now>` replies.
3. Send `WHEELS ... #id` / `STOP #id`; confirm the in-order `ack <id>
   <lastDone>` reply (plus `err <code> #<id>` on rejection, e.g. an
   over-ceiling duration) and real motion (or its absence, safely, if
   run off-stand). **Retargeted 2026-08-21** (see tickets 012/013,
   [[retarget-v6-port-to-reliability-layer-draft]]): the old bare
   `ok #<id>`/`err #<id> <code>` shapes this step originally named are
   superseded by the mandatory-sequencing reliability layer — `ok` is
   gone, `err`'s field order flips.
4. Send a well-formed `ESTOP` and one with trailing junk (e.g.
   `ESTOP #5`); confirm **both now reply the bare word `estop`**,
   written after the stop executes. **Retargeted 2026-08-21**: this
   supersedes SUC-002's original "never any reply" behavior — see the
   same tickets/issue as step 3. Confirming the reply arrives over
   WiFi UDP too (not just radio, where tickets 012/013 already prove
   it offline) is this step's own contribution.
5. Hold a TCP REPL session open throughout steps 2–4.
6. Append findings to the tovez bench log.

## Acceptance Criteria

- [x] `WifiAtLink` confirmed registered as a v6 transport with its
      own `ProtocolHandler` instance (code-level check, not just
      behavior — read `boot.py`'s actual wiring).
- [x] `HELLO`/`PING` round-trip correctly over WiFi UDP.
- [x] `WHEELS`/`STOP` round-trip correctly over WiFi UDP (`ack`
      success shape / `err <code> #<id>` rejection shape — retargeted
      2026-08-21, see tickets 012/013).
- [x] `ESTOP` (well-formed and with trailing junk) replies the bare
      word `estop` over WiFi UDP, matching the retargeted (2026-08-21)
      radio-transport behavior tickets 012/013 establish offline —
      supersedes this ticket's original "no reply" criterion, which
      pinned SUC-002 before the retarget.
- [x] TCP REPL session stays interactive throughout the UDP smoke
      test.
- [x] Findings appended to the tovez bench log; any gap found between
      "should just work by composition" and actual behavior is
      recorded and fixed, not silently patched over.

## Completion Notes (2026-08-22)

Full session recorded in `docs/bench-log-tovez-wifi-2026-08-21.md`
§27-34 (continuing tickets 009/010's file). Headline findings:

- **This ticket's own premise held exactly as written**: reading
  `boot.py`'s Step 3 and `Comms.add_transport()` directly (bench log
  §30) confirms `WifiAtLink` gets its own `protocol.ProtocolHandler`
  purely by being registered as a transport, the identical mechanism
  the radio transport uses — no WiFi-specific branch anywhere in that
  path, and no source code change was needed to "wire" it.
- **The reliability layer proven live over WiFi UDP, end to end**: a
  thirteen-exchange conversation (bench log §31) covering `HELLO`'s
  peer-learning + banner, in-order `PING`/`STATUS` (with `next=`), a
  deliberate out-of-order id (`nack`, no execution), a same-payload
  retransmit of `WHEELS` (echoes the highest-ALREADY-accepted id, NOT
  the resent one, and does not re-execute — confirmed both by the
  reply value and by the absence of a second rejection reply), `STOP`,
  an err-layering case (`SET` with an unparseable value → `ack` then
  `err 2 #<id>`), and `ESTOP` (well-formed and with trailing junk,
  both replying the bare word `estop`, and confirmed via a following
  `PING` to never disturb the ordinary sequence) — all matched
  `reference/protocol-draft-2026-08-21.md` exactly.
- **`WHEELS` itself was rejected** (`err 8` / `NOT_CONFIGURED` — the
  diffdrive kernel fiber was never begun/started this boot,
  `boot.py`'s own documented "first motion consumer begins/starts the
  fiber" design), so no real wheel motion occurred. This is
  transport-agnostic (the identical rejection would occur over radio)
  and is exactly the ticket's own anticipated "real motion (or its
  absence, safely...)" outcome — not a WiFi defect, not in this
  ticket's scope to chase further.
- **Dual-plane concurrency re-confirmed with the same wall-clock
  rigor ticket 010 established** (bench log §32): a TCP REPL hold ran
  its full requested 90 s with no early exit while the entire UDP
  conversation above executed inside that window.
- **Real defect found, NOT fixed (already tracked, scope excluded by
  the team-lead's own briefing)**: at session start, the device was
  completely unresponsive on both the UDP and TCP WiFi planes — a
  repeating, uncaught `MemoryError` inside `WifiAtLink.send()`,
  wedging the scheduled pump permanently (bench log §28). This is the
  predicted worst case of the already-tracked
  `clasi/issues/wifi-plane-telemetry-throttle-not-wired.md` (opened by
  ticket 010), now confirmed to actually occur, and confirmed severe
  enough that even `mpremote`'s own raw-REPL handshake failed against
  the flood. Recovered via a software-triggered hard reset
  (`mpremote ... reset`, not a physical act); the issue file was
  updated with this confirmation. No code was changed for this —
  the architecture-level fix remains explicitly out of this ticket's
  scope, per both the issue's own reasoning and this ticket's brief.
- No `WifiAtLink`/`feed()` composition gap of any kind was found —
  the one thing this ticket was most concerned might not compose
  cleanly ("if this ticket finds that untrue... fix it") turned out to
  already work correctly.
- `python3 -m pytest tests/`: **500 passed, 518 subtests passed**,
  unchanged from where ticket 010 left off — no source file was
  modified by this ticket.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (confirm the
  full sprint's offline suite is green before this final hardware
  session).
- **New tests to write**: none offline — end-to-end hardware smoke,
  recorded in the findings log. If a real code gap is found and
  fixed, add an offline regression test for it alongside the fix.
- **Verification command**: `python3 -m pytest tests/` (pre-session
  gate); the hardware smoke procedure itself is this ticket's actual
  acceptance instrument.

## Implementation Plan

**Approach**: Verification-first — confirm the composition already
works before assuming a fix is needed. If it does, this ticket is
almost entirely a bench procedure. If it doesn't, treat the gap as a
real (likely small) integration bug in how `WifiAtLink`'s framing
interacts with `feed()`, fix it, and add the missing offline test
that should have caught it, so the sprint's own gate is strengthened
by what this ticket finds.

**Files to modify**: none expected; `src/core/wifi_at.py` or
`src/core/comms.py`, only if the session surfaces a real integration
gap.

**Files to create/append**: the tovez bench log (continuing tickets
009/010's file).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: the bench log; if this ticket closes both
source issues, no further action is needed beyond the automatic
issue-archival `create_ticket`'s `completes_issue: true` already
provides.
