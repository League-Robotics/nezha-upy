"""boot -- frozen boot module: assembles the firmware layer at power-on
(UC-002/UC-007/UC-011; see ``docs/design/specification.md`` Sec 5/6/7.2).

LANDMINE: ``main.c``'s ``mp_main()`` looks for ``main.py`` via a
DIRECT, unconditional filesystem stat (``mp_import_stat()`` ->
``uos_mbfs_import_stat()``), with NO frozen-module fallback -- a
frozen module named ``main`` would never be found. This module is
therefore named ``boot`` and frozen normally via ``manifest.py``
(reachable via ``import boot`` through the normal frozen-module
resolution path, unlike ``mp_main()``'s direct filesystem-only probe).
``build.sh`` patches ``main.c`` to ``mp_import_name(MP_QSTR_boot, ...)``
then call this module's ``run()``, placed immediately after
``mp_init()`` and BEFORE the existing ``main.py``-or-REPL branch,
wrapped in its own ``nlr_push``/``nlr_pop`` pair so any exception here
is printed and boot continues into the REPL regardless -- boot must
never block it.

This module has NO import-time side effects -- all work happens inside
``run()``, called explicitly. That is what lets
``tests/test_boot_sequence.py`` ``import boot`` under CPython and call
``run()`` repeatedly with injected fakes, matching this codebase's
duck-typed-dependency-injection testing convention.

The six steps ``run()`` performs, in order:
  1. Load the robot's JSON config, fail-closed.
  2. ``diffdrive.configure/begin/start`` -- only if step 1 succeeded
     AND a diffdrive-shaped module is available. Also builds a
     ``hardware.protocol_adapter.ProtocolAdapter`` (backed by a real
     ``MoveQueue``/``ConfigDispatch`` on that path, or by
     ``_NullDiffDrive``/an empty ``ConfigDispatch`` on the fail-closed
     path -- see ``_NullDiffDrive``'s own docstring for why comms must
     ALWAYS get a real adapter, never ``None``).
  3. Bring up ``comms.Comms`` (wired to that SAME ``ProtocolAdapter``)
     and the radio transport unconditionally; bring up WiFi only when
     ``wifi_secrets.json`` is present.
  4. Start the scheduled pump, wired to ``microbit.run_every()``.
  5. ``comms.send_banner()`` then ``comms.send_ready()`` -- always,
     regardless of step 1/2's outcome (fail-closed: comms/REPL must
     stay available even on a bad config).
  6. Boot must not block: nothing in ``run()`` performs a blocking
     wait -- every call is non-blocking by contract or a one-shot
     native call documented as returning immediately.

On-device config path: ``CONFIG_PATH = "robot.json"`` -- one fixed,
robot-agnostic, bare (no leading slash) name; this port ENOENTs the
leading-slash form. Whichever robot's JSON is copied onto a unit's
filesystem at bench time goes under this name.

Sprint 007 ticket 006 (v6 line-protocol cutover): this module no
longer builds a banner or ``id_line`` string of its own the way v5's
``_identity_lines()`` did -- ``core/protocol.py``'s ``ProtocolHandler``
now formats "device NEZHA2 robot <name> <serial>" (``HELLO``/the
banner) and "id <drivetrain> <profile> <version>" (``ID``) ON DEMAND
from the shared ``ProtocolAdapter.identity()``, so boot only needs to
hand that adapter the right SCALARS (``_identity_fields()`` below),
never a pre-formatted line. This is the simpler of the two options the
ticket left open, and is what actually made a static ``id_line``
string obsolete: identity() is called fresh every time, so nothing
here can go stale relative to what the wire reports. Field mapping
(this ticket's own call, since ``robot_config.schema.json`` names none
of these "the v6 identity fields" itself):

  - ``name`` (the banner's own field) = ``identity.uid`` -- the
    ROBOT's stable identity, not its currently-loaded config profile;
    critically, it is guaranteed a single wire token, unlike
    ``robot_name`` (``data/tovez_nocal.json``'s own
    ``identity.robot_name`` is the literal two-word string "tovez
    nocal" -- a banner field containing a space would misparse under
    protocol.md's space-delimited field grammar). Falls back to
    ``robot_name`` if ``uid`` is absent (older/malformed JSON).
  - ``profile`` = ``identity.robot_name`` -- which named config
    variant is loaded (e.g. "tovez" vs "tovez nocal"), a required key
    (``REQUIRED_KEYS``) so always present when config load succeeded.
  - ``drivetrain`` = ``identity.get("drivetrain_type", "differential")``
    -- most robot JSONs omit this key entirely (this sprint's kernel
    is DiffDrive-only, CLAUDE.md), but ``data/togov.json`` already
    carries ``"drivetrain_type": "mecanum"``, so reading it when
    present (rather than hardcoding "differential" unconditionally)
    reports that robot's real hardware over the wire without this
    port needing to understand mecanum kinematics at all.
  - ``serial`` = ``connection.serial_last_6`` (unchanged from v5).
  - ``counts_per_length`` (WHEELS' geometry factor, sprint.md Design
    Rationale) = ``wheels.ticks_per_mm`` (``data/tovez.json``:
    12.7602) -- optional (not in ``REQUIRED_KEYS``; ``data/togov.
    json`` carries an explicit JSON ``null`` here, not just a missing
    key), falls back to ``1.0`` when absent/null/non-positive, mirroring
    ``ProtocolAdapter``'s own constructor guard for the same value.

MicroPython-only modules (``diffdrive``, ``microbit``, ``utime``) are
import-guarded so this module imports under CPython (the offline test
gate).
"""

