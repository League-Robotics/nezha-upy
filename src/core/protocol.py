"""protocol -- v6 ASCII line-grammar handler (protocol.md Sec 2-6).

Ported from radio-robot-lib's ``src/protocol/protocol_handler.{h,cpp}``
(the C++ archetype) -- read that file's own header first if extending
this module; it documents every grammar ambiguity this port inherits
already resolved (malformed-line ``#id`` recovery firing even for an
unknown verb, ``ESTOP`` winning over that same recovery rule, the id's
own stricter digit-only grammar). This file re-derives none of those
calls; see ``docs/design/protocol.md`` (radio-robot-lib) Sec 9 for the
full resolution history and ``clasi/sprints/007-.../sprint.md``'s
Architecture section for this repo's own port-level decisions.

Grammar (protocol.md Sec 2), in one line::

    line   ::= sp? verb ( sp field )* sp? '\\n'
    sp     ::= ' '+
    verb   ::= [A-Za-z][A-Za-z0-9_]*
    field  ::= any bytes except ' ' and '\\n'
    id     ::= '#' [0-9]+        (a field in trailing position, Sec 2.3)

A run of spaces is ONE separator; leading/trailing line whitespace is
ignored; a blank/all-whitespace line is ignored SILENTLY (not
malformed). Case is direction: commands are UPPERCASE, replies are
lowercase, and verb lookup is case-sensitive -- a lowercase-led line is
another robot's reply overheard on a shared channel and is dropped
silently (Sec 2.1). Malformed-line recovery (Sec 2.3): unknown verb /
wrong arity / unparseable field -> count malformed; if the line's raw
last token is a well-formed NONZERO ``#id``, reply ``err #<id>
<code>``, else no reply. ``ESTOP`` is the one exception and wins even
when malformed: never any reply, ever.

Sprint scope (this repo's ``sprint.md``, "In Scope"): ``HELLO PING ID
VER STATUS HELP GET SET TLM WHEELS STOP ESTOP`` -- 12 verbs. The C++
archetype also implements ``RUN`` (invocation by name) and the
robot-to-host-only ``debug`` unsolicited emission; NEITHER is ported
here at all, not even deferred to a later ticket -- this sprint's own
verb-scope list omits both, so ``tests/fixtures/protocol_golden_vectors.txt``
(copied verbatim from the archetype's own fixture, which DOES cover
RUN/debug) has vectors this port will never make green; the harness
(``tests/unit/test_protocol_golden_vectors.py``) skips them by verb
instead of deleting them. One concrete consequence: the archetype's own
``HELP`` vector lists ``RUN`` as a 13th verb; this port's ``HELP`` text
(Sec 4, "generated from the same dispatch table dispatch() uses") is
only ever 12 verbs, so that one fixture vector is skipped too, even
though every OTHER session-verb vector runs for real.

Ticket 001 scope (this file, as it lands here): ``feed()``/tokenizer/
dispatch skeleton; the six session verbs (HELLO/PING/ID/VER/STATUS/
HELP) fully implemented; ``ESTOP`` fully implemented (SUC-002: never
any reply, even malformed); the generic malformed-line ``#id``-recovery
rule. ``GET``/``SET``/``TLM``/``WHEELS``/``STOP`` are registered
dispatch NAMES ONLY -- present in ``VERB_TABLE`` so an inbound line for
one of them is never treated as an unknown verb, but each one's own
handler is a deliberate no-op (no arity check, no adapter call, no
reply) until ticket 002 (GET/SET/TLM) and ticket 003 (WHEELS/STOP) give
it a real body. ``HELP``'s text already lists all of them, since it
walks this same table.

Ticket 002 scope (this file, as it lands here): ``GET``/``SET``/``TLM``
get real bodies -- pure delegation to the Adapter, the handler holding
no field table and no bounds of its own (protocol.md Sec 7); the full
``Result`` -> wire-error-code table (Sec 6.1, all 8 rejection codes,
plus ``OK``); the guarded numeric-field parser
(``_parse_wire_float()``) that pins Sec 9.4's hex-float/leading-
whitespace findings and adds the whitespace/underscore guards Python's
own ``float()`` needs that C++'s ``strtof()`` did not; and
``formatConfigValue()``'s NaN-clamp fix (Sec 9.4 finding 1), ported as
``_format_config_value()``. ``WHEELS``/``STOP`` remain registered-
name-only stubs -- ticket 003's job.

Adapter seam (protocol.md Sec 4), as far as this ticket calls it --
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

Ticket 003 grows this contract further (``on_wheels``/``on_stop``,
protocol.md Sec 4) as WHEELS/STOP get real bodies; the real adapter
(``src/hardware/protocol_adapter.py``) is ticket 005.

Design decisions this port makes, beyond a line-for-line translation:

- ``Sink.write(text)`` takes a ``str`` (the complete reply line,
  INCLUDING its trailing ``'\\n'``), not raw bytes. The C++ archetype's
  ``Sink::write(const char*, size_t)`` exists only because C++ has no
  other way to hand back a formatted line; a text-based line protocol
  maps onto Python ``str`` naturally, and the wire-byte boundary is a
  transport-layer concern this module never owns (comms.py's job,
  ticket 006).
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
  exists in the C++ archetype purely to bound a fixed C array's storage
  (RUN's own open arity, protocol_handler.h's ambiguity note #4) --
  Python lists have no equivalent fixed-capacity hazard, and RUN is not
  ported here at all, so the cap (and the separate raw-line
  "``findLastFieldToken()``" backward scan it forced the archetype to
  do BEFORE tokenizing) has no reason to exist in this port: the
  tokenized field list is never truncated, so its own last element IS
  the line's true raw last token whenever there is one.
- ``Result``'s class attributes are the wire error codes themselves
  (``Result.RANGE == 3``, matching protocol.md Sec 6.1's ``ERR_RANGE``
  wire value directly), not a declaration-order ordinal the way the
  C++ archetype's ``enum class Result`` is (there, ``kRange`` is
  ordinal 3 but ``kUnimplemented`` is ordinal 5 mapping to wire code 6
  -- ordinal and wire code diverge past ``kFull``, which is exactly
  why the archetype needs its own ``resultCode()`` switch at all).
  This port skips that indirection: a ``Result`` value already IS its
  own wire code. ``result_code()`` still exists, mirroring the
  archetype's contract 1:1 (every rejection path calls it, never a
  bare ``Result`` attribute, so a future Result value this table
  hasn't been taught about is caught centrally) -- it is close to an
  identity function here, but that is a property of THIS port's
  numbering choice, not a reason to skip having the function.

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
    "resolve_trailing_optional_id",
    "ID_OMITTED",
    "ID_ZERO",
    "ID_NONZERO",
    "ID_MALFORMED",
    "MAX_LINE_BYTES",
]

# protocol.md Sec 2: "Max line: 240 bytes including the terminator."
# One place this number is spelled -- feed()'s buffer sizes off it.
MAX_LINE_BYTES = 240


class Result(object):
    """Outcome of an Adapter call (protocol.md Sec 4) -- maps onto the
    wire's ok/err distinction. A plain class of int constants, not
    ``enum.Enum`` (MicroPython-clean: avoid assuming ``enum`` is always
    available -- see ``src/core/msgs.py``'s ``VerbEntry`` for the same
    plain-class convention elsewhere in this codebase).

    protocol.md Sec 6.1's full error-code table (ticket 002 scope):
    every non-``OK`` attribute's own int value IS its wire error code
    directly -- ``Result.RANGE == 3`` doubles as ``ERR_RANGE``'s wire
    spelling, unlike the C++ archetype's declaration-order ``enum
    class Result``, which needs a ``resultCode()`` switch precisely
    because its ordinals and the wire codes diverge (see this module's
    own ``result_code()`` and the docstring note above it). ``OK``
    itself is never emitted as an error code (Sec 4's own comment on
    the archetype's ``kOk``); it is included here only so a Result
    variable can hold either outcome uniformly."""

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
    """protocol.md Sec 4/6.1: ``Result`` -> wire error code, the same
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
    """Where finished reply lines go (protocol.md Sec 3's Sink seam).
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
    """protocol.md Sec 2.2: the id's own grammar is ``'#' [0-9]+`` --
    STRICTER than an ordinary signed integer field (Sec 2's "every wire
    value is ... optionally signed"): no sign at all, not even a
    leading ``'+'``, so ``#+5`` must NOT parse as id 5. A dedicated
    digit-only scan (not ``int()``, which accepts a leading ``'+'``/
    ``'-'`` and this codebase's own underscore/whitespace leniency
    concerns -- see ``config.py``'s numeric-field notes) -- returns the
    parsed non-negative int, or ``None`` if ``digits`` is empty or
    contains any non-digit byte."""
    if len(digits) == 0:
        return None
    value = 0
    for b in digits:
        if b < 48 or b > 57:  # '0'-'9'
            return None
        value = value * 10 + (b - 48)
    return value


def _recover_trailing_id(token):
    """protocol.md Sec 2.3's generic malformed-line recovery: "if the
    line's last token is a well-formed nonzero ``#id``, reply ``err
    #<id> <code>``." ``token`` (bytes or ``None``) is the line's raw
    last token -- ``None`` when the line was just the verb, nothing
    after it (matching "otherwise no reply"). Returns the recovered int
    id, or ``None`` if there is nothing to recover (no token, not
    ``#``-shaped, not well-formed digits, or exactly zero -- id 0 never
    gets an err reply, Sec 2.2)."""
    if token is None or token[0:1] != b"#":
        return None
    parsed = _parse_id_digits(token[1:])
    if parsed is None or parsed == 0:
        return None
    return parsed


# ---- optional trailing-id resolution (SET, and ticket 003's WHEELS) -------
# protocol.md Sec 8.2's now-unambiguous rule for a verb whose id is
# OPTIONAL: omitted, explicit "#0" ("no ack wanted"), an explicit
# nonzero "#<n>", or a trailing token that is present but is NOT a
# well-formed id at all -- which, since neither verb has any OTHER use
# for that positional slot, means the WHOLE LINE is malformed, not
# merely "id-less" (ported from protocol_handler.cpp's own
# resolveTrailingOptionalId()/IdOutcome). Plain int constants, not
# ``enum.Enum`` -- same MicroPython-clean convention as ``Result``.
ID_OMITTED = 0
ID_ZERO = 1
ID_NONZERO = 2
ID_MALFORMED = 3


def resolve_trailing_optional_id(token):
    """``token`` is the raw trailing field that IS the id slot for a
    verb whose id is optional, given the caller has already decided
    (by field count) that a trailing token is present at all -- an
    OMITTED id is ``ID_OMITTED``, decided by the caller without ever
    calling this function (mirrors the C++ archetype: it is only
    called when ``fieldCount`` already proves a trailing token
    exists). Returns ``(outcome, id)`` -- ``id`` is ``0`` unless
    ``outcome`` is ``ID_NONZERO``."""
    if token[0:1] != b"#":
        return ID_MALFORMED, 0
    parsed = _parse_id_digits(token[1:])
    if parsed is None:
        return ID_MALFORMED, 0
    if parsed == 0:
        return ID_ZERO, 0
    return ID_NONZERO, parsed


# ---- guarded numeric-field parser (protocol.md Sec 2.2/7.2/9.4) ----------
# Shared by SET's value field now, and meant to be reused as-is by any
# future numeric field (ticket 003's WHEELS) rather than a second
# parser that might diverge (this ticket's own Implementation Plan).

# The field grammar (Sec 2) is "any bytes except ' ' and '\n'" -- ' '
# can therefore never reach a field token at all (the tokenizer's own
# space-run splitting guarantees it; protocol.md Sec 9.4's own
# leading-whitespace finding calls this case closed structurally, not
# by this guard). What DOES legally reach a field token, and is
# exactly the residue Sec 9.4 flags: '\t' (9), '\v' (11), '\f' (12),
# '\r' (13) -- all of which Python's int()/float() would silently
# ``.strip()`` from EITHER end (not just the leading end C's
# strtol/strtof skip), reproducing the same leniency bug for a wider
# set of bytes and a wider set of positions than the C++ archetype's
# own single-byte, leading-only check. '_' (95) is Python's own
# addition, with no C++ analogue at all: int()/float() accept it as a
# digit-group separator ("1_000") that has no wire spelling whatsoever.
_DISALLOWED_FIELD_BYTES = (9, 11, 12, 13, 95)


def _has_disallowed_field_byte(field):
    for byte in field:
        if byte in _DISALLOWED_FIELD_BYTES:
            return True
    return False


def parse_wire_float(field):
    """Guarded float decode for a wire config value (protocol.md Sec
    7.2). Returns the parsed float, or ``None`` if ``field`` is not a
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
      needed from this function (pinned by this ticket's own explicit
      test, not just assumed);
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
    """protocol.md Sec 7.2's ``formatFixed()``, ported from
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
    reachable only through the Adapter seam (an adapter's own stored
    value being ``NaN``, read back by ``GET`` -- never through the
    wire). Ported as an explicit clamp to ``0.0`` -- there is no wire
    spelling for ``NaN`` to preserve -- rather than reproducing the bug
    class. ``+-Inf`` clamps to the fixed-point representation's own
    max magnitude, the same as the archetype's own arithmetic already
    did for free."""
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
    field-table name this library or any adapter declares always is
    one. Decoding a wire-supplied name must never crash the handler,
    even on a byte no real name would ever contain (the same
    never-crash-on-untrusted-input posture ``feed()`` itself takes).
    Returns the decoded ``str``, or ``None`` on a decode failure -- a
    ``None`` can never equal a real (always-ASCII) field-table name,
    so callers treat it exactly like "name not found"."""
    try:
        return field.decode("ascii")
    except UnicodeError:
        return None


# ---- TLM mode decode (protocol.md Sec 6) ----------------------------------
# "OFF/POSE/FULL/NOW/AUTO/BUFFER decoded" -- the handler only decodes
# and validates the mode name; anything past "persist it" is the
# calling application's job (Sec 6's own table entry for TLM).
_TLM_MODES = (b"OFF", b"POSE", b"FULL", b"NOW", b"AUTO", b"BUFFER")


class ProtocolHandler(object):
    """The ASCII line-grammar codec (protocol.md Sec 2-6). The only
    class in this module that ever touches a wire byte: ``feed()``
    reassembles arbitrary byte blocks into ``'\\n'``-terminated lines,
    tokenizes each line on runs of ``' '``, dispatches to the Adapter,
    and formats the reply -- once, per verb, so the Adapter can neither
    forget a reply nor invent a shape for one.

    ``VERB_TABLE``: an ordered tuple of ``(name_bytes, handler)`` pairs
    -- the SAME table ``dispatch()`` and ``_handle_help()`` both walk,
    so ``HELP``'s reply text cannot drift from what ``dispatch()``
    actually recognizes (protocol.md Sec 4)."""

    def __init__(self, adapter, sink):
        self._adapter = adapter
        self._sink = sink
        self._line_buf = bytearray()
        self._overflowing = False
        self._malformed_count = 0

    def malformed_count(self):
        """Lines dropped as unknown verb, wrong arity, or an
        unparseable field (protocol.md Sec 2's malformed counter). A
        lowercase-led inbound verb (another robot's reply, Sec 2.1) is
        dropped silently and does NOT increment this; neither does a
        blank/all-whitespace line (Sec 2)."""
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
            del self._line_buf[:]
            return
        self._line_buf.append(byte)

    def _on_line_complete(self):
        if self._overflowing:
            self._overflowing = False
            del self._line_buf[:]
            self._malformed_count += 1
            return

        # A lone '\r' immediately before '\n' is a terminal artifact,
        # stripped; '\r' appears nowhere else on the wire (Sec 2).
        if len(self._line_buf) > 0 and self._line_buf[-1] == 13:  # '\r'
            del self._line_buf[-1:]
        line = bytes(self._line_buf)
        del self._line_buf[:]

        # A blank or all-whitespace line is ignored SILENTLY (Sec 2) --
        # a terminal artifact, not an error; it does NOT count
        # malformed. Only ' ' counts here, matching the grammar's own
        # "field ::= any bytes except ' ' and '\n'" -- a line of only
        # tabs is NOT blank under this rule (it tokenizes to one odd
        # "verb" token instead, and fails as an unknown verb).
        if not line.strip(b" "):
            return

        # Split on runs of ' ', dropping the empties a run produces --
        # collapses "sp ::= ' '+" into one separator and trims
        # leading/trailing line whitespace, with no allocation-bounded
        # storage cap (see this module's own docstring: unlike the C++
        # archetype, nothing here truncates the field list, so its own
        # last element IS the line's true raw last token whenever one
        # exists).
        tokens = [t for t in line.split(b" ") if t]
        verb = tokens[0]
        fields = tokens[1:]
        last_field_token = tokens[-1] if len(tokens) >= 2 else None
        self._dispatch(verb, fields, last_field_token)

    # ---- dispatch -------------------------------------------------------

    def _dispatch(self, verb, fields, last_field_token):
        # Case is direction (Sec 2.1): commands are UPPERCASE, replies
        # are lowercase, and verb lookup is case-sensitive. A verb
        # starting with a lowercase letter can never be a command this
        # table knows about -- it is another robot's reply, overheard
        # on a shared channel, and is dropped SILENTLY, not counted
        # malformed (the structural fix for the v5 DBG:-flood incident:
        # a reply can never parse as a command under this grammar).
        if 97 <= verb[0] <= 122:  # 'a' <= verb[0] <= 'z'
            return

        for name, handler in self.VERB_TABLE:
            if verb == name:
                handler(self, fields, last_field_token)
                return

        # Unknown verb: no arity is knowable, but the line's own last
        # token can still be a well-formed nonzero #id worth acking
        # against (Sec 2.3's own "including unknown verbs" framing).
        self._reject_malformed(last_field_token, Result.UNKNOWN)

    def _reject_malformed(self, last_field_token, code):
        """Malformed-line recovery (Sec 2/2.3): counts the line
        malformed, then replies ``err #<id> <code>`` IF the line's raw
        last token is a well-formed nonzero ``#id`` -- otherwise no
        reply. Used for unknown verbs and every handler's own
        wrong-arity rejection EXCEPT ``ESTOP``, which never calls
        this."""
        self._malformed_count += 1
        recovered_id = _recover_trailing_id(last_field_token)
        if recovered_id is not None:
            self._reply_err(recovered_id, code)

    # ---- reply formatting ------------------------------------------------

    def _reply_ok(self, reply_id):
        self._write_line("ok #%d\n" % reply_id)

    def _reply_ok_bare(self):
        self._write_line("ok\n")

    def _reply_err(self, reply_id, code):
        self._write_line("err #%d %d\n" % (reply_id, code))

    def _reply_err_bare(self, code):
        self._write_line("err %d\n" % code)

    def _write_line(self, text):
        self._sink.write(text)

    # ---- unsolicited emissions --------------------------------------------

    def send_banner(self):
        """Unsolicited emission (protocol.md Sec 4): ``device NEZHA2
        robot <name> <serial>``. ``HELLO``'s own reply (Sec 3.1) is
        byte-identical to this -- ``_handle_hello()`` calls this same
        method rather than duplicating the format string."""
        name, serial, _drivetrain, _profile, _version = self._adapter.identity()
        self._write_line("device NEZHA2 robot %s %s\n" % (name, serial))

    # ---- session verbs ----------------------------------------------------
    # HELLO/PING/ID/VER/STATUS/HELP all take zero fields -- any
    # trailing token at all, id-shaped or not, is wrong arity.

    def _handle_hello(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        self.send_banner()

    def _handle_ping(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        self._write_line("pong %d\n" % self._adapter.now())

    def _handle_id(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        _name, _serial, drivetrain, profile, version = self._adapter.identity()
        self._write_line("id %s %s %s\n" % (drivetrain, profile, version))

    def _handle_ver(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        _name, _serial, _drivetrain, _profile, version = self._adapter.identity()
        self._write_line("ver %s\n" % version)

    def _handle_status(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        (ready, active, conn_left, conn_right, otos, wedge, flags,
         tlm) = self._adapter.status()
        self._write_line(
            "status ready=%d active=%d connL=%d connR=%d otos=%d "
            "wedge=%d flags=%x tlm=%s\n"
            % (1 if ready else 0, 1 if active else 0,
               1 if conn_left else 0, 1 if conn_right else 0,
               1 if otos else 0, 1 if wedge else 0, flags, tlm))

    def _handle_help(self, fields, last_field_token):
        if len(fields) != 0:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        # "Generated by walking the verb table at runtime, so it cannot
        # drift from the dispatcher" (protocol.md Sec 4) -- VERB_TABLE
        # is the SAME table _dispatch() looks verbs up in.
        names = [name.decode("ascii") for name, _handler in self.VERB_TABLE]
        self._write_line("help " + " ".join(names) + "\n")

    def _handle_estop(self, fields, last_field_token):
        if len(fields) != 0:
            # ESTOP is NEVER acked, not even on wrong arity (protocol.md
            # Sec 2.3/SUC-002) -- this verb's own rule wins over the
            # generic malformed-line #id-recovery rule every other
            # handler uses. Deliberately does NOT call
            # _reject_malformed() (which would call _reply_err()).
            self._malformed_count += 1
            return
        self._adapter.on_estop()
        # No reply, ever.

    # ---- configuration: pure delegation, no storage here (protocol.md
    # Sec 7: "the handler holds no field table, no bounds, no storage.
    # Which names are valid is entirely the adapter's business") -------

    def _handle_get(self, fields, last_field_token):
        if len(fields) > 1:
            self._reject_malformed(last_field_token, Result.BADARG)
            return

        if len(fields) == 0:
            # Bare GET: one "get name value" line per field the
            # Adapter declares (Sec 6: "one get line per field (bare
            # GET)") -- entirely the Adapter's own enumeration, this
            # handler holds no list of its own.
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
        # Unknown name: GET never carries an id (Sec 3.1: "GET |
        # [name]", no id slot at all), so there is no wire channel to
        # reject it on -- silent, and NOT counted malformed (Sec 7.1,
        # stated explicitly). A name that fails to decode as ASCII can
        # never match a real (always-ASCII) field-table name either,
        # so it takes the exact same silent path.
        if name is None:
            return
        value = self._adapter.on_get(name)
        if value is None:
            return
        self._write_line(
            "get %s %s\n" % (name, _format_config_value(value)))

    def _handle_set(self, fields, last_field_token):
        if len(fields) != 2 and len(fields) != 3:
            self._reject_malformed(last_field_token, Result.BADARG)
            return

        id_provided = len(fields) == 3
        if id_provided:
            id_outcome, reply_id = resolve_trailing_optional_id(fields[2])
            if id_outcome == ID_MALFORMED:
                # The 3rd token is present but not a well-formed
                # "#id" -- SET has no other use for a 3rd positional
                # field, so this is a malformed line, not "a SET with
                # an id-less extra field".
                self._reject_malformed(last_field_token, Result.BADARG)
                return
        else:
            id_outcome, reply_id = ID_OMITTED, 0

        value = parse_wire_float(fields[1])
        if value is None:
            # The VALUE field itself is malformed -- a handler-level
            # decode failure (Sec 7.2: SET's value is decoded by the
            # handler), never reaching on_set(). Still applies the
            # same id-outcome-driven reply shape the success path
            # uses, so a typo'd value on an otherwise well-formed SET
            # still gets the ack format its own id calls for.
            self._malformed_count += 1
            if id_outcome == ID_NONZERO:
                self._reply_err(reply_id, Result.BADARG)
            elif id_outcome == ID_OMITTED:
                self._reply_err_bare(Result.BADARG)
            # ID_ZERO: "#0" -- no ack wanted, stays silent.
            return

        name = _decode_field_name(fields[0])
        # A name that fails to decode as ASCII can never match a real
        # field-table name -- treat it exactly like the Adapter itself
        # answering "no such name" (ERR_UNKNOWN), rather than calling
        # on_set() with something that isn't a usable name at all.
        result = (self._adapter.on_set(name, value, reply_id)
                   if name is not None else Result.UNKNOWN)

        if id_outcome == ID_ZERO:
            return  # executes silently, no ack at all (Sec 8.2)
        if id_outcome == ID_OMITTED:
            if result == Result.OK:
                self._reply_ok_bare()
            else:
                self._reply_err_bare(result_code(result))
            return
        # ID_NONZERO
        if result == Result.OK:
            self._reply_ok(reply_id)
        else:
            self._reply_err(reply_id, result_code(result))

    # ---- telemetry mode (protocol.md Sec 6) -------------------------------

    def _handle_tlm(self, fields, last_field_token):
        if len(fields) != 1:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        mode_bytes = fields[0]
        if mode_bytes not in _TLM_MODES:
            self._reject_malformed(last_field_token, Result.BADARG)
            return
        # TLM carries no id (Sec 3.1) -- no wire channel to ack or
        # reject on. The Adapter's own Result (e.g. for logging) never
        # surfaces on the wire (mirrors protocol_handler.cpp's
        # `(void)adapter_.onTlm(mode);`).
        self._adapter.on_tlm(mode_bytes.decode("ascii"))

    def _handle_wheels_stop_stub(self, fields, last_field_token):
        """WHEELS/STOP: registered dispatch NAMES only, still. An
        inbound line for one of them is recognized (so it never falls
        into the generic "unknown verb" malformed path) but is
        otherwise a deliberate no-op -- no arity check, no adapter
        call, no reply, no malformed-count change -- until ticket 003
        gives it a real body. See this module's own docstring."""
        pass

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
        (b"WHEELS", _handle_wheels_stop_stub),
        (b"STOP", _handle_wheels_stop_stub),
        (b"ESTOP", _handle_estop),
    )
