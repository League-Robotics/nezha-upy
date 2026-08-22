---
status: done
sprint: '007'
tickets:
- 007-012
- 007-013
---

# Retarget the v6 port to the 2026-08-21 reliability-layer draft (+ RUN/debug)

Stakeholder decision (2026-08-21, mid-sprint-007): **stop and retarget
now.** The port completed in tickets 001–007 implements protocol.md as
committed at session start; the design has since moved twice:

1. **Committed during the session** (radio-robot-lib `c99e6e8`):
   `RUN` (invocation-by-name) and `debug` (robot→host only) verbs —
   protocol.md §6.2/§6.3/§9.7.
2. **Uncommitted working-tree draft** (~540 added lines, §8 rewritten):
   the reliability layer — mandatory sequence ids + cumulative
   `ack`/`nack`. The stakeholder is quoted verbatim inside the draft
   (§8.3), so it is stakeholder-authored design, not speculation.

The port now LEADS the C++ archetype: no updated golden vectors, no
updated reference implementation exist yet. Risk accepted explicitly
by the stakeholder. The implementing work must **snapshot the draft
text into this repo** (e.g. `reference/protocol-draft-2026-08-21.md`)
so the target is fixed even if the upstream working tree keeps moving,
and record the snapshot's upstream git state (base commit `c99e6e8`,
uncommitted working tree).

## What changes in protocol.py (from the draft, §2.2/§6/§8)

- **Sequencing state**: `expected_next=1`, `last_done=0`,
  `gap_outstanding=False`. That is ALL the receiver state — no ring,
  no clock, no tick.
- **Mandatory `#id` on every sequenced verb**
  (`PING ID VER STATUS HELP GET SET TLM WHEELS STOP RUN`); the id is
  stripped centrally before verb parsing. Three-way classification:
  `== expected_next` → dispatch, advance, `ack <id> <lastDone>`;
  `<` → retransmit: do NOT re-execute, `ack <expected_next-1> <lastDone>`;
  `>` → gap: discard, `nack <expected_next> <lastDone>`.
- **`ok` is deleted** — an in-order `ack` IS acceptance. `err` becomes
  a second line layered on top of the ack for in-order-but-rejected
  content, with **field order flipped: `err <code> #<id>`** (§8.6).
  Unknown verb / wrong arity / bad field with an in-order id → ack +
  err (ERR_UNKNOWN/ERR_BADARG); malformed counter counts content
  failures only, never sequencing outcomes.
- **§8.4 replaces the old malformed-line recovery entirely**: no
  trailing field → no reply; trailing field not `#[0-9]+` → no reply;
  well-formed id → classify by id alone before any verb inspection.
- **`#0` deleted as a special case** (always stale/retransmit);
  ERR_DUPLICATE_ID (11) becomes unreachable (stays declared).
- **`HELLO`: unsequenced, zero fields** (a trailing id is wrong
  arity), resets `expected_next=1`, `last_done=0`,
  `gap_outstanding=False`, then banner.
- **`ESTOP`: unsequenced, maximally forgiving** — ANY line whose verb
  token is exactly `ESTOP` executes the stop regardless of trailing
  junk/arity, and now **replies the bare word `estop`**, written AFTER
  the kernel call executes. Supersedes never-reply (SUC-002 and the
  ticket 001–004 tests pinning silence must flip).
- **Telemetry piggyback (§8.5)**: every `emit_telemetry()` call also
  emits the current reliability line (`nack <expected_next> <lastDone>`
  if `gap_outstanding` else `ack <expected_next-1> <lastDone>`). No
  timer added.
- **`STATUS` gains `next=<expected_next>`** (§8.7). No wraparound
  handling; ids 1..999999 by host convention, unenforced.
- **`sendDebug(text)`** (§6.2): unsolicited `debug <text>`, `\n`/`\r`
  stripped, truncated to the 240-byte cap, empty → bare `debug`.
- **`RUN <function> [arg...] #id`** (§6.3): handler parses only —
  name + raw arg tokens → adapter `on_run`; replies `ret <value> #<id>`
  (in addition to ack) for a value, nothing for void, ack+err for
  unknown/arity/convert failures; `RUN #7` (id consumed the only
  field) → ack + err 2; bare `RUN` → malformed per §8.4. Return value
  sanitized like debug text.
- **HELP text**: 13 verbs (adds RUN).

## What changes in protocol_adapter.py

- `on_run(name, args)` with an **explicit registration allowlist as
  the security boundary** (§6.3) — mirror the archetype's
  DiffDriveAdapter: register nothing by default, every RUN →
  ERR_UNKNOWN. Do NOT expose `globals()` blanket lookup.

## Test consequences

- The synced golden-vector fixture gates the OLD scheme; most of its
  ack/reply shapes are now wrong by design. Mark the fixture
  superseded (keep the file; point the harness at a NEW fixture) and
  author a new draft-derived vector set from §8's own tables and the
  §6 verb table — written so radio-robot-lib can adopt it back when
  the C++ archetype catches up.
- Ticket 007's byte-exact loopback expectations update to the draft
  shapes (banner unchanged; PING now `ack 1 0` + `pong <now>`, etc.).
- ESTOP-silence tests flip to estop-replies tests.

## Sequencing

Land after ticket 008 (host prober, unaffected). Ticket 011 (join)
smoke-tests whatever protocol is current when it runs — it should run
AFTER this retarget so the join proves the draft protocol, not the
superseded one. Bench tickets 009/010 are AT-layer and unaffected.

## Related

[[port-v6-line-protocol-hard-cutover-from-v5]] — the completed base
this retargets.