import gc

try:
    import diffdrive
except ImportError:  # CPython, or a build without --with-diffdrive
    diffdrive = None

try:
    import microbit
except ImportError:  # CPython -- no microbit module off-device
    microbit = None

try:
    import utime as _time
except ImportError:  # CPython has no utime -- fall back to time.monotonic()
    import time as _time

from core import comms
from core import config
from hardware import motion
from hardware import protocol_adapter
from core import radio_shim
from core import wifi_at

__all__ = [
    "CONFIG_PATH",
    "SECRETS_PATH",
    "DEFAULT_RADIO_CHANNEL",
    "PUMP_PERIOD_MS",
    "VERSION",
    "BootResult",
    "run",
    "last_result",
]

CONFIG_PATH = "robot.json"  # bare name -- leading slash ENOENTs on this port

# Gitignored, provided locally at bench time (CLAUDE.md: no secrets in repo).
SECRETS_PATH = "wifi_secrets.json"

# Matches MICROBIT_RADIO_DEFAULT_CHANNEL (micropython-microbit-v2's
# drv_radio.h) -- used only when config load failed (step 3 still
# brings up radio unconditionally).
DEFAULT_RADIO_CHANNEL = 7

# Matches the kernel's own native cadence (vendor/differential_drive.h
# cyclePeriod default) so the pump keeps pace with fresh diffdrive output.
PUMP_PERIOD_MS = config.DEFAULT_CYCLE_PERIOD_MS

# Reported by ID/VER (via ProtocolAdapter.identity()) -- spec Sec 10
# open item 1.
VERSION = "nezha-upy-0.1"

_DEFAULT_SERIAL_SUFFIX = "000000"


def _now_ms():
    """Monotonic milliseconds -- ``utime.ticks_ms()`` on-device,
    ``time.monotonic()*1000`` under CPython (no ``ticks_ms`` there).
    The default ``now_fn`` for ``comms.PumpTimer``/``_BootPumpTimer``."""
    if hasattr(_time, "ticks_ms"):
        return _time.ticks_ms()
    return int(_time.monotonic() * 1000)


def _identity_fields(robot_config):
    """``(name, serial, drivetrain, profile, counts_per_length)`` for
    the v6 ``ProtocolAdapter`` -- see module docstring's field-mapping
    note for what each maps from and why. ``robot_config`` may be
    ``None`` (fail-closed path); this never raises, since HELLO/ID
    must still answer either way."""
    if robot_config is not None:
        identity = robot_config.get("identity") or {}
        robot_name = identity["robot_name"]
        name = identity.get("uid", robot_name)
        drivetrain = identity.get("drivetrain_type", "differential")
        profile = robot_name
        connection = robot_config.get("connection") or {}
        serial = connection.get("serial_last_6", _DEFAULT_SERIAL_SUFFIX)
        wheels = robot_config.get("wheels") or {}
        raw_counts_per_length = wheels.get("ticks_per_mm")
        counts_per_length = (
            float(raw_counts_per_length) if raw_counts_per_length else 1.0
        )
    else:
        name = "unconfigured"
        drivetrain = "differential"
        profile = "unconfigured"
        serial = _DEFAULT_SERIAL_SUFFIX
        counts_per_length = 1.0
    return name, serial, drivetrain, profile, counts_per_length


