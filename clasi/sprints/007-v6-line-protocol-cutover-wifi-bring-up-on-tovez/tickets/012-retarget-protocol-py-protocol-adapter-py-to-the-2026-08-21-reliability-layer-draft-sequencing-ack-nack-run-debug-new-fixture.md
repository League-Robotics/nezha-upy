---
id: '012'
title: 'Retarget protocol.py/protocol_adapter.py to the 2026-08-21 reliability-layer
  draft: sequencing, ack/nack, RUN/debug, new fixture'
status: done
use-cases:
- SUC-001
- SUC-002
- SUC-005
depends-on:
- '007'
- 008
github-issue: ''
issue: retarget-v6-port-to-reliability-layer-draft.md
completes_issue: true
---
<!-- CLASI: Before changing code or making plans, review the SE process in CLAUDE.md -->

# Retarget protocol.py/protocol_adapter.py to the 2026-08-21 reliability-layer draft: sequencing, ack/nack, RUN/debug, new fixture

## Description

Mid-sprint retarget (stakeholder decision, 2026-08-21 — see
[[retarget-v6-port-to-reliability-layer-draft]]): tickets 001–007
ported `protocol.py`/`protocol_adapter.py` against the protocol.md
text committed at session start (`c99e6e8`, colon→space/`#id`
grammar plus `debug`/`RUN`, no reliability layer). The upstream
design has since moved again, in the *uncommitted* working tree of
`radio-robot-lib/docs/design/protocol.md` (base commit `c99e6e8`,
~540 added lines rewriting §8): every sequenced command now carries a
**mandatory** sequence id and gets a transport-layer `ack`/`nack`;
`ok` is deleted; `err`'s field order flips; `ESTOP` gains a reply;
`RUN`/`debug` (already ticket-001–007-excluded) come into scope for
the first time. This ticket makes that draft real in this repo's own
handler/adapter, so the port stops leading an unfixed target.

**Step 0 — snapshot the design authority.** Copy
`radio-robot-lib/docs/design/protocol.md` **verbatim, in full** (not
just the changed sections) into `reference/protocol-draft-2026-08-21.md`
in this repo, with a short header noting provenance: base commit
`c99e6e8`, upstream working tree uncommitted as of 2026-08-21 (`git
status --short -- docs/design/protocol.md` in `radio-robot-lib` shows
` M docs/design/protocol.md`). From this point on, **this snapshot —
not the live upstream file — is this ticket's and ticket 013's design
authority**; if the upstream working tree moves again before this
lands, that is not this ticket's problem to track.

