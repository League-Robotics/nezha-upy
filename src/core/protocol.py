"""protocol -- v6 ASCII line-grammar handler + reliability layer
(``reference/protocol-draft-2026-08-21.md`` Sec 2-8, this repo's own
snapshot of radio-robot-lib's uncommitted design draft; see that file's
provenance header for exactly which upstream commit/working-tree state
it was taken from).

Ported from radio-robot-lib's ``src/protocol/protocol_handler.{h,cpp}``
(the C++ archetype) -- read that file's own header first if extending
this module. This file re-derives none of the archetype's own grammar
calls; see the snapshot's Sec 9 for the full resolution history and
``clasi/sprints/007-.../sprint.md``'s Architecture section (including
its 2026-08-21 "Revision" note) for this repo's own port-level
decisions.

**2026-08-21 retarget (sprint 007 ticket 012).** Tickets 001-007 ported
this module against the pre-reliability-layer draft: ids were an
OPTIONAL, host-assigned correlation token (``#0`` suppressed a reply
entirely; an omitted id gave a bare ``ok``/``err <code>``); acceptance
was signaled by ``ok``; ``err``'s field order was ``err #<id> <code>``;
``ESTOP`` never replied, even when malformed; ``RUN``/``debug`` were
out of this sprint's scope entirely. Ticket 012 retargets all of that
to the stakeholder's reliability-layer design (snapshot Sec 8):

- **Every sequenced verb now carries a MANDATORY, strictly-increasing
  ``#<id>``** -- ``PING ID VER STATUS HELP GET SET TLM WHEELS STOP
  RUN``. ``HELLO``/``ESTOP`` are the only two verbs excluded from
  sequencing at all (snapshot Sec 8.3) -- excluded by verb IDENTITY,
  checked before the id-extraction step even runs, not folded into the
  generic path with an exception bolted on (this is the "one rule, not
  a rule-plus-a-carve-out" property the snapshot's own Sec 8.4 calls
  out as cleaner than the old Sec 2.3 recovery rule it replaces).
- **``ok`` is gone.** An in-order id's ``ack <id> <lastDone>`` -- sent
  UNCONDITIONALLY, before the verb is even looked up -- *is* the
  acceptance signal (snapshot Sec 8.2). ``err``'s field order flips to
  ``err <code> #<id>`` (code first, snapshot Sec 8.6) and is now always
  a SECOND line layered on top of an already-sent ``ack``, never a
  replacement for it, and never sent bare (with no id).
- **A well-formed id classifies via a three-way table BEFORE the verb
  is even looked up** (snapshot Sec 8.1/8.4): ``== expected_next`` ->
  dispatch, advance, ``ack``; ``< expected_next`` -> retransmit, do NOT
  re-execute, ``ack`` against the highest already-accepted id; ``>
  expected_next`` -> gap, do NOT execute, ``nack``, and every
  subsequent command (however well-formed) keeps nacking until the
  missing id arrives (a stalled stream self-heals because a fresh nack
  rides every new inbound line). ``#0`` is no longer a special
  suppression spelling -- since ids start at 1, an inbound ``#0``
  always falls into the ordinary retransmit bucket.
- **``ESTOP`` now replies** the bare word ``estop``, written AFTER
  ``on_estop()`` executes, for ANY line whose verb token is exactly
  ``ESTOP`` -- well-formed or with arbitrary trailing junk. It never
  increments ``malformed_count()`` any more (there is no arity to
  inspect at all under this rule).
- **``STATUS`` gains a ``next=<expected_next>`` key**; ``HELP`` grows
  to 13 verbs (``RUN`` appended last); ``emit_telemetry()`` now also
  piggybacks the current reliability line on every call (no timer
  added -- this rides the existing telemetry cadence, snapshot Sec
  8.5); ``RUN``/``debug`` (invocation-by-name, robot-to-host-only
  unsolicited text) are ported for the first time (snapshot Sec 6.2/
  6.3).
- Obsolete under mandatory sequencing, and DELETED from this module:
  the whole optional-id outcome enum (``ID_OMITTED``/``ID_ZERO``/
  ``ID_NONZERO``/``ID_MALFORMED``/``resolve_trailing_optional_id()``)
  and the old malformed-line ``#id``-recovery path
  (``_recover_trailing_id()``/``_reject_malformed()``/``_reply_ok``/
  ``_reply_ok_bare``/``_reply_err_bare``) -- there is no longer a reply
  channel without a valid, in-order id to anchor one against, so
  nothing is ever "recovered" from an otherwise-unusable line any more.

Grammar (unchanged by the retarget -- snapshot Sec 2), in one line::

    line   ::= sp? verb ( sp field )* sp? '\\n'
    sp     ::= ' '+
    verb   ::= [A-Za-z][A-Za-z0-9_]*
    field  ::= any bytes except ' ' and '\\n'
    id     ::= '#' [0-9]+        (a field in trailing position)

A run of spaces is ONE separator; leading/trailing line whitespace is
ignored; a blank/all-whitespace line is ignored SILENTLY (not
malformed). Case is direction: commands are UPPERCASE, replies are
lowercase, and verb lookup is case-sensitive -- a lowercase-led line is
another robot's reply overheard on a shared channel and is dropped
silently (Sec 2.1) -- this check still runs FIRST, before anything else
in ``_dispatch()``, unchanged by the retarget.

Dispatch order (snapshot Sec 8.3/8.4, this module's own ``_dispatch()``):
lowercase-drop -> (blank-line-silence and the 240-byte overlong-discard
already happened during line reassembly, before ``_dispatch()`` is ever
called) -> verb token read -> ``ESTOP`` (maximally forgiving: executes,
then replies ``estop``, regardless of trailing content) -> ``HELLO``
(zero fields only, resets the sequence, sends the banner) -> the
sequenced path (every other verb, known or not, via
``_dispatch_sequenced()``).

Verb scope (13 verbs total, this repo's own ``sprint.md`` "In Scope"
plus this ticket's RUN/debug addition): ``HELLO PING ID VER STATUS HELP
GET SET TLM WHEELS STOP ESTOP RUN``, plus the unsolicited, robot-to-host
-only ``debug`` emission (``send_debug()``, never reached through
``feed()`` at all -- there is no inbound wire form for it, per Sec 6.2:
a would-be inbound ``debug ...`` line is simply lowercase-led and
dropped by the same mechanism every other lowercase line is).

Adapter seam (snapshot Sec 4), as far as this module calls it --
duck-typed, no ABC (MicroPython has no ``abc`` module):

    identity() -> (name, serial, drivetrain, profile, version)
    now() -> int [ms]
    status() -> (ready, active, conn_left, conn_right, otos, wedge,
                 flags, tlm) -- booleans, `flags` an int, `tlm` a str
    on_estop() -> None
    on_get(name) -> float or None          -- None means "unknown name"
    on_set(name, value, reply_id) -> Result
    on_tlm(mode) -> Result                 -- Result never reaches the wire
    field_count() -> int                   -- for bare GET
    field_name(index) -> str
    on_wheels(left, right, duration, reply_id) -> Result
                                            -- [mm/s] [mm/s] [ms]; no
                                               bounds enforcement here
    on_stop(reply_id) -> Result
    on_run(name, args) -> (Result, value, has_value)
                                            -- args: a list of raw
                                               bytes tokens, untouched
                                               by this handler (Sec
                                               6.3: "the handler holds
                                               no function table and
                                               does no type
                                               conversion"); value is
                                               ignored unless
                                               has_value is truthy

``reply_id`` is now always the real, in-order sequence id (mandatory,
never a magic suppression value the way ``#0`` used to be) -- every
Adapter method that takes one may simply ignore it if it has no use for
it, same as before the retarget.

``emit_telemetry()`` never calls back into the Adapter at all -- unlike
every verb handler above, it is not reached through ``dispatch()``; the
caller (``comms.py``'s scheduled pump) hands it an already-projected
column list directly, mirroring the archetype's own ``Snapshot``-by-
value contract (Sec 5.2: "the adapter's telemetry job is a
projection... hand the handler an array"). The real adapter
(``src/hardware/protocol_adapter.py``) is ticket 005 (WHEELS/STOP/
ESTOP/GET/SET/TLM) plus ticket 012 (``RUN``'s allowlist).

Design decisions this port makes, beyond a line-for-line translation:

- ``Sink.write(text)`` takes a ``str`` (the complete reply line,
  INCLUDING its trailing ``'\\n'``), not raw bytes. The C++ archetype's
  ``Sink::write(const char*, size_t)`` exists only because C++ has no
  other way to hand back a formatted line; a text-based line protocol
  maps onto Python ``str`` naturally, and the wire-byte boundary is a
  transport-layer concern this module never owns (``comms.py``'s job).
- ``feed()`` still takes ``bytes`` (matching every transport's own
  ``read_line() -> bytes`` contract elsewhere in this repo) and still
  reassembles byte-by-byte with a bounded buffer, even though every
  live transport today already hands it one complete, pre-reassembled
  line per call -- this mirrors ``sprint.md``'s own Design Rationale
  ("port feed()'s full byte-buffering robustness... a line-only
  shortcut would fail the golden-vector fixture and would be a silent
  divergence"). A bounded buffer (not an unbounded accumulate-until-'\\n'
  loop) also matters on a memory-constrained MicroPython target: an
  overlong line without a terminator is capped and marked overflowing
  rather than growing without bound.
- No fixed-size field-token array / ``kMaxFieldTokens`` cap. That cap
  exists in the C++ archetype purely to bound a fixed C array's
  storage -- Python lists have no equivalent fixed-capacity hazard, and
  the tokenized field list is never truncated, so its own last element
  IS the line's true raw last token whenever there is one (this is
  exactly what lets this port treat "the id" as simply
  ``fields[-1]``, with no separate raw-line backward scan the way the
  C++ archetype's own ``RUN``-motivated ``findLastFieldToken()`` needs).
- ``Result``'s class attributes are the wire error codes themselves
  (``Result.RANGE == 3``, matching the snapshot's ``ERR_RANGE`` wire
  value directly), not a declaration-order ordinal the way the C++
  archetype's ``enum class Result`` is (there, ``kRange`` is ordinal 3
  but ``kUnimplemented`` is ordinal 5 mapping to wire code 6 --
  ordinal and wire code diverge past ``kFull``, which is exactly why
  the archetype needs its own ``resultCode()`` switch at all). This
  port skips that indirection: a ``Result`` value already IS its own
  wire code. ``result_code()`` still exists, mirroring the archetype's
  contract 1:1 (every rejection path calls it, never a bare ``Result``
  attribute, so a future Result value this table hasn't been taught
  about is caught centrally) -- it is close to an identity function
  here, but that is a property of THIS port's numbering choice, not a
  reason to skip having the function.
- ``send_debug()``/``RUN``'s ``ret`` line both sanitize free text the
  same way: ``'\\n'``/``'\\r'`` bytes removed (not just trimmed from the
  ends), then the WHOLE formatted line truncated -- never overflowed --
  to fit the 240-byte cap, exactly like an overlong INBOUND line is
  discarded rather than truncated into something that might parse as a
  command nobody sent (Sec 6.2). An empty/``None`` ``send_debug()``
  argument, or text that sanitizes down to nothing, emits the bare
  ``debug`` line with no dangling separator space.

History (pre-retarget optional-id design, tickets 001-007): see this
file's own git history for the "ids are optional, ``#0`` suppresses a
reply, ``STOP``'s id is required unlike every other verb" design this
module carried before 2026-08-21 -- none of it is current any more and
none of it is repeated here as if it still were.

LANDMINE: no f-strings, no PEP 604/generic-subscript type hints, no
host-only stdlib -- must import and run unmodified under both CPython
(host tests) and MicroPython (CLAUDE.md).
"""