class _NullDiffDrive(object):
    """No-op diffdrive stand-in for the fail-closed path (config load
    failed, or no diffdrive-shaped module is available). Step 3 brings
    up comms/REPL unconditionally (module docstring), and v6's
    ``protocol.ProtocolHandler`` always needs a real ``ProtocolAdapter``
    -- unlike v5's ``NullDispatch``, there is no "no adapter at all"
    option (``ProtocolHandler.__init__`` takes one positionally, not an
    optional). Wrapping THIS in a real ``MoveQueue`` gives
    ``ProtocolAdapter`` something duck-typed to call that never touches
    any real hardware. ``drive()`` answers the exact status string
    (``"refused_unconfigured"``) ``protocol_adapter.py``'s own
    ``_STATUS_TO_RESULT`` table already maps onto
    ``protocol.Result.NOT_CONFIGURED`` -- no new mapping needed."""

    def drive(self, velocity, twist, lease_ms):
        return "refused_unconfigured"

    def neutral(self):
        pass

    def estop(self):
        pass

    def output(self):
        return {
            "ready": False, "estopped": False, "leaseExpired": False,
            "stallHalted": False, "connectedLeft": False,
            "connectedRight": False, "velocity": 0.0, "twist": 0.0,
        }


class _BootPumpTimer(comms.PumpTimer):
    """``comms.PumpTimer``, extended to also drive ``wifi_at``'s own
    per-cycle ``pump()`` (AT servicing + READY-on-new-peer-edge) from
    the SAME ``micropython.schedule()`` tick, by composing
    ``tick()``/``_pump_now()`` rather than modifying ``comms.py``.
    ``tick()`` is inherited unchanged -- still degrades to a
    synchronous call under CPython (no ``micropython`` module there)."""

    def __init__(self, comms_obj, now_fn, wifi_link=None):
        comms.PumpTimer.__init__(self, comms_obj, now_fn)
        self._wifi_link = wifi_link

    def _pump_now(self, arg):
        comms.PumpTimer._pump_now(self, arg)
        if self._wifi_link is not None:
            wifi_at.pump(self._wifi_link, self._now_fn(), self._comms)


class BootResult:
    """Everything ``run()`` assembled -- plain attributes (no
    ``dataclasses``, matching ``comms.Status``/``otos.OtosReading``),
    so tests can assert on each piece directly. Nothing here is
    scattered into separate module globals; the one exception is
    ``last_result()`` below (sprint 007 ticket 009, first hardware
    bring-up of ``wifi_at.py``), which exists ONLY so a bench REPL
    session -- which never sees ``run()``'s return value, since
    ``main.c``'s boot call site discards it -- has some way to reach
    ``result.wifi_link.state()`` for diagnosis. It is a debug
    convenience, not a supported runtime API, and nothing in ``run()``
    itself reads it back."""

    def __init__(self):
        self.robot_config = None   # released after Step 3; see run()
        self.config_loaded = False  # survives the release -- readiness flag
        self.config_error = None
        self.diffdrive_ready = False
        self.dispatch = None  # set in Step 2 -- always a ProtocolAdapter once run() returns
        self.comms = None
        self.radio_link = None
        self.wifi_link = None
        self.pump_timer = None

    def config_ok(self):
        # NOT `robot_config is not None`: run() releases the parsed
        # document once the scalars are extracted, so the flag has to
        # outlive it.
        return self.config_loaded


_last_result = None  # bench-debug only; see BootResult's own docstring


def last_result():
    """Return the ``BootResult`` from the most recent ``run()`` call,
    or ``None`` if ``run()`` has never been called this boot.

    Bench-diagnostic escape hatch (sprint 007 ticket 009): the
    automatic power-on call to ``run()`` (``main.c``'s patched boot
    site) discards its return value, so a REPL session opened after
    boot has no handle on ``result.wifi_link``/``result.comms`` at
    all -- there is no other reachable reference once ``run()``
    returns (the pump keeps the object graph alive via the
    ``run_every`` callback closure, but nothing exposes it to
    Python). At the REPL: ``import core.boot as boot;
    boot.last_result().wifi_link.state()``. Do not call ``run()``
    again from the REPL to "refresh" this -- it would register a
    second radio/WiFi transport and a second scheduled pump on top of
    the one already running from power-on, corrupting both."""
    return _last_result


