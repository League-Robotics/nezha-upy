"""boot -- frozen boot module: assembles the firmware layer at power-on
(sprint 001 ticket 010, sprint.md's Architecture Revision 2026-08-19 /
``docs/design/specification.md`` Sec 5/6/7.2, UC-002/UC-007/UC-011).

**Gap this closes**: tickets 004-007 each built one milestone's piece
(native diffdrive module, wire codec, protocol engine, WiFi transport,
Python firmware layer) but none of them owned assembling those pieces
into a running image at power-on -- see ``docs/bench-acceptance-
procedures.md``'s (now-rewritten) former A.3 section for the exact gap
this module closes, and ``comms.PumpTimer``'s own docstring for the
"actual timer source" this module supplies.

**How this module gets to run at all -- grounded, not assumed**: the
ticket that created this module explicitly required confirming
``micropython-microbit-v2``'s real boot hook rather than assuming
``main.py`` is correct by convention. Reading
``micropython-microbit-v2/src/codal_port/main.c``'s ``mp_main()``
directly: it checks for ``main.py`` via ``mp_import_stat(main_py) ==
MP_IMPORT_STAT_FILE``, and that function (``main.c``'s own
``mp_import_stat()``) is a **direct, unconditional call to
``uos_mbfs_import_stat()``** (``microbitfs.c``) -- the on-device
**filesystem** stat, with **no frozen-module fallback**. A frozen
``main.py`` would therefore NEVER be found by this check; freezing a
module under that name would silently never run at boot. This module is
instead named ``boot`` (this file, ``src/boot.py``) and frozen normally
via ``manifest.py`` (an ordinary frozen module, reachable by ``import
boot`` exactly like ``comms``/``config``/etc. already are -- frozen-
module imports go through the normal ``mp_import_name()`` resolution
path, which DOES check the frozen table, unlike ``mp_main()``'s own
direct filesystem-only ``main.py`` probe). ``build.sh``'s own "Wire the
frozen boot module into main.c's power-on sequence" step patches
``main.c`` to explicitly ``mp_import_name(MP_QSTR_boot, ...)`` then call
this module's ``run()`` -- placed immediately after ``mp_init()`` and
BEFORE the existing ``main.py``-or-``from microbit import *`` branch, so
a student's own filesystem ``main.py`` (the standard micro:bit drag-and
-drop workflow) still runs afterward, on top of an already-assembled
engine, unchanged. The call is wrapped in its own ``nlr_push``/``nlr_pop``
pair in ``main.c`` (mirroring ``microbit_pyexec_file()``'s own pattern in
the same file) as a last-resort safety net: if anything in this module
raises an exception this module's own fail-closed handling below does
not already catch, the exception is printed and boot continues into the
REPL regardless -- boot must never block it (ticket's own step 6).

**This module has NO import-time side effects.** All work happens
inside ``run()``, called explicitly (never via a bare ``import boot``
auto-running anything) -- this is what lets ``tests/test_boot_sequence.py``
``import boot`` under CPython and call ``run()`` repeatedly with
injected fakes, matching every other module in this codebase's own
duck-typed-dependency-injection testing convention (see e.g.
``radio_shim.RadioLink``, ``wifi_at.WifiAtLink``, ``motion.MoveQueue``).

**The six steps** (ticket's own enumeration; ``run()``'s body performs
them in this exact order):

  1. Load the robot's JSON config, fail-closed.
  2. ``diffdrive.configure/begin/start`` -- only if step 1 succeeded AND
     a diffdrive-shaped module is actually available (native build
     variant, or an injected stub under test). Also wires
     ``motion.RobotDispatch`` (``motion.MoveQueue`` + ``config.
     ConfigDispatch``) as ``comms.Comms``'s dispatch, gated on the SAME
     condition -- this is "assembling", not new logic: ``motion.py``'s
     own docstring already names ``RobotDispatch`` as "the single
     composite object wired as ``comms.Comms(..., dispatch=...)``".
  3. Bring up ``comms.Comms`` and the radio transport unconditionally;
     bring up the WiFi transport only when ``wifi_secrets.json`` is
     present (``wifi_at.load_secrets()`` returns ``(None, None)``
     otherwise -- not an error, per that function's own docstring).
  4. Start the scheduled pump, wired to ``microbit.run_every()`` -- see
     ``PUMP_PERIOD_MS`` / ``_BootPumpTimer`` below for why this hook and
     not a new native timer.
  5. ``comms.send_banner()`` then ``comms.send_ready()`` -- always,
     regardless of step 1/2's outcome (the fail-closed acceptance
     criterion: "comms/REPL still available (banner still emits...)").
  6. Boot must not block: nothing in ``run()`` performs a blocking wait
     (no ``time.sleep``, no polling loop) -- enforced by construction,
     every call here is either non-blocking-by-contract (``RadioLink.
     begin()``, ``WifiAtLink.__init__``) or a plain one-shot native call
     (``diffdrive.configure/begin/start``, all documented as returning
     immediately in ``native/README.md``).

**On-device config path convention (this module's own decision, flagged
here rather than guessed silently)**: no document in this repo pins an
exact on-device filesystem path for the robot's JSON. ``build.sh`` has
no per-robot build flag anywhere (grepped, confirmed) and the M6
RAM/flash checkpoint measures ONE hex's footprint -- so the built image
is robot-AGNOSTIC; per-robot specialization is entirely a filesystem-
content concern, decided at bench-flash time (out of this ticket's
scope, same division ``data/tovez.json`` etc. already establish: "the
robot JSON... the on-device filesystem holds robot JSON + student code;
frozen modules hold the code"). A frozen, robot-agnostic module
therefore needs ONE fixed, generic on-device path, not a robot-specific
filename ``config.py``'s own docstring example (``"/tovez.json"``) would
only work for one specific robot. This module fixes that path as
``CONFIG_PATH = "/robot.json"`` -- whichever robot's JSON content is
copied onto a given unit's filesystem at bench time, it goes under this
one name. ``docs/bench-acceptance-procedures.md``'s ticket-010 revision
records this convention for the bench operator.

**Banner/ID/VERSION content (this module's own decision)**: spec Sec 10
open item 1 explicitly leaves "the version value... flag if any host
tool pins the old value" as a non-blocking, decide-during-execution
item, and ``comms.Comms``'s own docstring says a banner is passed in
"already-formatted" -- the exact byte content was always deferred to
whoever constructs ``Comms``, i.e. this module. ``tests/test_comms_
loopback.py``'s own ``BANNER = "DEVICE:NEZHA2:robot:testbot:12345"``
(ticket 005's own M3 gate fixture) is the only grounded evidence of the
real shape in this repo; this module reproduces that shape with real
per-robot data: ``identity.robot_name`` (a ``REQUIRED_KEYS`` field, so
always present on a successful config load) and ``connection.
serial_last_6`` (present in every copied robot JSON --
``data/tovez.json``'s own value, "f137c0", is independently confirmed
in ``docs/bench-acceptance-procedures.md`` -- optional in the schema, so
defaulted rather than required here). Not independently re-verified
byte-for-byte against radio-robot's real C++ source (not available in
this repo) -- flagged, not silently assumed exact.

MicroPython-only modules (``diffdrive``, ``microbit``, ``utime``) are
import-guarded so this module imports under CPython (this ticket's own
offline gate).
"""

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