__all__ = [
    "ProtocolHandler",
    "Sink",
    "Result",
    "result_code",
    "parse_wire_float",
    "MAX_LINE_BYTES",
]

# protocol.md Sec 2: "Max line: 240 bytes including the terminator."
# One place this number is spelled -- feed()'s buffer sizes off it, and
# send_debug()/RUN's ret-line truncation both cap against it too.
MAX_LINE_BYTES = 240


class Result(object):
    """Outcome of an Adapter call (snapshot Sec 4) -- maps onto the
    wire's ack/err distinction. A plain class of int constants, not
    ``enum.Enum`` (MicroPython-clean: avoid assuming ``enum`` is always
    available -- see ``src/core/msgs.py``'s ``VerbEntry`` for the same
    plain-class convention elsewhere in this codebase).

    Snapshot Sec 6.1's full error-code table: every non-``OK``
    attribute's own int value IS its wire error code directly --
    ``Result.RANGE == 3`` doubles as ``ERR_RANGE``'s wire spelling,
    unlike the C++ archetype's declaration-order ``enum class Result``,
    which needs a ``resultCode()`` switch precisely because its
    ordinals and the wire codes diverge (see this module's own
    ``result_code()`` and the docstring note above it). ``OK`` itself
    is never emitted as an error code; it is included here only so a
    Result variable can hold either outcome uniformly.

    ``DUPLICATE_ID`` (code 11) is UNREACHABLE as of the 2026-08-21
    retarget (snapshot Sec 2.2/9.8 item 8): the handler's own
    sequencing now guarantees an id is never dispatched to the Adapter
    more than once, so no code path in this module can ever produce
    it. Kept declared, per the snapshot's own instruction not to prune
    a stakeholder-owned wire-outcome enumerator as part of an unrelated
    change."""

    OK = 0
    UNKNOWN = 1
    BADARG = 2
    RANGE = 3
    FULL = 4
    UNIMPLEMENTED = 6
    NOT_CONFIGURED = 8
    BUSY = 10
    DUPLICATE_ID = 11

    # Every value this class declares, OK included -- result_code()'s
    # own membership check walks this rather than a second, separately
    # maintained list that could drift from the attributes above.
    _ALL_VALUES = (OK, UNKNOWN, BADARG, RANGE, FULL, UNIMPLEMENTED,
                   NOT_CONFIGURED, BUSY, DUPLICATE_ID)


