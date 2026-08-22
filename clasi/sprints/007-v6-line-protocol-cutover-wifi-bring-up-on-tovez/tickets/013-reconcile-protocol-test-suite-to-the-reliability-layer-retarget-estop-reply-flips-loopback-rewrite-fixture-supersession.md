---
id: '013'
title: 'Reconcile protocol test suite to the reliability-layer retarget: ESTOP-reply
  flips, loopback rewrite, fixture supersession'
status: open
use-cases:
- SUC-001
- SUC-002
- SUC-005
depends-on:
- '012'
github-issue: ''
issue: retarget-v6-port-to-reliability-layer-draft.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Reconcile protocol test suite to the reliability-layer retarget: ESTOP-reply flips, loopback rewrite, fixture supersession

## Description

Ticket 012 retargets `protocol.py`/`protocol_adapter.py` to the
2026-08-21 reliability-layer draft (mandatory sequencing, `ack`/
`nack`, `err` field-order flip, `ESTOP` now replies, `RUN`/`debug`
added) and gets its *own* new fixture green, but deliberately leaves
this sprint's *pre-existing* tests red where they pin the old
scheme's literal shapes — several were written specifically to
assert the old design (some by name: `test_help_matches_this_
sprints_own_scoped_12_verb_list`), and one (`test_protocol_loopback_
boot.py`) explicitly documents, in its own module docstring, a
deliberate decision to pin the *previously-committed* text over an
already-known uncommitted draft. This ticket closes that gap: update
every existing test that encodes the superseded design, using ticket
012's new `reference/protocol-draft-2026-08-21.md` snapshot as the
one source of truth for every asserted shape (transcribed from the
snapshot, never copy-pasted from a first passing run — same
discipline ticket 007 itself established), and get `python3 -m
pytest tests/` fully green again.

**Known red spots this ticket must fix** (found by direct inspection
of the current suite; treat this as a floor, not a ceiling — audit
for any other old-shape assertion this list missed):

1. **`tests/unit/test_protocol_golden_vectors.py`'s hand-authored
   tests** (the fixture-driven parametrized cases are already fixed
   by ticket 012 pointing the harness at the new fixture — this
   ticket only touches the hand-written `def test_*` functions in
   this same file):
   - ESTOP-silence tests (`OUT NONE`/empty-sink assertions for both
     well-formed `ESTOP` and `ESTOP #5`, roughly lines 493-521 and
     1084-1106 as of this writing) — flip to assert the bare `estop`
     reply, for both the well-formed case and the "trailing junk"
     case (`ESTOP #5`, `ESTOP 1 2 3`) that used to be the interesting
     "still silent" case and is now the interesting "still replies,
     regardless of the junk" case.
   - `test_help_matches_this_sprints_own_scoped_12_verb_list` — the
     12-verb pin is gone (`RUN` is in scope now); rename and update
     to assert the 13-verb `HELP` text, reached via an in-order `#id`
     now that `HELP` is sequenced.
   - Any other hand-written test in this file asserting a bare `ok`,
     an `err #<id> <code>` (old field order), or a zero-field session
     verb — audit the whole file, not just the two spots named above.