import comms
import config
import motion
import radio_shim
import wifi_at

__all__ = [
    "CONFIG_PATH",
    "SECRETS_PATH",
    "DEFAULT_RADIO_CHANNEL",
    "PUMP_PERIOD_MS",
    "VERSION",
    "BootResult",
    "run",
]

# See module docstring "On-device config path convention".
CONFIG_PATH = "/robot.json"

# Matches wifi_at.load_secrets()'s own default -- gitignored, provided
# locally at bench time (CLAUDE.md: "No secrets in the repo").
SECRETS_PATH = "wifi_secrets.json"

# Matches MICROBIT_RADIO_DEFAULT_CHANNEL (micropython-microbit-v2/src/
# codal_port/drv_radio.h) -- the radio module's own stock default,
# verified directly against that header. Used only when config load
# failed (step 3 brings up radio UNCONDITIONALLY, per the ticket's own
# wording, even with no valid per-robot channel to read).
DEFAULT_RADIO_CHANNEL = 7

# The scheduled-pump tick period -- matches config.DEFAULT_CYCLE_PERIOD_MS
# (the kernel's own native cadence, vendor/differential_drive.h's
# cyclePeriod default) so the pump keeps pace with fresh diffdrive
# output roughly once per kernel cycle.
PUMP_PERIOD_MS = config.DEFAULT_CYCLE_PERIOD_MS