def result_code(result):
    """Snapshot Sec 4/6.1: ``Result`` -> wire error code, the same
    contract the C++ archetype's ``resultCode()`` implements as a
    ``switch`` over a declaration-order ordinal. In this port each
    ``Result`` attribute's own int value already IS its wire code (see
    the class docstring above), so this is close to an identity
    function for any value the class actually declares -- but it is
    kept as its own callable, and every rejection-reply path below
    calls it rather than a bare ``Result`` attribute, for the same
    reason the archetype's own switch ends in a defensive fallthrough
    (its own comment: "kept so a FUTURE enumerator trips -Wswitch
    instead of silently falling through a default case"): a value this
    table has not been taught about maps onto ``ERR_UNKNOWN`` here,
    rather than emitting some other int with no listed meaning."""
    if result in Result._ALL_VALUES:
        return result
    return Result.UNKNOWN


class Sink(object):
    """Where finished reply lines go (snapshot Sec 3's Sink seam).
    Duck-typed, not an ABC (MicroPython has no ``abc`` module): any
    object with a ``write(text)`` method works, and ``ProtocolHandler``
    never checks ``isinstance()`` against this class. It exists only so
    the contract has one documented, importable name.

    ``write(text)``: ``text`` is one fully formatted reply line
    (``str``), INCLUDING its trailing ``'\\n'`` -- exactly one call per
    line, matching ``protocol_handler.h``'s own ``Sink::write()``
    contract."""

    def write(self, text):
        raise NotImplementedError


def _parse_id_digits(digits):
    """The id's own grammar is ``'#' [0-9]+`` -- STRICTER than an
    ordinary signed integer field (Sec 2's "every wire value is ...
    optionally signed"): no sign at all, not even a leading ``'+'``, so
    ``#+5`` must NOT parse as id 5. A dedicated digit-only scan (not
    ``int()``, which accepts a leading ``'+'``/``'-'`` and this
    codebase's own underscore/whitespace leniency concerns -- see
    ``config.py``'s numeric-field notes) -- returns the parsed
    non-negative int (0 included: as of the 2026-08-21 retarget, ``#0``
    is not a special case any more, it is just a small number that
    always compares less than ``expected_next``), or ``None`` if
    ``digits`` is empty or contains any non-digit byte."""
    if len(digits) == 0:
        return None
    value = 0
    for b in digits:
        if b < 48 or b > 57:  # '0'-'9'
            return None
        value = value * 10 + (b - 48)
    return value


def _parse_mandatory_id(token):
    """Snapshot Sec 2.2/8.4: every sequenced verb's trailing token must
    be a well-formed ``'#' [0-9]+`` -- present, ``'#'``-prefixed, and
    all-digit, or the whole line cannot be classified at all (Sec 8.4
    items 1-2). Returns the parsed non-negative int, or ``None``."""
    if token[0:1] != b"#":
        return None
    return _parse_id_digits(token[1:])


# ---- guarded numeric-field parser (protocol.md Sec 2.2/7.2/9.4) ----------
# Shared by every numeric field this module decodes (SET's value,
# WHEELS's three fields) -- one parser, so none of them can diverge.

# The field grammar (Sec 2) is "any bytes except ' ' and '\n'" -- ' '
# can therefore never reach a field token at all (the tokenizer's own
# space-run splitting guarantees it; Sec 9.4's own leading-whitespace
# finding calls this case closed structurally, not by this guard). What
# DOES legally reach a field token, and is exactly the residue Sec 9.4
# flags: '\t' (9), '\v' (11), '\f' (12), '\r' (13) -- all of which
# Python's int()/float() would silently ``.strip()`` from EITHER end
# (not just the leading end C's strtol/strtof skip), reproducing the
# same leniency bug for a wider set of bytes and a wider set of
# positions than the C++ archetype's own single-byte, leading-only
# check. '_' (95) is Python's own addition, with no C++ analogue at
# all: int()/float() accept it as a digit-group separator ("1_000")
# that has no wire spelling whatsoever.
_DISALLOWED_FIELD_BYTES = (9, 11, 12, 13, 95)