**Step 1 — rewrite `protocol.py`'s dispatch core around mandatory
sequencing (§2.2, §8).** The handler gains three new pieces of
per-instance state (alongside the existing `_header_names`/
`_header_hex`/`_ever_emitted_header` — same "one handler per
transport" reasoning, sprint.md's Design Rationale):

```
expected_next = 1     # next id expected from this transport's host
last_done     = 0     # plumbed, never written (see below) — §8.5.1
gap_outstanding = False
```

`HELLO` resets all three (`expected_next=1`, `last_done=0`,
`gap_outstanding=False`) before sending the banner — same as today,
just three fields now instead of none.

**Dispatch restructures around id-extraction-before-verb-lookup**
(§8.4), replacing essentially all of the current per-verb
`ID_OMITTED`/`ID_ZERO`/`ID_NONZERO`/`resolve_trailing_optional_id()`
machinery (§2.2: "`#0` is deleted as a special case... falls into the
ordinary stale/retransmit bucket with no special-casing at all" — the
whole optional-id outcome enum this port currently has is obsolete,
not merely extended):

1. Verb is `ESTOP` → §8.3's exemption path (below). Verb is `HELLO`
   → existing zero-field-only path, reset state, banner; no id ever
   accepted (a trailing token on `HELLO` is wrong arity, same as
   today).
2. Otherwise every verb in scope (`PING ID VER STATUS HELP GET SET
   TLM WHEELS STOP RUN`) is now sequenced — the *previously*
   zero-field session verbs (`PING`/`ID`/`VER`/`STATUS`/`HELP`) each
   gain exactly one mandatory field (`#id`); `GET`/`TLM` (previously
   no id channel at all) gain one too.
3. Before any verb lookup: is there a trailing field at all? No →
   malformed, no reply (§8.4.1). Is it well-formed `#[0-9]+`? No →
   malformed, no reply (§8.4.2) — this collapses the *entire* old
   `_reject_malformed()`/`_recover_trailing_id()` id-recovery path;
   nothing is recovered from an ill-formed id any more, because there
   is no longer a reply channel without one.
4. A well-formed id classifies via §8.1's three-way table, **using
   only the id — the verb is not even looked up yet**:
   - `< expected_next` (retransmit): do **not** execute or look up
     the verb at all; reply `ack <expected_next-1> <last_done>`.
     `malformed_count()` is untouched (§9.8 item 2).
   - `> expected_next` (gap): do **not** execute; reply
     `nack <expected_next> <last_done>`; set `gap_outstanding = True`
     (see "Resolved ambiguity" below). `malformed_count()` untouched.
   - `== expected_next` (in order): `expected_next = id + 1`;
     `gap_outstanding = False`; reply `ack <id> <last_done>`
     **unconditionally, before the verb is looked up** (§9.8 item 4)
     — *then* look up the verb over the *remaining* fields (id token
     already stripped): unrecognized verb → `malformed_count()`++,
     `err 1 #<id>`; recognized but wrong remaining-field-count or an
     unparseable field → `malformed_count()`++, `err 2 #<id>`;
     recognized and parses → call the verb's own body, which now
     never itself sends `ok`/`ack` (that already happened) and only
     ever optionally sends its own informational reply and/or
     `err <code> #<id>` on adapter rejection (§8.2 — `err`'s field
     order is `err <code> #<id>`, flipped from today's `err #<id>
     <code>`, §8.6).

**Step 2 — per-verb reply bodies, once reached (i.e. only on an
in-order id — every verb below assumes the ack already fired):**

| verb | success reply (beyond the ack) | rejection reply |
|---|---|---|
| `PING`/`ID`/`VER`/`STATUS`/`HELP` | same literal text as today (`STATUS` gains a `next=<expected_next>` key; `HELP` grows to 13 verbs, `RUN` appended — same "generated from `VERB_TABLE`" mechanism) | `err 2 #<id>` if a stray field survives past the id |
| `GET` | `get name value` per resolved field, or nothing for an unknown/bare-empty name — **unknown name still gets the ack, no `err`** (§6 table note) | `err 2 #<id>` only for a malformed *shape* (too many fields before the id) |
| `SET` | nothing — the ack **is** the acceptance (`ok` deleted, §8.2) | `err 1 #<id>` (unknown name) / `err 2 #<id>` (unparseable value) |
| `TLM` | nothing (adapter `Result` never surfaces, same posture as today) | `err 2 #<id>` for an unparseable mode string — see "Resolved ambiguity" below |
| `WHEELS` | nothing | `err 2 #<id>` (unparseable field) / `err <result_code> #<id>` (adapter rejection, e.g. range) |
| `STOP` | nothing | `err <result_code> #<id>` |
| `RUN` | `ret <value> #<id>` (value sanitized like `debug`'s text: strip `\n`/`\r`, truncate to the 240-byte line cap) if the function returned a value; nothing if void | `err 1 #<id>` (unknown function) / `err 2 #<id>` (wrong arity / bad convert / bare `RUN #<id>` with no function name) |

**Step 3 — `ESTOP`/`HELLO` exemption (§8.3), superseding this port's
current behavior:** `ESTOP` is removed from sequencing entirely — no
id, never nacked, and its own arity check is **deleted outright**
(today's code still counts a malformed `ESTOP` via a manual
`self._malformed_count += 1`; under the draft, *any* line whose verb
token is `ESTOP` — `ESTOP`, `ESTOP 1 2 3`, `ESTOP #5`, `ESTOP #abc` —
executes the stop with no arity inspection at all, so there is no
"wrong arity" case left to count). **Execute the kernel call first,
then write the reply** — `estop`, bare, no fields, written after
`_adapter.on_estop()` returns. This **flips SUC-002** ("ESTOP never
replies") to its opposite; ticket 013 owns updating the tests that
pin the old silence.

**Step 4 — add `RUN`/`debug` (§6.2, §6.3), in scope for the first
time (this port's current module docstring explicitly says "NEITHER
is ported here at all" — that line becomes false):**
- `ProtocolHandler.send_debug(text)`: unsolicited emission (like
  `send_banner()`), never reached through `feed()`. `text` is
  sanitized (`\n`/`\r` stripped) and the whole formatted line
  truncated (never overflowed) to the 240-byte cap.
  `send_debug("")`/`send_debug(None)` both emit the bare `debug\n`
  line — no dangling separator space.
- `_handle_run(fields, ...)`: parses only — function name (first
  remaining field after id-extraction) + the rest as raw argument
  tokens — and hands them to `adapter.on_run(name, args)`. The
  handler holds no function table and does no type conversion (§6.3
  — mirrors `GET`/`SET`'s "handler holds no tables" posture exactly).
  A bare `RUN` with no fields at all (not even the id) is malformed
  per Step 1's item 3 (no trailing field). `RUN #7` (the id consumed
  the only field, no function name) → ack + `err 2 #<id>` (§6.3's own
  explicit example).

**Step 5 — `protocol_adapter.py`'s `on_run(name, args)` (§6.3):** add
one new method, with an **explicit registration allowlist as the
security boundary** — mirror the archetype's own `DiffDriveAdapter`
posture exactly: register nothing by default, so every `RUN` this
adapter receives answers `ERR_UNKNOWN`. Provide the allowlist as a
real, inspectable data structure (e.g. a `{name: callable}` dict
built at construction, with a small `register()`/registration-list
constructor argument for a future ticket to populate) — **do not**
implement this as a `globals()`/`getattr(module, name)` blanket
lookup (§9.7's own explicit warning to a dynamic-language porter:
"everything importable is remotely callable unless the porter
deliberately restricts it"). This ticket registers nothing real; it
only proves the allowlist mechanism itself (empty → `ERR_UNKNOWN`
for anything).

**Step 6 — author a new golden-vector fixture from the draft's own
tables, point the harness at it, mark the old one superseded.** The
existing `tests/fixtures/protocol_golden_vectors.txt` gates the OLD
(pre-retarget) scheme — most of its `ok`/`err`/bare-reply vectors are
now wrong by design. Do not delete it (this project's own convention,
and radio-robot-lib may still want it if the C++ archetype hasn't
caught up yet either): add a `# SUPERSEDED 2026-08-21` banner comment
at its top explaining why it no longer gates anything, and author a
sibling fixture (e.g. `tests/fixtures/protocol_golden_vectors_reliability.txt`)
built mechanically from §6's verb table and §8's three-way
classification table plus this ticket's own new `RUN`/`debug`
vectors — cover, at minimum: in-order ack for each verb family,
retransmit (id `< expected_next`, confirming no re-execution — e.g. a
resent `WHEELS` must not drive the wheels twice), gap (id `>
expected_next`, confirming no execution and the stalled-stream nack),
`err` field-order (`err <code> #<id>`), `HELLO`'s reset, `ESTOP`'s
new `estop` reply and forgiveness, `STATUS`'s `next=` key, `RUN`'s
full outcome matrix, `debug`'s sanitization. Point
`tests/unit/test_protocol_golden_vectors.py`'s fixture-driven harness
at the new file (the hand-authored `def test_*` functions in that
same file that pin the *old* ESTOP-silence/12-verb-HELP shapes are
ticket 013's job, not this one — leave them failing/red if this
ticket lands standalone; ticket 013 depends on this one specifically
so it can fix them next).

**Resolved ambiguities this ticket makes explicit** (mirroring this
project's own established convention of flagging, not silently
picking, a fork the draft leaves open — protocol.py's module
docstring and protocol.md's own §9.8 are full of these):

1. **`gap_outstanding`'s set/clear transitions.** The draft's state
   block calls it "a nack is currently owed" but never states exactly
   when it flips. Resolved here: set `True` the instant the `>`
   (gap) branch fires; set `False` the instant the `==` (in-order)
   branch fires; the `<` (retransmit) branch never touches it. This
   is the simplest reading consistent with §8.5's own description
   ("as long as telemetry keeps flowing, a gap keeps producing fresh
   nacks... until the missing id arrives") and needs no extra
   bookkeeping beyond the boolean flip already required.
2. **`TLM` with an unparseable mode string.** §6's table shows `TLM`'s
   own success-path reply as "—", which could be misread as "TLM
   never emits `err`, full stop." Resolved: that row describes the
   *success* case (mode decoded, delegated) — an unparseable mode
   string (not one of the six literal names) is an ordinary §8.4
   item-3 "unparseable field" and gets `ack` + `err 2 #<id>`, exactly
   like every other verb's content-decode failure. Only the
   *adapter's* `on_tlm()` `Result` is the thing that never surfaces.
3. **`ESTOP`'s `malformed_count()`.** Under the draft, `ESTOP` never
   inspects its own fields at all (§8.3's "regardless of trailing
   junk or arity"), so there is no wrong-arity case left to detect —
   resolved: `ESTOP` never increments `malformed_count()`, for any
   input, superseding today's code (which still bumps it on a
   trailing-field `ESTOP`).

If a reviewer disagrees with any of these three, that is exactly the
kind of thing to override in review — they are recorded, not hidden.

## Acceptance Criteria

- [x] `reference/protocol-draft-2026-08-21.md` exists: a verbatim,
      full-file snapshot of `radio-robot-lib/docs/design/protocol.md`
      as of this ticket's work, with a provenance header (base commit
      `c99e6e8`, uncommitted upstream working tree).
- [x] `protocol.py` implements `expected_next`/`last_done`/
      `gap_outstanding` as per-`ProtocolHandler`-instance state, reset
      by `HELLO`.
- [x] Every verb in `PING ID VER STATUS HELP GET SET TLM WHEELS STOP
      RUN` requires a mandatory trailing `#id`, classified via the
      three-way table (§8.1) *before* verb lookup; `HELLO`/`ESTOP`
      remain unsequenced.
- [x] `ok` is gone from every code path; `ack <n> <lastDone>` /
      `nack <n> <lastDone>` are emitted exactly per §8.1/§8.4; a
      retransmit (`< expected_next`) never re-executes the verb (a
      resent `WHEELS` does not drive the wheels twice — this needs an
      explicit test, not just inspection).
- [x] `err <code> #<id>` (code first) replaces the old `err #<id>
      <code>` everywhere; the bare `err <code>` (no-id) form is gone.
- [x] `ESTOP` replies the bare word `estop`, written after
      `on_estop()` executes, for any input whose verb token is
      exactly `ESTOP` (well-formed or with trailing junk) — never
      increments `malformed_count()`.
- [x] `STATUS`'s reply carries a `next=<expected_next>` key in
      addition to its existing keys.
- [x] `HELP`'s reply lists 13 verbs, `RUN` last.
- [x] `ProtocolHandler.send_debug(text)` exists: sanitizes `\n`/`\r`,
      truncates to the 240-byte line cap, and `send_debug("")`/
      `send_debug(None)` both emit the bare `debug` line.
- [x] `RUN <function> [arg...] #id` is dispatched per the outcome
      table in the Description (unknown/badarg/void/value-returning/
      bare-`RUN`/`RUN #<id>`-only cases all covered).
- [x] `hardware/protocol_adapter.py` gains `on_run(name, args)` backed
      by an explicit, empty-by-default registration allowlist (not
      `globals()`); an unregistered `RUN` call returns
      `Result.UNKNOWN`.
- [x] `tests/fixtures/protocol_golden_vectors.txt` carries a
      `# SUPERSEDED 2026-08-21` banner and is otherwise untouched
      (kept, not deleted).
- [x] A new fixture (e.g. `tests/fixtures/protocol_golden_vectors_reliability.txt`)
      exists, authored from §6/§8's own tables plus this ticket's
      `RUN`/`debug` additions, and the CPython harness in
      `tests/unit/test_protocol_golden_vectors.py` is re-pointed at it
      for its fixture-driven (non-hand-authored) test cases.
- [x] `mpy-cross` compiles `src/core/protocol.py` and
      `src/hardware/protocol_adapter.py` cleanly.
- [x] `git diff --exit-code -- vendor/` stays clean.

## Completion Notes (2026-08-21)

**Built**: Step 0's snapshot at `reference/protocol-draft-2026-08-21.md`
(1363 lines incl. an 16-line provenance header, byte-for-byte diff
against the upstream working tree's `docs/design/protocol.md` is
empty). `src/core/protocol.py`'s dispatch core was rewritten around
id-extraction-before-verb-lookup (`_dispatch_sequenced()`), replacing
the entire `ID_OMITTED`/`ID_ZERO`/`ID_NONZERO`/`ID_MALFORMED`/
`resolve_trailing_optional_id()`/`_recover_trailing_id()`/
`_reject_malformed()`/`_reply_ok*`/`_reply_err_bare` machinery per the
plan; `VERB_TABLE` now lists all 13 verbs (`_SEQUENCED_VERB_TABLE`
mechanically derived, excluding `HELLO`/`ESTOP`). `send_debug()`/
`_handle_run()` added; `hardware/protocol_adapter.py` gained
`on_run()`/`register_run()` with a plain-dict allowlist, empty by
default. New fixture `tests/fixtures/protocol_golden_vectors_reliability.txt`:
**37 blocks**, covering in-order ack per verb family (10 blocks),
retransmit + gap (2 blocks), the gap-stall-and-self-heal chain (1
multi-action block), ack+err layering incl. adapter-level rejection (3
blocks), the two "no trailing field / malformed id" no-reply cases (2
blocks), HELLO's reset (1 block), ESTOP's forgiveness matrix (4
blocks), RUN's full outcome matrix (6 blocks), telemetry piggyback incl.
the gap/nack variant (2 blocks), and `debug` (2 blocks) — all 37 pass
against the retargeted handler on the first run after authoring from
the spec tables (no vectors needed correction against the
implementation). The old fixture keeps its `# SUPERSEDED 2026-08-21`
banner, untouched otherwise.
`tests/unit/test_protocol_golden_vectors.py`'s fixture-driven harness
(`_FIXTURE_PATH`, `_apply_setup`, `_run_block`, the `test_golden_vector_block`
parametrization) is re-pointed at the new fixture; the now-pointless
skip/`_classify()` machinery (nothing is out-of-scope any more) was
removed. Added 7 new hand-written tests at the end of that same file
(clearly delimited, "ticket 012 ... new reliability-layer tests")
covering what the fixture alone cannot prove: retransmit/gap
non-re-execution via `wheels_calls` count, `ESTOP` never incrementing
`malformed_count()`, and `debug`/`RUN`'s embedded-`\n`/`\r`
sanitization and 240-byte truncation. Added 6 new tests to
`tests/test_protocol_adapter.py` for `on_run()`'s allowlist mechanics
(empty-by-default UNKNOWN, no `globals()`/`getattr()` reachability,
`register_run()` success/void/exception-to-BADARG cases, and an
end-to-end `ProtocolHandler.feed()` round trip), and fixed that same
file's one pre-existing test that assumed id-less `TLM`/`STATUS` lines
(`test_tlm_mode_is_shared_across_two_protocol_handler_instances`) —
this is an adapter-sharing test, not a wire-shape pin, and the fix is
mechanical (add `#1` to both lines), so it was kept in this ticket's
own scope rather than left for ticket 013.

**Full suite**: `python3 -m pytest tests/` → **149 failed, 344 passed,
518 subtests passed** (was 476 passed / 11 skipped / 518 subtests
before this ticket). Every failure is a downstream consequence of this
retarget's own wire-shape changes (mandatory ids on session verbs,
`ok` deletion, `ESTOP` now replying, 13-verb `HELP`) hitting a
hand-authored test that still pins the pre-retarget shape — none are
new bugs. Exactly four files fail, all pre-existing (none touched by
this ticket beyond the one adapter-sharing fix above):

- `tests/unit/test_protocol_golden_vectors.py` — **134 failed**, all
  hand-authored `def test_*` functions (not fixture-driven blocks —
  every one of the 37 new fixture blocks and all 7 of this ticket's own
  new hand-written tests pass). Failure classes: (a) the `feed()`
  boundary/blank-line/case/malformed-recovery tests whose own "prove it
  still works" recovery probe is a bare, id-less `PING`/`HELLO`, now
  malformed with no reply instead of `pong <n>`; (b) every
  `test_wrong_arity_*_recovers_id`/`test_*_gets_err_unknown`-style test
  built on the deleted optional-id recovery rule; (c) all three
  `test_estop_*` tests pinning "ESTOP never replies"; (d)
  `test_help_text_is_generated_from_the_dispatch_table` /
  `test_help_lists_every_verb_this_sprint_scopes_including_stubs`
  (12-verb HELP, no ids); (e) every GET/SET/TLM/WHEELS/STOP test built
  on `ok #id`/bare `ok`/`#0`-suppression/`err #id <code>` shapes; (f)
  every `test_emit_telemetry_*` test, since `emit_telemetry()` now also
  emits the reliability piggyback line; (g)
  `test_embedded_nul_immediately_after_verb_is_rejected_not_truncated`
  and all 64 `test_recovers_after_adversarial_input[...]`/the one
  `test_recovers_after_every_adversarial_input_in_one_session` case,
  whose shared recovery probe is the same bare, id-less `PING`.
- `tests/test_protocol_loopback_boot.py` — **5 failed** (of 6):
  `test_ping_matches_protocol_md_literal_pong_now_shape`,
  `test_id_and_ver_match_protocol_md_literal_shapes`,
  `test_status_carries_every_protocol_md_key_present_not_positional`,
  `test_help_matches_this_sprints_own_scoped_12_verb_list`,
  `test_wheels_and_stop_ok_and_err_pair_matches_protocol_md_literal_shapes`
  — all send id-less commands and/or assert the old `ok #id`/`err #id
  <code>` shapes through the real boot-assembled engine.
- `tests/test_comms_loopback.py` — **7 failed** (of 13):
  `test_ping_replies_with_pong_and_the_adapters_now_value`,
  `test_id_and_ver_replies`,
  `test_pump_reads_at_most_one_line_per_transport_per_call`,
  `test_two_transports_get_two_independent_handlers_sharing_one_adapter`,
  `test_telemetry_on_emits_every_cadence_tick_even_while_parked`,
  `test_telemetry_auto_is_silent_while_parked_and_emits_while_active`,
  `test_telemetry_header_re_emits_once_per_handler_only_on_change` —
  the first four send id-less `PING`/`ID`/`VER`; the telemetry three
  assert an exact reply count/shape that doesn't yet account for the
  piggybacked reliability line.
- `tests/test_boot_sequence.py` — **3 failed** (of 6, NOT named in the
  ticket text but found by this ticket's own full-suite run, same root
  cause): `test_happy_path_configures_diffdrive_and_boots_comms`,
  `test_fail_closed_path_refuses_motion_but_keeps_comms_alive`,
  `test_no_secrets_path_skips_wifi_but_boots_everything_else` — each
  drives a bare, id-less `PING` through the real boot-assembled engine
  via its own `_tick_and_get_replies()` helper and asserts exactly one
  reply comes back; now zero do (malformed, no reply), since `PING` is
  a mandatory-id verb as of this retarget. Flagging this file
  explicitly for ticket 013 since it was not in this ticket's or the
  issue's own named list.

**mpy-cross / vendor gates**: `python3 -m pytest tests/test_source_compile_gate.py`
— 24 passed (covers both `protocol.py` and `protocol_adapter.py` via
its existing glob). `git diff --exit-code -- vendor/` — clean (exit 0).

**Draft vs. the three recorded ambiguity resolutions**: sanity-checked
all three against `reference/protocol-draft-2026-08-21.md` while
implementing; the draft text does not contradict any of them —
`gap_outstanding`'s set/clear transitions (§8.1's own state-block
comment "a nack is currently owed", read alongside §8.5's "as long as
telemetry keeps flowing, a gap keeps producing fresh nacks"), TLM's
unparseable-mode ack+err2 treatment (§8.4 item 3's general rule, §6's
"—" being the success-path entry only), and ESTOP never incrementing
`malformed_count()` (§8.3's "regardless of trailing junk or arity, ANY
line whose verb token is ESTOP executes") are all directly consistent
with the implementation as built. The draft was silent on one small
corner this ticket had to decide on its own: `RUN`'s `ret <value>
#<id>` line is truncated to the 240-byte cap as ONE formatted string
(matching `send_debug()`'s own treatment literally, per §6.3's "sanitized
... exactly like debug's text"), which means a sufficiently long
returned value could in principle truncate into the trailing `#<id>`
token itself — the draft does not address preserving the id during
this truncation (unlike, e.g., its explicit id-is-always-last-token
framing elsewhere), and this port did not invent a special case for it
since no worked example or test calls for one.

## Testing

- **Existing tests to run**: `python3 -m pytest tests/` — expected
  **not** fully green after this ticket alone (the hand-authored
  ESTOP-silence/12-verb-HELP tests and `test_protocol_loopback_boot.py`/
  `test_comms_loopback.py`'s literal old-shape assertions are ticket
  013's job); the new fixture-driven vectors and any new
  hand-written tests this ticket adds must themselves be green.
- **New tests to write**: the new reliability-layer fixture (above);
  an explicit "resent id does not re-drive the wheels" test (mock
  adapter records call count); an adapter-level test proving
  `on_run()`'s empty-allowlist-by-default posture
  (`tests/test_protocol_adapter.py` is the natural home, matching its
  existing fake-diffdrive convention).
- **Verification command**: `python3 -m pytest tests/unit/test_protocol_golden_vectors.py -k "not <the old hand-authored ESTOP/HELP test names>"` for this ticket's own scope, plus `mpy-cross src/core/protocol.py src/hardware/protocol_adapter.py`; the *full* `python3 -m pytest tests/` gate is ticket 013's to close green.

## Implementation Plan

**Approach**: Do Step 0 (snapshot) first so the rest of this ticket
has a fixed, cross-repo-drift-proof text to implement against. Then
rewrite `protocol.py`'s dispatch skeleton (Steps 1-2) before touching
`ESTOP`/`RUN`/`debug` (Steps 3-4) — the id-extraction-before-lookup
restructuring is the one change every other verb's behavior sits on
top of, so getting it right first makes every later verb a smaller,
independent diff. Do `protocol_adapter.py`'s `on_run()` (Step 5) once
`RUN`'s handler-side contract is settled. Author the new fixture
(Step 6) last, deriving vectors mechanically from the now-implemented
behavior's own spec sections rather than from a first passing run
(same "transcribed from the design doc" discipline ticket 007 already
established) — write vectors from protocol.md §6/§8's tables, then
confirm the implementation satisfies them, not the reverse.

**Files to create**:
- `reference/protocol-draft-2026-08-21.md` (new, verbatim snapshot +
  provenance header).
- `tests/fixtures/protocol_golden_vectors_reliability.txt` (new
  fixture; name is this ticket's own call).

**Files to modify**:
- `src/core/protocol.py` — the dispatch/sequencing rewrite (Steps
  1-4), including deleting `ID_OMITTED`/`ID_ZERO`/`ID_NONZERO`/
  `ID_MALFORMED`/`resolve_trailing_optional_id()`/
  `_recover_trailing_id()`/`_reject_malformed()`/`_reply_ok`/
  `_reply_ok_bare`/`_reply_err_bare` (all obsolete under mandatory
  sequencing) and updating the module's own extensive docstring,
  which currently documents the *old* optional-id design as if it
  were still current.
- `src/hardware/protocol_adapter.py` — `on_run()` + allowlist (Step
  5); update its module docstring's own "NEITHER RUN nor debug is
  ported" framing (that's `protocol.py`'s docstring, but check this
  file's cross-references too).
- `tests/fixtures/protocol_golden_vectors.txt` — superseded banner
  only, no content change.
- `tests/unit/test_protocol_golden_vectors.py` — re-point the
  fixture-driven harness at the new file; leave the file's own
  hand-authored `def test_*` functions untouched (ticket 013).

**Testing plan**: see Acceptance Criteria / Testing above.

**Documentation updates**: `protocol.py`'s module docstring (extensive
design-decision commentary keyed to the old optional-id scheme) needs
a substantial rewrite, not a patch — it currently asserts things
("ids are optional", "`STOP`'s id is REQUIRED, not optional — unlike
every other verb") that become actively wrong under the retarget.