2. **`tests/test_protocol_loopback_boot.py`** — this file's own
   docstring (top of file) records a deliberate, dated decision to
   pin the *previously-committed* protocol.md text over the draft
   that existed even at that ticket's own time — that decision is now
   explicitly superseded by the stakeholder's 2026-08-21 retarget
   decision (this issue). Rewrite:
   - Update the module docstring itself: the "design-authority
     resolution" section it currently carries (explaining why it
     pinned the committed text over the draft) is now historical —
     replace it with a short note pointing at
     `reference/protocol-draft-2026-08-21.md` as the current
     authority and at this ticket/issue as the retarget record. Do
     not just delete the old reasoning silently; a future reader
     should be able to see that a considered decision was made and
     then explicitly overridden by the stakeholder, not that nobody
     ever thought about it.
   - `test_banner_and_hello_match_protocol_md_literal_banner_shape`,
     `test_ping_matches_protocol_md_literal_pong_now_shape`,
     `test_id_and_ver_match_protocol_md_literal_shapes`,
     `test_status_carries_every_protocol_md_key_present_not_
     positional` — each needs its command line updated to carry a
     mandatory `#id` (these verbs had none before) and its
     assertion updated to expect the `ack <id> 0` line ahead of the
     verb's own informational reply; `STATUS`'s assertion also needs
     the new `next=` key.
   - `test_help_matches_this_sprints_own_scoped_12_verb_list` (this
     file has its own copy of this test, separate from #1's) — same
     12→13-verb fix, same ack-first shape.
   - `test_wheels_and_stop_ok_and_err_pair_matches_protocol_md_
     literal_shapes` — `WHEELS 50 50 500 #10` no longer replies
     `ok #10`; it replies `ack 10 0` (nothing else, success); `WHEELS
     50 50 6000 #11` no longer replies `err #11 3`; it replies
     `ack 11 0` **then** `err 3 #11` (two lines now, not one, and the
     field order is flipped) — same restructuring for the `STOP #12`
     pair.
   - Add at least one new case proving `ESTOP`'s reply flip
     end-to-end through the real boot-assembled engine (not just the
     mock-adapter harness ticket 012 already covers) — this file's
     whole reason to exist is proving the *wiring*, and `ESTOP`'s
     reply is exactly the kind of thing that could be right in the
     handler and wrong in how `comms.py`'s `_TransportSink` bridges
     it.
3. **`tests/test_comms_loopback.py`**:
   - `test_two_transports_get_two_independent_handlers_sharing_one_
     adapter` (around line 243) asserts `host_a.read_line() ==
     b"ok #1"` for what is presumably a `WHEELS`/`SET`-shaped command
     — update to the new `ack <id> <lastDone>`-only shape (no
     standalone `ok`).
   - `test_telemetry_off_emits_nothing_on_the_cadence`,
     `test_telemetry_on_emits_every_cadence_tick_even_while_parked`,
     `test_telemetry_auto_is_silent_while_parked_and_emits_while_
     active`, `test_telemetry_header_re_emits_once_per_handler_only_
     on_change` (lines ~279-325) — `emit_telemetry()` now *also*
     emits the piggybacked reliability line (`ack`/`nack`) after
     `thdr`/`t` on every call (§8.5); each of these tests' expected
     line count/content needs the extra trailing line accounted for,
     not just the `thdr`/`t` frame it currently checks.
4. **Audit for anything this list missed.** Grep the whole `tests/`
   tree for literal `b"ok`, `b'ok`, `err #`, and any zero-field
   session-verb command line (`b"PING\n"`, `b"STATUS\n"`, etc. with
   no `#id`) once tickets 012/013's own changes land, and fix any
   remaining hit — the four spots above are what direct inspection
   found before this ticket started, not a guaranteed-complete list.

## Acceptance Criteria

- [ ] Every ESTOP-silence assertion in
      `tests/unit/test_protocol_golden_vectors.py` is flipped to
      assert the `estop` reply (well-formed and trailing-junk cases
      both).
- [ ] `test_help_matches_this_sprints_own_scoped_12_verb_list` (both
      copies — `test_protocol_golden_vectors.py` and
      `test_protocol_loopback_boot.py`) is renamed/updated to the
      13-verb, ack-first shape.
- [ ] `test_protocol_loopback_boot.py`'s module docstring records the
      retarget decision (pointing at
      `reference/protocol-draft-2026-08-21.md`) rather than silently
      dropping its prior "pinned the committed text" reasoning.
- [ ] Every literal reply string in `test_protocol_loopback_boot.py`
      is re-transcribed from `reference/protocol-draft-2026-08-21.md`,
      not copied from a first passing run.
- [ ] `test_protocol_loopback_boot.py` gains an end-to-end `ESTOP`
      reply-flip test through the real boot-assembled engine.
- [ ] `test_comms_loopback.py`'s `b"ok #1"` assertion and its four
      telemetry-cadence tests are updated for the `ack`-only success
      shape and the piggybacked reliability line respectively.
- [ ] A repo-wide grep for stale `ok`/old-field-order-`err`/
      zero-field-session-verb literals in `tests/` turns up nothing
      unaddressed.
- [ ] `python3 -m pytest tests/` fully green.
- [ ] `git diff --exit-code -- vendor/` stays clean.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` (the full
  suite — this ticket's own gate is making it green again, not a
  subset).
- **New tests to write**: the `ESTOP`-reply-flip end-to-end test in
  `test_protocol_loopback_boot.py` (see Description item 2); no other
  wholly new test file is expected — this ticket is reconciliation of
  existing assertions, not new coverage (ticket 012 already owns the
  new `RUN`/`debug`/retransmit/gap coverage).
- **Verification command**: `python3 -m pytest tests/`

## Implementation Plan

**Approach**: Work file by file in the order listed in the
Description (golden-vectors hand-written tests, then loopback-boot,
then comms-loopback), running `python3 -m pytest tests/` after each
file so failures stay attributable to the file just touched rather
than piling up. Do the repo-wide grep audit (item 4) last, once the
three known files are green, so it is checking for genuine leftovers
rather than things already mid-fix.

**Files to modify**:
- `tests/unit/test_protocol_golden_vectors.py` — hand-written
  `def test_*` functions only (the fixture-driven cases are already
  handled by ticket 012's fixture re-point).
- `tests/test_protocol_loopback_boot.py` — module docstring + every
  named test above + the new ESTOP end-to-end test.
- `tests/test_comms_loopback.py` — the one literal-shape assertion +
  the four telemetry-cadence tests.
- Any other file the item-4 grep audit turns up.

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: none beyond the docstring rewrite already
named in Description item 2 — this ticket does not touch
`docs/design/` (this project has no design-doc opt-in, per sprint.md's
Use Cases section) or `sprint.md` itself (the sprint-planner owns
that).