def _has_disallowed_field_byte(field):
    for byte in field:
        if byte in _DISALLOWED_FIELD_BYTES:
            return True
    return False


def parse_wire_float(field):
    """Guarded float decode for a wire config value (snapshot Sec 7.2).
    Returns the parsed float, or ``None`` if ``field`` is not a
    well-formed wire numeric value.

    Guards, beyond a bare ``float()`` call:

    - empty field -- rejected (``float("")`` itself already raises,
      but stated explicitly so the empty-field case reads as
      deliberate, not incidental);
    - any byte in ``_DISALLOWED_FIELD_BYTES`` -- Python's own leniency
      findings, Sec 9.4 (whitespace variants position-independent,
      '_' with no wire spelling at all);
    - ``'e'``/``'E'`` anywhere -- Sec 2's "no exponents" applies to
      config values too (Sec 7.2's own posture, matching the C++
      archetype's ``parseFloatField()`` comment: "nothing in this
      project ever needs a robot to accept '1e10' ... as a gain").
      Unlike the archetype, this guard does NOT need to separately bar
      ``'x'``/``'X'`` for the hex-float bypass (Sec 9.4 finding 2):
      that bug was a C++-only divergence -- neither CPython's nor
      MicroPython's ``float()`` accepts hex-float syntax at all, so
      ``float("0x1.8p3")`` already raises ``ValueError`` with no help
      needed from this function;
    - a successfully parsed but non-finite result (``NaN``/``Inf``) --
      Sec 2's "no NaN, no inf", checked the same way the archetype's
      ``std::isnan``/``std::isinf`` do post-parse, since ``float()``
      itself happily parses the literal text ``"nan"``/``"inf"``."""
    if len(field) == 0 or _has_disallowed_field_byte(field):
        return None
    for byte in field:
        if byte == 101 or byte == 69:  # 'e' 'E' -- no exponents (Sec 2)
            return None
    try:
        text = field.decode("ascii")
    except UnicodeError:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value:  # NaN != itself -- no math.isnan() import needed
        return None
    if value == float("inf") or value == float("-inf"):
        return None
    return value


# ---- config-value formatting (protocol.md Sec 7.2) ------------------------

_FORMAT_DIVISOR = 1000000  # 10**6 -- Sec 7.2's fixed six fractional digits
# Ported from formatConfigValue()'s own fixed-point clamp bound
# ("largest float < UINT32_MAX") -- ``+-Inf`` clamps to this
# representation's own max magnitude, purely a consequence of the
# chosen fixed-point arithmetic, not an independent design decision.
_FORMAT_MAX_SCALED = 4294967040.0


def _format_config_value(value):
    """Snapshot Sec 7.2's ``formatFixed()``, ported from
    ``protocol_handler.cpp``'s ``formatConfigValue()``: six fractional
    digits, always present, no exponent -- ``_format_config_value(0.02)``
    -> ``"0.020000"``, ``_format_config_value(-51.5)`` ->
    ``"-51.500000"`` (the spec's own literal examples).

    ``value`` is NOT wire-parsed here -- it is whatever the Adapter's
    own ``on_get()`` handed back, so unlike a value that arrived
    through ``parse_wire_float()`` (which already rejects ``NaN``/
    ``Inf`` on the way in), it is not guaranteed finite. Sec 9.4
    finding 1: the C++ archetype cast a ``NaN`` straight to
    ``uint32_t`` here, undefined behavior caught live by UBSan,
    reachable only through the Adapter seam. Ported as an explicit
    clamp to ``0.0`` -- there is no wire spelling for ``NaN`` to
    preserve -- rather than reproducing the bug class. ``+-Inf`` clamps
    to the fixed-point representation's own max magnitude, the same as
    the archetype's own arithmetic already did for free."""
    if value != value:  # NaN clamp (Sec 9.4 finding 1) -- NaN != itself
        value = 0.0
    negative = value < 0.0
    magnitude = -value if negative else value
    scaled = magnitude * _FORMAT_DIVISOR + 0.5
    if scaled > _FORMAT_MAX_SCALED:
        scaled = _FORMAT_MAX_SCALED
    scaled_int = int(scaled)
    whole_part = scaled_int // _FORMAT_DIVISOR
    frac_part = scaled_int % _FORMAT_DIVISOR
    return "%s%d.%06d" % ("-" if negative else "", whole_part, frac_part)


def _decode_field_name(field):
    """Field content is "any bytes except ' ' and '\\n'" (protocol.md
    Sec 2) -- not restricted to ASCII, even though every real
    field-table name (or ``RUN`` function name) this library or any
    adapter declares always is one. Decoding a wire-supplied name must
    never crash the handler, even on a byte no real name would ever
    contain. Returns the decoded ``str``, or ``None`` on a decode
    failure -- a ``None`` can never equal a real (always-ASCII)
    name, so callers treat it exactly like "name not found"."""
    try:
        return field.decode("ascii")
    except UnicodeError:
        return None


def _sanitize_free_text(text):
    """Snapshot Sec 6.2/6.3: free text destined for ``debug <text>`` or
    ``ret <value> #<id>`` is sanitized by STRIPPING (removing, not just
    trimming the ends) every ``'\\n'``/``'\\r'`` byte -- it must never be
    able to forge a second line onto the wire."""
    return text.replace("\n", "").replace("\r", "")


def _truncate_line_to_cap(line):
    """The whole formatted line (content only, NOT including the
    trailing ``'\\n'`` this function's caller appends) is truncated --
    never overflowed -- to fit inside the 240-byte wire cap, the same
    posture ``feed()`` itself takes on an overlong INBOUND line (Sec
    3.1): a truncated line that still happens to parse as something
    valid must never be handed to the sink."""
    max_content = MAX_LINE_BYTES - 1  # room for the trailing '\n'
    if len(line) > max_content:
        return line[:max_content]
    return line