# See module docstring "Banner/ID/VERSION content" -- spec Sec 10 open
# item 1's own "decide during execution" instruction.
VERSION = "nezha-upy-0.1"

_DEFAULT_SERIAL_SUFFIX = "000000"


def _now_ms():
    """Monotonic milliseconds -- ``utime.ticks_ms()`` on-device,
    ``time.monotonic()*1000`` under CPython (no ``ticks_ms`` there).
    The default ``now_fn`` for ``comms.PumpTimer``/``_BootPumpTimer``."""
    if hasattr(_time, "ticks_ms"):
        return _time.ticks_ms()
    return int(_time.monotonic() * 1000)


def _identity_lines(robot_config, version):
    """Build the (banner, id_line) pair -- see module docstring
    "Banner/ID/VERSION content". ``robot_config`` may be ``None`` (the
    fail-closed path) -- the fail-closed acceptance criterion requires
    the banner to still emit, so this never raises."""
    if robot_config is not None:
        robot_name = robot_config["identity"]["robot_name"]
        connection = robot_config.get("connection") or {}
        serial_suffix = connection.get("serial_last_6", _DEFAULT_SERIAL_SUFFIX)
    else:
        robot_name = "unconfigured"
        serial_suffix = _DEFAULT_SERIAL_SUFFIX
    banner = "DEVICE:NEZHA2:robot:%s:%s" % (robot_name, serial_suffix)
    id_line = "ID:nezha:%s:%s" % (robot_name, version)
    return banner, id_line


class _BootPumpTimer(comms.PumpTimer):
    """``comms.PumpTimer``, extended to also drive ``wifi_at``'s own
    per-cycle ``pump()`` (AT servicing + READY-on-new-peer-edge) from
    the SAME ``micropython.schedule()`` tick -- composing PumpTimer's
    already-published ``tick()``/``_pump_now()`` shape rather than
    modifying it: ``comms.py`` is not in this ticket's file scope (its
    own ``PumpTimer`` has no seam for a second per-cycle callback, and
    editing a ticket-005-owned, already-tested module to add one would
    be out of scope here). ``tick()`` itself is inherited unchanged --
    still only ever queues via ``micropython.schedule()``, still
    degrades to a synchronous call under CPython (no ``micropython``
    module there), per ``PumpTimer``'s own docstring."""

    def __init__(self, comms_obj, now_fn, wifi_link=None):
        comms.PumpTimer.__init__(self, comms_obj, now_fn)
        self._wifi_link = wifi_link

    def _pump_now(self, arg):
        comms.PumpTimer._pump_now(self, arg)
        if self._wifi_link is not None:
            wifi_at.pump(self._wifi_link, self._now_fn(), self._comms)


class BootResult:
    """Everything ``run()`` assembled -- plain attributes (no
    ``dataclasses``, matching ``comms.Status``/``otos.OtosReading``'s
    own precedent), returned so ``tests/test_boot_sequence.py`` can
    assert on each piece directly instead of reaching into module-level
    globals (this module keeps none -- no boot-time state survives
    outside the returned result and whatever objects it references)."""

    def __init__(self):
        self.robot_config = None
        self.config_error = None
        self.diffdrive_ready = False
        self.dispatch = None
        self.comms = None
        self.radio_link = None
        self.wifi_link = None
        self.pump_timer = None

    def config_ok(self):
        return self.robot_config is not None