def run(config_path=CONFIG_PATH, secrets_path=SECRETS_PATH,
        diffdrive_module=diffdrive, wifi_serial_factory=None,
        wifi_repl_hook_factory=None, run_every=None, now_fn=None,
        version=VERSION, pump_period_ms=PUMP_PERIOD_MS):
    """Perform the six-step boot sequence (see module docstring) and
    return a ``BootResult``. Every hardware-touching dependency is an
    injectable parameter, defaulting to the real on-device object (or
    a no-op degrade off-device) -- this lets the same function serve
    both ``main.c``'s boot call (all defaults) and CPython unit tests
    (fakes injected per scenario). Never blocks and never raises for
    the fail-closed case (a bad/missing config)."""
    if now_fn is None:
        now_fn = _now_ms
    if wifi_serial_factory is None:
        wifi_serial_factory = wifi_at.NativeWifiSerial
    if wifi_repl_hook_factory is None:
        wifi_repl_hook_factory = wifi_at.NativeReplHook
    if run_every is None and microbit is not None:
        run_every = microbit.run_every

    result = BootResult()

    # --- Step 1: load the robot's JSON config, fail-closed. -------------
    try:
        result.robot_config = config.load_robot_config(config_path)
        result.config_loaded = True
    except config.ConfigError as exc:
        result.config_error = exc
        print("BOOT: robot config load failed -- motion refused:", exc)

    # --- Step 2: diffdrive configure/begin/start + ProtocolAdapter -----
    # wiring. diffdrive itself is armed only on a valid config AND an
    # available diffdrive-shaped module; the ProtocolAdapter (and the
    # MoveQueue/ConfigDispatch it wraps) is built EITHER WAY -- comms
    # must always get a real adapter, never None (see _NullDiffDrive's
    # own docstring for why).
    if result.robot_config is not None and diffdrive_module is not None:
        kwargs = config.diffdrive_configure_kwargs(result.robot_config)
        diffdrive_module.configure(**kwargs)
        # LANDMINE: deliberately no begin()/start() here -- a later
        # consumer re-configures with its own gains, and doing that
        # under a live kernel fiber orphans it and kills all motion
        # (bench log). Boot stages a valid config; the FIRST motion
        # consumer begins/starts the fiber.
        result.diffdrive_ready = True
        move_queue = motion.MoveQueue(diffdrive_module)
    else:
        move_queue = motion.MoveQueue(_NullDiffDrive())

    if result.robot_config is not None:
        config_dispatch = config.ConfigDispatch(result.robot_config)
    else:
        config_dispatch = config.ConfigDispatch({"wheel_control": {}})

    # `robot_serial` (not `serial`) -- Step 3 below reuses the name
    # `serial` for the WiFi AT byte-pipe object; keeping these two
    # distinct avoids a same-name-different-thing trap even though the
    # ProtocolAdapter call below already captures this value first.
    name, robot_serial, drivetrain, profile, counts_per_length = (
        _identity_fields(result.robot_config))
    result.dispatch = protocol_adapter.ProtocolAdapter(
        move_queue, config_dispatch, counts_per_length,
        name, robot_serial, drivetrain, profile, version, now_fn=now_fn)

    # --- Step 3: comms.Comms + transports. ------------------------------
    # Release the parsed config: everything downstream needs only the
    # scalars already extracted above (diffdrive kwargs, the
    # wheel_control copy inside ConfigDispatch, and the identity/geometry
    # scalars just pulled for the ProtocolAdapter). Measured on tovez: the
    # document is ~6.9 KB of a ~16.7 KB heap -- 41% of it -- and holding
    # it was the single largest resident allocation on the device.
    # Callers use config_ok(), not `robot_config is not None`.
    result.robot_config = None
    gc.collect()

    result.comms = comms.Comms(result.dispatch)

    if result.robot_config is not None:
        channel = config.radio_channel(result.robot_config)
    else:
        channel = DEFAULT_RADIO_CHANNEL
    result.radio_link = radio_shim.RadioLink(channel=channel)
    result.radio_link.begin()
    result.comms.add_transport(result.radio_link)

    ssid, password = wifi_at.load_secrets(secrets_path)
    if ssid is not None:
        serial = wifi_serial_factory()
        repl_hook = wifi_repl_hook_factory() if wifi_repl_hook_factory is not None else None
        result.wifi_link = wifi_at.WifiAtLink(serial, ssid, password, repl_hook=repl_hook)
        result.comms.add_transport(result.wifi_link)

    # --- Step 4: scheduled pump, wired to a real timer source. ---------
    # microbit.run_every() is serviced from a hardware timer IRQ
    # (drv_system.c) -- safe to call tick() from there because tick()
    # only ever queues via micropython.schedule() and returns,
    # deferring all heap-touching work (comms.pump(), wifi_at.pump())
    # to the next safe main-context point (see PumpTimer's docstring).
    result.pump_timer = _BootPumpTimer(result.comms, now_fn, wifi_link=result.wifi_link)
    if run_every is not None:
        run_every(callback=result.pump_timer.tick, ms=pump_period_ms)

    # --- Step 5: banner/boot/READY -- always, regardless of steps 1/2.
    # LANDMINE: fail-soft here -- an uncaught exception scrolls forever
    # on the LED display (robot looks bricked). Boot must never die for
    # a diagnostics banner (bench log).
    try:
        result.comms.send_banner()
        result.comms.send_ready()
    except Exception as exc:
        print("BOOT: banner/ready send failed (continuing):", exc)

    # --- Step 6: boot must not block. -----------------------------------
    # Every call above is non-blocking by contract or a one-shot native
    # call documented as returning immediately (native/README.md).
    # run() returning here is the "REPL stays live" guarantee.
    global _last_result
    _last_result = result
    return result