# ---- TLM mode decode (protocol.md Sec 6) ----------------------------------
# "OFF/POSE/FULL/NOW/AUTO/BUFFER decoded" -- the handler only decodes
# and validates the mode name; anything past "persist it" is the
# calling application's job (Sec 6's own table entry for TLM). An
# unparseable mode string is an ordinary Sec 8.4 item-3 "unparseable
# field" -- ack + err 2 -- not a standalone TLM-specific rule (this
# ticket's own recorded ambiguity resolution #2; the snapshot's "--"
# reply shown for TLM in Sec 6's table describes the SUCCESS path only).
_TLM_MODES = (b"OFF", b"POSE", b"FULL", b"NOW", b"AUTO", b"BUFFER")


class ProtocolHandler(object):
    """The ASCII line-grammar codec plus the reliability layer
    (snapshot Sec 2-8). The only class in this module that ever touches
    a wire byte: ``feed()`` reassembles arbitrary byte blocks into
    ``'\\n'``-terminated lines, tokenizes each line on runs of ``' '``,
    dispatches to the Adapter, and formats the reply -- once, per verb,
    so the Adapter can neither forget a reply nor invent a shape for
    one.

    ``VERB_TABLE``: an ordered tuple of all 13 ``(name_bytes, handler)``
    pairs, in the exact order ``HELP``'s reply lists them (snapshot Sec
    6's own literal table) -- the SAME table ``_handle_help()`` walks
    to generate that text, so it cannot drift from what this class
    actually implements. ``_SEQUENCED_VERB_TABLE`` (everything except
    ``HELLO``/``ESTOP``) is mechanically DERIVED from ``VERB_TABLE`` at
    class-definition time, not a second, independently-maintained list
    -- the same "cannot drift" property extends to which verbs the
    sequenced dispatch path will recognize."""

    def __init__(self, adapter, sink):
        self._adapter = adapter
        self._sink = sink
        self._line_buf = bytearray()
        self._overflowing = False
        self._malformed_count = 0
        # ---- telemetry header-change state (protocol.md Sec 5.2/6.2)
        # -- per-INSTANCE, never shared across handlers (sprint.md's
        # Design Rationale: one ProtocolHandler per transport, each
        # with its own thdr-once-per-subscriber tracking).
        self._header_names = []
        self._header_hex = []
        self._ever_emitted_header = False
        # ---- reliability-layer state (snapshot Sec 8.1), 2026-08-21
        # retarget -- per-instance, the ENTIRE receiver-side state (no
        # ring, no per-id storage, no eviction policy), reset by HELLO.
        self._expected_next = 1
        self._last_done = 0
        self._gap_outstanding = False

    def malformed_count(self):
        """Content/decode failures only (snapshot Sec 8.4 item 3 /
        Sec 9.8 item 2): an unrecognized verb, wrong field count, or an
        unparseable field with an IN-ORDER id; a missing or ill-formed
        id on an otherwise-sequenced verb; a malformed ``HELLO``. Never
        incremented for: a lowercase-led line (Sec 2.1, another robot's
        reply), a blank/all-whitespace line (Sec 2), an out-of-order
        (retransmit or gap) id -- "a normal, expected occurrence on a
        lossy or reordering transport, not a protocol violation" (Sec
        9.8 item 2) -- or ``ESTOP``, which inspects nothing about its
        own line at all any more (Sec 8.3)."""
        return self._malformed_count

    # ---- feed() / line reassembly --------------------------------------

    def feed(self, data):
        """Feed an arbitrary block from the port (``bytes``) -- may
        contain zero, one, or several complete lines, and may end
        mid-line. Partial lines are buffered across calls; complete
        lines are parsed and dispatched immediately, in the order they
        complete. Must survive (protocol.md Sec 2/2.1):

        - several complete lines in one block;
        - a block ending mid-line (the remainder is buffered);
        - a block that is only a line fragment;
        - a lone ``'\\r'`` immediately before ``'\\n'`` (stripped;
          ``'\\r'`` never appears elsewhere);
        - a blank or all-whitespace line (ignored silently -- NOT
          counted malformed);
        - a line longer than the 240-byte maximum: discarded to the
          next ``'\\n'`` and counted malformed -- NEVER truncated into
          a prefix that might still parse as a command the host never
          sent."""
        for byte in data:
            self._append_byte(byte)

    def _append_byte(self, byte):
        if byte == 10:  # '\n' (0x0A) -- line terminator
            self._on_line_complete()
            return
        if self._overflowing:
            return  # discard content until the next '\n'
        if len(self._line_buf) >= MAX_LINE_BYTES - 1:
            # Storing this byte would push the line's content alone to
            # MAX_LINE_BYTES - 1, i.e. content + '\n' would exceed the
            # wire's 240-byte cap. Discard to the next '\n' rather than
            # truncate -- a truncated prefix that still parses as a
            # legal command is one the host never sent (Sec 2.1).
            self._overflowing = True
            self._line_buf = bytearray()  # NOT `del ...[:]` -- see below
            return
        self._line_buf.append(byte)

    def _on_line_complete(self):
        # BENCH DEFECT (sprint 007 ticket 010, found on tovez's real
        # hardware): every `del self._line_buf[...]` below used to be
        # exactly that -- item/slice deletion on a `bytearray`. CPython
        # supports it fine (this module's own offline test suite is
        # 100% CPython, so it never caught this), but this MicroPython
        # build's `bytearray` does NOT: `TypeError: 'bytearray' object
        # doesn't support item deletion`, raised inside the scheduled
        # pump callback on the FIRST real line `feed()` ever completed
        # on hardware (a HELLO datagram). The exception aborted that
        # callback silently -- `wifi_at.pump()` (called right after
        # `comms.pump()` in the same tick, per `core/boot.py`) never
        # ran, so nothing downstream of it (state servicing, the send
        # queue drain) advanced either -- which is why the peer-edge
        # `READY` (sent via a different, unrelated code path in
        # `wifi_at.py`, not through this handler at all) got through
        # but `HELLO`'s own `send_banner()` reply never did: the crash
        # happened before that reply's bytes could even be queued.
        # Fixed by reassigning a fresh `bytearray()` (or slicing a new
        # one) instead of deleting in place -- the same pattern
        # `wifi_at.py`'s own line-buffer handling already uses
        # everywhere (e.g. `_feed_status_byte`), which is presumably
        # why THAT module's real-hardware bring-up never hit this.
        if self._overflowing:
            self._overflowing = False
            self._line_buf = bytearray()
            self._malformed_count += 1
            return

        # A lone '\r' immediately before '\n' is a terminal artifact,
        # stripped; '\r' appears nowhere else on the wire (Sec 2).
        if len(self._line_buf) > 0 and self._line_buf[-1] == 13:  # '\r'
            self._line_buf = self._line_buf[:-1]
        line = bytes(self._line_buf)
        self._line_buf = bytearray()

        # A blank or all-whitespace line is ignored SILENTLY (Sec 2) --
        # a terminal artifact, not an error; it does NOT count
        # malformed. Only ' ' counts here, matching the grammar's own
        # "field ::= any bytes except ' ' and '\n'".
        if not line.strip(b" "):
            return

        # Split on runs of ' ', dropping the empties a run produces --
        # collapses "sp ::= ' '+" into one separator and trims
        # leading/trailing line whitespace. No allocation-bounded
        # storage cap -- the tokenized field list is never truncated,
        # so its own last element IS the line's true raw last token
        # whenever one exists (this module's own docstring).
        tokens = [t for t in line.split(b" ") if t]
        verb = tokens[0]
        fields = tokens[1:]
        self._dispatch(verb, fields)

    # ---- dispatch (snapshot Sec 8.3/8.4) ---------------------------------

    def _dispatch(self, verb, fields):
        # Case is direction (Sec 2.1): commands are UPPERCASE, replies
        # are lowercase, and verb lookup is case-sensitive. A verb
        # starting with a lowercase letter can never be a command this
        # table knows about -- it is another robot's reply, overheard
        # on a shared channel, and is dropped SILENTLY, not counted
        # malformed. This check runs first, unchanged by the retarget.
        if 97 <= verb[0] <= 122:  # 'a' <= verb[0] <= 'z'
            return

        # ESTOP and HELLO are excluded from sequencing by verb IDENTITY,
        # checked before any id-extraction logic runs at all (Sec 8.3).
        if verb == b"ESTOP":
            self._handle_estop()
            return
        if verb == b"HELLO":
            self._handle_hello(fields)
            return

        self._dispatch_sequenced(verb, fields)

    def _dispatch_sequenced(self, verb, fields):
        """Snapshot Sec 8.4: every verb reaching this method (known or
        not -- an unrecognized verb classifies exactly like a known one
        until AFTER an in-order ack fires, Sec 9.8 item 1) is sequenced.

        1. No trailing field at all -- malformed, no reply (nothing to
           sequence-check).
        2. A trailing field present but not a well-formed ``#[0-9]+``
           -- malformed, no reply.
        3. A well-formed id -- classify via the three-way table (Sec
           8.1), using ONLY the id; the verb itself is not even looked
           up until the in-order branch fires."""
        if len(fields) == 0:
            self._malformed_count += 1
            return

        inbound_id = _parse_mandatory_id(fields[-1])
        if inbound_id is None:
            self._malformed_count += 1
            return

        remaining_fields = fields[:-1]

        if inbound_id < self._expected_next:
            # Retransmit -- the host's own ack for this id was lost.
            # Do NOT re-execute; echo the highest ALREADY-accepted id
            # (Sec 8.1's own point: this is what tells the host "I
            # already have everything through here," not "here is a
            # fresh ack for the id you just resent").
            self._reply_ack(self._expected_next - 1)
            return

        if inbound_id > self._expected_next:
            # Gap -- discard, do NOT execute. The stream stalls on
            # purpose until the missing id arrives; every subsequent
            # line (however well-formed) re-triggers the same nack, so
            # a lost nack self-heals for free.
            self._gap_outstanding = True
            self._reply_nack(self._expected_next)
            return

        # In order: the sequence advances and the ack fires
        # UNCONDITIONALLY, before the verb is even looked up (Sec 9.8
        # item 4).
        self._expected_next = inbound_id + 1
        self._gap_outstanding = False
        self._reply_ack(inbound_id)

        handler = self._find_sequenced_handler(verb)
        if handler is None:
            self._malformed_count += 1
            self._reply_err(Result.UNKNOWN, inbound_id)
            return
        handler(self, remaining_fields, inbound_id)

    def _find_sequenced_handler(self, verb):
        for name, handler in self._SEQUENCED_VERB_TABLE:
            if verb == name:
                return handler
        return None

    # ---- reply formatting (snapshot Sec 8.1/8.2/8.6) ---------------------

    def _reply_ack(self, n):
        self._write_line("ack %d %d\n" % (n, self._last_done))

    def _reply_nack(self, n):
        self._write_line("nack %d %d\n" % (n, self._last_done))

    def _reply_err(self, code, reply_id):
        # Field order: code FIRST, id last (Sec 8.6) -- flipped from
        # this module's own pre-2026-08-21 "err #<id> <code>".
        self._write_line("err %d #%d\n" % (code, reply_id))

    def _write_line(self, text):
        self._sink.write(text)

    # ---- unsolicited emissions --------------------------------------------

    def send_banner(self):
        """Unsolicited emission: ``device NEZHA2 robot <name>
        <serial>``. ``HELLO``'s own reply is byte-identical to this --
        ``_handle_hello()`` calls this same method rather than
        duplicating the format string."""
        name, serial, _drivetrain, _profile, _version = self._adapter.identity()
        self._write_line("device NEZHA2 robot %s %s\n" % (name, serial))

    def send_debug(self, text):
        """Snapshot Sec 6.2: unsolicited ``debug <text>``, robot-to-host
        ONLY -- never reached through ``feed()``, no inbound wire form
        exists for it at all. ``text`` (``None`` or a ``str``) is
        sanitized (``'\\n'``/``'\\r'`` stripped) and the WHOLE formatted
        line truncated, never overflowed, to the 240-byte cap.
        ``send_debug(None)``/``send_debug("")``, and any text that
        sanitizes down to nothing, all emit the bare ``debug`` line --
        no dangling separator space."""
        if text is None or text == "":
            self._write_line("debug\n")
            return
        sanitized = _sanitize_free_text(text)
        if sanitized == "":
            self._write_line("debug\n")
            return
        line = _truncate_line_to_cap("debug " + sanitized)
        self._write_line(line + "\n")

    def emit_telemetry(self, columns):
        """Snapshot Sec 5.2/6.2/8.5: ``thdr <col1> <col2> ...`` once --
        the first time this INSTANCE ever emits, or again whenever the
        column set (count, names, or hex-ness, in that order) changes
        from what this instance last remembered -- then
        ``t <v1> <v2> ...`` on every call, header emission included,
        then (2026-08-21 retarget) the current reliability line: ``nack
        <expected_next> <last_done>`` if a gap is outstanding, else
        ``ack <expected_next - 1> <last_done>`` -- piggybacked on this
        existing, application-driven cadence rather than a new timer
        (Sec 8.5: "deliberately, there is no tick() and no clock").

        ``columns`` is a sequence of ``(name, value, hex)`` tuples,
        already fully projected by the caller (this handler holds no
        notion of what a column MEANS). ``name`` is a ``str``; ``value``
        is an ``int``; ``hex`` is truthy for a flags-style column
        formatted as lowercase hex with no ``0x`` prefix, falsy for an
        ordinary signed decimal column."""
        if self._header_changed(columns):
            self._emit_header(columns)
            self._remember_header(columns)
        self._emit_frame(columns)
        self._emit_reliability_line()

    def _emit_reliability_line(self):
        if self._gap_outstanding:
            self._reply_nack(self._expected_next)
        else:
            self._reply_ack(self._expected_next - 1)

    def _header_changed(self, columns):
        if not self._ever_emitted_header:
            return True
        if len(columns) != len(self._header_names):
            return True
        for index in range(len(columns)):
            name, _value, hex_flag = columns[index]
            if self._header_hex[index] != bool(hex_flag):
                return True
            if self._header_names[index] != name:
                return True
        return False

    def _remember_header(self, columns):
        self._header_names = [name for name, _value, _hex in columns]
        self._header_hex = [bool(hex_flag) for _name, _value, hex_flag in columns]
        self._ever_emitted_header = True

    def _emit_header(self, columns):
        parts = ["thdr"]
        for name, _value, _hex in columns:
            parts.append(name)
        self._write_line(" ".join(parts) + "\n")

    def _emit_frame(self, columns):
        parts = ["t"]
        for _name, value, hex_flag in columns:
            if hex_flag:
                # Lowercase hex, no "0x" prefix. Masked to 32 bits the
                # same way the C++ archetype's own
                # `static_cast<uint32_t>(value)` reinterprets a
                # negative int32 as its unsigned bit pattern before
                # formatting -- flags are never negative in practice,
                # but the mask keeps this port byte-identical to the
                # archetype's own arithmetic rather than assuming so.
                parts.append("%x" % (int(value) & 0xFFFFFFFF))
            else:
                parts.append("%d" % int(value))
        self._write_line(" ".join(parts) + "\n")

    # ---- HELLO / ESTOP: the sequencing exemption set (Sec 8.3) -----------

    def _handle_hello(self, fields):
        """Unsequenced, zero fields -- a trailing id is wrong arity,
        same as any other extra field (Sec 8.3). A malformed HELLO
        increments ``malformed_count()`` and produces no reply (Sec
        9.8 item 7: there is no ack to anchor an err against for a verb
        outside the sequence entirely)."""
        if len(fields) != 0:
            self._malformed_count += 1
            return
        self._expected_next = 1
        self._last_done = 0
        self._gap_outstanding = False
        self.send_banner()

    def _handle_estop(self):
        """Maximally forgiving (Sec 8.3): ANY line whose verb token is
        exactly ``ESTOP`` -- well-formed or with arbitrary trailing
        junk -- executes the stop and then replies. No id, never
        sequenced, never nacked, and (unlike every other verb in this
        table) no arity or content is ever inspected at all, so there
        is no wrong-arity case left to count: ``ESTOP`` never
        increments ``malformed_count()``. The kernel call executes
        BEFORE the reply is written, so the reply can never be mistaken
        for having queued ahead of the actual stop."""
        self._adapter.on_estop()
        self._write_line("estop\n")

    # ---- session verbs (Sec 6/8.4) -- ack already fired; a stray field
    # past the (already-stripped) id is the only wrong-arity case left.

    def _handle_ping(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        self._write_line("pong %d\n" % self._adapter.now())

    def _handle_id(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        _name, _serial, drivetrain, profile, version = self._adapter.identity()
        self._write_line("id %s %s %s\n" % (drivetrain, profile, version))

    def _handle_ver(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        _name, _serial, _drivetrain, _profile, version = self._adapter.identity()
        self._write_line("ver %s\n" % version)

    def _handle_status(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        (ready, active, conn_left, conn_right, otos, wedge, flags,
         tlm) = self._adapter.status()
        # "next=<expected_next>" appended 2026-08-21 (Sec 8.7) -- a
        # reconnecting host can resync its own tracking without a full
        # HELLO reset (which would also clear last_done).
        self._write_line(
            "status ready=%d active=%d connL=%d connR=%d otos=%d "
            "wedge=%d flags=%x tlm=%s next=%d\n"
            % (1 if ready else 0, 1 if active else 0,
               1 if conn_left else 0, 1 if conn_right else 0,
               1 if otos else 0, 1 if wedge else 0, flags, tlm,
               self._expected_next))

    def _handle_help(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        # Generated by walking VERB_TABLE at runtime, so it cannot
        # drift from what this class actually implements -- 13 verbs,
        # RUN last, as of the 2026-08-21 retarget.
        names = [name.decode("ascii") for name, _handler in self.VERB_TABLE]
        self._write_line("help " + " ".join(names) + "\n")

    # ---- configuration: pure delegation, no storage here (protocol.md
    # Sec 7: "the handler holds no field table, no bounds, no storage.
    # Which names are valid is entirely the adapter's business") -------

    def _handle_get(self, fields, reply_id):
        if len(fields) > 1:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        if len(fields) == 0:
            # Bare "GET #id": one "get name value" line per field the
            # Adapter declares -- entirely the Adapter's own
            # enumeration, this handler holds no list of its own.
            total = self._adapter.field_count()
            for index in range(total):
                name = self._adapter.field_name(index)
                value = self._adapter.on_get(name)
                if value is None:
                    continue
                self._write_line(
                    "get %s %s\n" % (name, _format_config_value(value)))
            return

        name = _decode_field_name(fields[0])
        # Unknown name: still gets the ack (already sent above), but no
        # `get` line and no `err` either -- silent, and NOT counted
        # malformed (snapshot Sec 6's own table note). A name that
        # fails to decode as ASCII can never match a real (always-
        # ASCII) field-table name, so it takes the exact same silent
        # path.
        if name is None:
            return
        value = self._adapter.on_get(name)
        if value is None:
            return
        self._write_line(
            "get %s %s\n" % (name, _format_config_value(value)))

    def _handle_set(self, fields, reply_id):
        if len(fields) != 2:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        value = parse_wire_float(fields[1])
        if value is None:
            # A handler-level decode failure on the value field --
            # never reaches on_set().
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        name = _decode_field_name(fields[0])
        # A name that fails to decode as ASCII can never match a real
        # field-table name -- treat it exactly like the Adapter itself
        # answering "no such name" (ERR_UNKNOWN), rather than calling
        # on_set() with something that isn't a usable name at all.
        result = (self._adapter.on_set(name, value, reply_id)
                   if name is not None else Result.UNKNOWN)
        if result != Result.OK:
            # "ok" is gone -- the ack already sent IS the acceptance
            # (Sec 8.2); a rejection is a SECOND line layered on top.
            self._reply_err(result_code(result), reply_id)

    # ---- telemetry mode (protocol.md Sec 6) -------------------------------

    def _handle_tlm(self, fields, reply_id):
        if len(fields) != 1:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        mode_bytes = fields[0]
        if mode_bytes not in _TLM_MODES:
            # Resolved ambiguity: an unparseable mode string is an
            # ordinary content-decode failure (Sec 8.4 item 3), not a
            # TLM-specific silence -- the snapshot's own Sec 6 table
            # "--" reply describes the SUCCESS path only.
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        # The Adapter's own Result (e.g. for logging) never surfaces on
        # the wire -- mirrors protocol_handler.cpp's own
        # `(void)adapter_.onTlm(mode);`.
        self._adapter.on_tlm(mode_bytes.decode("ascii"))

    # ---- motion: WHEELS/STOP (protocol.md Sec 5/5.1/9.1) -------------------
    # No queue, no planner -- WHEELS reaches the Adapter directly. The
    # handler holds no bounds table (Sec 9.1: "the adapter enforces
    # [the 5000 ms ceiling]"), so left/right/duration cross this seam
    # as plain parsed floats, untouched.

    def _handle_wheels(self, fields, reply_id):
        if len(fields) != 3:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        left = parse_wire_float(fields[0])
        right = parse_wire_float(fields[1])
        duration = parse_wire_float(fields[2])
        if left is None or right is None or duration is None:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        result = self._adapter.on_wheels(left, right, duration, reply_id)
        if result != Result.OK:
            self._reply_err(result_code(result), reply_id)

    def _handle_stop(self, fields, reply_id):
        if len(fields) != 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return
        result = self._adapter.on_stop(reply_id)
        if result != Result.OK:
            self._reply_err(result_code(result), reply_id)

    # ---- RUN: invocation by name (protocol.md Sec 6.3) ---------------------
    # Parses only -- function name + the rest as raw argument tokens,
    # handed straight to the Adapter. No function table, no name
    # resolution, no type conversion here (mirrors GET/SET's own "the
    # handler holds no tables" posture exactly). A bare "RUN" with no
    # fields at all (not even the id) never reaches this method -- it
    # is caught generically by _dispatch_sequenced()'s own "no trailing
    # field at all" rule. "RUN #<id>" (the id consumed the only field,
    # no function name) DOES reach here with an empty `fields` list --
    # that is this method's own "wrong arity" case, ack + err 2.

    def _handle_run(self, fields, reply_id):
        if len(fields) == 0:
            self._malformed_count += 1
            self._reply_err(Result.BADARG, reply_id)
            return

        name = _decode_field_name(fields[0])
        args = fields[1:]
        if name is None:
            result, value, has_value = Result.UNKNOWN, None, False
        else:
            result, value, has_value = self._adapter.on_run(name, args)

        if result != Result.OK:
            self._reply_err(result_code(result), reply_id)
            return

        if has_value:
            # Sanitized exactly like send_debug()'s own text -- '\n'/
            # '\r' stripped, whole line truncated to the 240-byte cap.
            text = "" if value is None else value
            line = _truncate_line_to_cap(
                "ret %s #%d" % (_sanitize_free_text(text), reply_id))
            self._write_line(line + "\n")
        # else: void return -- nothing beyond the ack already sent.

    VERB_TABLE = (
        (b"HELLO", _handle_hello),
        (b"PING", _handle_ping),
        (b"ID", _handle_id),
        (b"VER", _handle_ver),
        (b"STATUS", _handle_status),
        (b"HELP", _handle_help),
        (b"GET", _handle_get),
        (b"SET", _handle_set),
        (b"TLM", _handle_tlm),
        (b"WHEELS", _handle_wheels),
        (b"STOP", _handle_stop),
        (b"ESTOP", _handle_estop),
        (b"RUN", _handle_run),
    )

    # Mechanically derived from VERB_TABLE (everything except the two
    # sequencing-exempt verbs) -- used by _dispatch_sequenced()'s own
    # verb lookup, so it cannot drift from VERB_TABLE/HELP's text
    # either (this class's own docstring).
    _SEQUENCED_VERB_TABLE = tuple(
        (name, handler) for name, handler in VERB_TABLE
        if name != b"HELLO" and name != b"ESTOP")