def run(config_path=CONFIG_PATH, secrets_path=SECRETS_PATH,
        diffdrive_module=diffdrive, wifi_serial_factory=None,
        wifi_repl_hook_factory=None, run_every=None, now_fn=None,
        version=VERSION, pump_period_ms=PUMP_PERIOD_MS):
    """Perform the six-step boot sequence (see module docstring) and
    return a ``BootResult``. Every hardware-touching dependency is an
    injectable parameter defaulting to the real on-device object (or
    ``None``/a no-op degrade off-device) -- see each parameter's use
    below; this is what lets this same function serve both ``main.c``'s
    boot call (all defaults) and this ticket's CPython unit tests (fakes
    injected for whichever piece a given test scenario needs to control).
    Never blocks and never raises for the documented fail-closed case
    (a bad/missing config) -- see step 6 in the module docstring."""
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
    except config.ConfigError as exc:
        result.config_error = exc
        print("BOOT: robot config load failed -- motion refused:", exc)

    # --- Step 2: diffdrive configure/begin/start + dispatch wiring, ----
    # only on a valid config AND an available diffdrive-shaped module.
    dispatch = None
    if result.robot_config is not None and diffdrive_module is not None:
        kwargs = config.diffdrive_configure_kwargs(result.robot_config)
        diffdrive_module.configure(**kwargs)
        diffdrive_module.begin()
        diffdrive_module.start()
        result.diffdrive_ready = True

        move_queue = motion.MoveQueue(diffdrive_module)
        config_dispatch = config.ConfigDispatch(result.robot_config)
        dispatch = motion.RobotDispatch(config_dispatch, move_queue)
    result.dispatch = dispatch

    # --- Step 3: comms.Comms + transports. ------------------------------
    banner, id_line = _identity_lines(result.robot_config, version)
    result.comms = comms.Comms(banner, id_line, dispatch=dispatch, version=version)

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
    # microbit.run_every() (micropython-microbit-v2/src/codal_port/
    # modmicrobit.c) is the port's own periodic-callback mechanism, built
    # on drv_softtimer's soft-timer heap -- serviced from
    # microbit_hal_timer_callback() (drv_system.c, a 6ms hardware timer
    # callback) which calls straight into mp_call_function_0() on the
    # registered Python callback. That is exactly the "hardware timer
    # IRQ" PumpTimer.tick()'s own docstring anticipates as its periodic
    # source ("tick() ONLY EVER queues the real work via
    # micropython.schedule(), never runs it directly") -- tick() is safe
    # to call from run_every's callback for precisely that reason: it
    # does the minimal, allocation-light micropython.schedule() call and
    # returns, deferring all heap-touching work (comms.pump(),
    # wifi_at.pump()) to the next safe main-context point. No native
    # module change needed -- this hook already ships in the port.
    result.pump_timer = _BootPumpTimer(result.comms, now_fn, wifi_link=result.wifi_link)
    if run_every is not None:
        run_every(callback=result.pump_timer.tick, ms=pump_period_ms)

    # --- Step 5: banner/boot/READY -- always, regardless of steps 1/2. -
    result.comms.send_banner()
    result.comms.send_ready()

    # --- Step 6: boot must not block. -----------------------------------
    # Nothing above performs a blocking wait -- every call is either
    # non-blocking by its own contract (RadioLink.begin(), WifiAtLink.
    # __init__, PumpTimer.tick()'s schedule-and-return) or a one-shot
    # native call documented as returning immediately (native/README.md).
    # run() returning here IS the "REPL stays live" guarantee: main.c's
    # boot call site runs this before the REPL loop even starts.
    return result
