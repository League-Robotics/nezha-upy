---
id: '013'
title: 'Reconcile protocol test suite to the reliability-layer retarget: ESTOP-reply
  flips, loopback rewrite, fixture supersession'
status: done
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

- [x] Every ESTOP-silence assertion in
      `tests/unit/test_protocol_golden_vectors.py` is flipped to
      assert the `estop` reply (well-formed and trailing-junk cases
      both).
- [x] `test_help_matches_this_sprints_own_scoped_12_verb_list` (both
      copies — `test_protocol_golden_vectors.py` and
      `test_protocol_loopback_boot.py`) is renamed/updated to the
      13-verb, ack-first shape.
- [x] `test_protocol_loopback_boot.py`'s module docstring records the
      retarget decision (pointing at
      `reference/protocol-draft-2026-08-21.md`) rather than silently
      dropping its prior "pinned the committed text" reasoning.
- [x] Every literal reply string in `test_protocol_loopback_boot.py`
      is re-transcribed from `reference/protocol-draft-2026-08-21.md`,
      not copied from a first passing run.
- [x] `test_protocol_loopback_boot.py` gains an end-to-end `ESTOP`
      reply-flip test through the real boot-assembled engine.
- [x] `test_comms_loopback.py`'s `b"ok #1"` assertion and its four
      telemetry-cadence tests are updated for the `ack`-only success
      shape and the piggybacked reliability line respectively.
- [x] A repo-wide grep for stale `ok`/old-field-order-`err`/
      zero-field-session-verb literals in `tests/` turns up nothing
      unaddressed.
- [x] `python3 -m pytest tests/` fully green.
- [x] `git diff --exit-code -- vendor/` stays clean.

## Completion Notes (2026-08-21)

Worked file by file per the Implementation Plan's own order, running
the full suite after each file.

**`tests/unit/test_protocol_golden_vectors.py`** (hand-written
`def test_*` functions only -- the fixture-driven cases were already
green from ticket 012): every bare/no-id session-verb probe was
re-expressed with a sequenced `#id` and the expected `ack <id>
<lastDone>` line ahead of the verb's own reply; every `err #<id>
<code>`/bare-`err` assertion was rewritten `err <code> #<id>`, layered
after the ack; every `ok [#id]` assertion became a bare `ack` (no
second line on success). The three ESTOP-silence tests flipped to
assert the `estop` reply (well-formed, wrong-arity, and
trailing-id-shaped-junk cases all), and the side-by-side confirmation
test was rewritten to the same effect.
`test_help_lists_every_verb_this_sprint_scopes_including_stubs`/
`test_help_matches_this_sprints_own_scoped_12_verb_list` are now
`test_help_text_is_generated_from_the_dispatch_table` (updated in
place, unrenamed) and `test_help_matches_this_sprints_own_scoped_13_verb_list`,
both ack-first, 13-verb. The whole "malformed-line `#id` recovery"
subsection was rewritten around the new §8.4 three-way-classify-first
rule (its own header comment updated to stop quoting the deleted §2.3
text); several individual cases (`FOO #0`, `SET .../WHEELS .../STOP
#0`, the WHEELS-vs-STOP "#0-legality" pair) needed their OUTCOME
rewritten, not just their reply shape, because `#0` no longer
suppresses anything -- it is now always a retransmit (`ack 0 0`, no
verb lookup, `malformed_count()` untouched). Every id used across
GET/SET/TLM/WHEELS/STOP/HELP/PING/unknown-verb tests that used to be an
arbitrary correlation token (`#5`, `#7`, `#9`, `#42`, ...) was
recomputed against `expected_next` so the test still reaches the code
path it means to exercise, instead of accidentally landing in the
gap/nack branch. The embedded-NUL divergence test gained a sibling
(`..._with_an_in_order_id_gets_ack_then_err_unknown`) covering the §8.4
"ack + err 1" outcome the ticket's own description calls out, alongside
the original no-id "no reply at all" case (recovery probe fixed to a
sequenced `PING #1`). The two adversarial-recovery tests were audited
case by case (documented in each test's own updated docstring) to
confirm no case ever legitimately advances the sequence, then their
shared recovery probe was changed from bare `PING` to `PING #1`
(per-case sweep, fresh handler each time) / `PING #%d` climbing by one
per case (single-session sweep, one shared handler) -- every existing
input byte in `_ADVERSARIAL_RECOVERY_CASES` was kept unchanged, only
the expectations moved. `emit_telemetry()`'s five tests each gained the
piggybacked `ack 0 0` trailing line (§8.5) after every `t`/`thdr` frame
they assert on.

**`tests/test_protocol_loopback_boot.py`**: module docstring's
"design-authority resolution" section is now a "Design-authority
retarget" note -- the original reasoning for pinning the committed text
over the once-uncommitted draft is preserved verbatim as a blockquoted
historical record, followed by an explicit statement that the
2026-08-21 stakeholder retarget (ticket 012's issue) overrides it and
that `reference/protocol-draft-2026-08-21.md` is the current authority.
Every literal reply string was re-transcribed from that snapshot's §6/§8
tables (not copied from a first run): `PING`/`ID`/`VER`/`STATUS`/`HELP`
each gained a `#id` and an ack-first two-line (or, for `STATUS`, `next=`
key) assertion; `HELP` grew to the 13-verb list (test renamed
`..._13_verb_list`); the `WHEELS`/`STOP` pair test was renamed
`..._ack_and_err_pair...` and rewritten to the ack-alone success shape
plus the two-line, code-first `err` rejection shape. Added
`test_estop_reply_flip_matches_protocol_md_through_the_real_engine`: a
sequenced `PING` before and after an `ESTOP` proves the real,
boot-assembled `comms.py`/`protocol_adapter.py` wiring both replies
`estop` and leaves the sequence undisturbed, and asserts
`on_estop()` reached the real `_FakeDiffDrive` stub (not just a mock
handler) via a new `result.diffdrive = stub` convenience `_boot()` now
sets on the plain-attribute `BootResult` object.

**`tests/test_comms_loopback.py`**: the `b"ok #1"` assertion in
`test_two_transports_get_two_independent_handlers_sharing_one_adapter`
became `b"ack 1 0"`; its `GET`/`PING` probes on the second transport
gained their own in-order ids (`#1`, `#2`) since each transport's
handler sequences independently. The four telemetry-cadence tests
(`test_telemetry_off_emits_nothing_on_the_cadence`,
`test_telemetry_on_emits_every_cadence_tick_even_while_parked`,
`test_telemetry_auto_is_silent_while_parked_and_emits_while_active`,
`test_telemetry_header_re_emits_once_per_handler_only_on_change`) each
gained the trailing `b"ack 0 0"` piggyback line after every `t`/`thdr`
frame. `test_ping_replies_with_pong_and_the_adapters_now_value`/
`test_id_and_ver_replies`/`test_pump_reads_at_most_one_line_per_transport_per_call`
gained sequenced ids and their own ack-first assertions.

**`tests/test_boot_sequence.py`** (flagged by ticket 012's own
completion notes as extra scope for this ticket, not named in the issue
or this ticket's own description -- same root cause: a bare, id-less
`PING` through the real boot path): `_tick_and_get_replies()`'s default
`line` parameter changed from `b"PING"` to `b"PING #1"` (always in
order, since each call registers a fresh transport/handler); its three
callers (`test_happy_path_configures_diffdrive_and_boots_comms`,
`test_fail_closed_path_refuses_motion_but_keeps_comms_alive`,
`test_no_secrets_path_skips_wifi_but_boots_everything_else`) now expect
two replies (`b"ack 1 0"` then the `pong ...` line) instead of one.

**Repo-wide grep audit** (item 4): searched `tests/` for `b"ok`/`b'ok`,
`"err #`/`'err #`, and bare zero-field session-verb literals
(`b"PING\n"` etc.) after the three named files above were green. One
hit remained: `TLM\n` in
`test_tlm_bare_no_field_at_all_has_no_recoverable_id` -- confirmed
correct as-is (a `TLM` line with zero fields at all, not even an id,
is still "no trailing field" per §8.4 item 1, unaffected by the
retarget) and left untouched, not a leftover. No other file in
`tests/` referenced a stale wire shape.

**Implementation bugs found**: none. `src/core/protocol.py` was traced
against `reference/protocol-draft-2026-08-21.md` line by line while
redesigning every test above (id classification order, ack-before-verb-
lookup, `err` field order, `ESTOP`'s execute-then-reply ordering,
`STATUS`'s `next=` placement, `HELP`'s verb order, `RUN`'s outcome
table, the embedded-NUL divergence, and the `#0`-is-always-a-retransmit
rule) and no disagreement between the implementation and the snapshot
was found; every failure this ticket fixed was a pinned test asserting
the pre-retarget shape, never a implementation defect. `protocol.py`
and `hardware/protocol_adapter.py` were not modified by this ticket.

**Deleted/reshaped coverage, and why the old intent could not survive
unchanged** (none of these are a loss of coverage -- each is a case
whose PRECONDITION the retarget deleted, replaced by an equivalent or
stronger assertion of the new behavior):
- The WHEELS-vs-STOP "`#0` is legal on an optional-id verb, malformed
  on a required-id verb" asymmetry
  (`test_wheels_hash_zero_executes_silently_optional_id_verb` /
  `test_stop_hash_zero_is_malformed_required_id_verb`) no longer has a
  premise: every sequenced verb is mandatory-id now, so there is no
  more "optional-id verb" class for WHEELS to belong to. Replaced with
  `test_wheels_hash_zero_is_a_stale_retransmit_never_executes` /
  `test_stop_hash_zero_is_a_stale_retransmit_never_executes`, which
  pin the new, UNIFORM fact (`#0` is always a stale retransmit, for
  every sequenced verb, with no verb-specific carve-out) side by side,
  same as before.
- `test_tlm_invalid_mode_that_looks_like_an_id_still_recovers_it`'s
  premise (a trailing field that both "looks like an id" and "would be
  the mode field" gets recovered as an id via content inspection) is
  gone: under mandatory sequencing the id is UNCONDITIONALLY the last
  token regardless of content (§8.4), so `TLM #1` is not an
  invalid-mode-that-recovers case at all -- it is an ordinary wrong-arity
  case (zero mode fields). Replaced with
  `test_tlm_bare_id_only_has_zero_mode_fields_is_wrong_arity`, which
  pins that same shift explicitly in its own docstring.
- `test_wheels_bad_value_with_id_omitted_acks_bare_err`'s bare `err 2`
  (no id) reply no longer exists as a wire shape at all (§8.6: every
  `err` now implies a prior `ack` for the same mandatory id) -- renamed
  `test_wheels_bad_value_with_no_id_at_all_gets_no_reply` and re-pinned
  to the correct new outcome (unclassifiable line, no reply at all).
- `test_set_bad_value_with_id_zero_suppresses_reply` /
  `test_wheels_bad_value_with_id_zero_suppresses_reply`'s premise ("#0"
  suppresses every reply) is gone (§2.2: there is no way to suppress a
  reply any more) -- renamed and re-pinned to the new retransmit
  outcome (`ack 0 0`, value never even decoded).

No test's coverage was dropped outright; every case above still exists,
pinning the new behavior in the same place the old behavior used to be
pinned.

**Final test counts**: `python3 -m pytest tests/` -> **495 passed, 518
subtests passed**, zero failures (was 149 failed / 344 passed / 518
subtests passed before this ticket). `git diff --exit-code --
vendor/` -- clean (exit 0). `python3 -m pytest
tests/test_source_compile_gate.py` -- 24 passed (covers the mpy-cross
gate for `protocol.py`/`protocol_adapter.py`, both unmodified by this
ticket).

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
