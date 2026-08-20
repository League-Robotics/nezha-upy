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
     AND a diffdrive-shaped module is available. Also wires
     ``motion.RobotDispatch`` as ``comms.Comms``'s dispatch.
  3. Bring up ``comms.Comms`` and the radio transport unconditionally;
     bring up WiFi only when ``wifi_secrets.json`` is present.
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

Banner/ID content mirrors ``tests/test_comms_loopback.py``'s
``BANNER = "DEVICE:NEZHA2:robot:testbot:12345"`` fixture, with real
per-robot data (``identity.robot_name``, ``connection.serial_last_6``)
-- not independently re-verified byte-for-byte against radio-robot's
real C++ source.

MicroPython-only modules (``diffdrive``, ``microbit``, ``utime``) are
import-guarded so this module imports under CPython (the offline test
gate).
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

# See module docstring "Banner/ID content" -- spec Sec 10 open item 1.
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
    """Build the (banner, id_line) pair -- see module docstring.
    ``robot_config`` may be ``None`` (fail-closed path); this never
    raises, since the banner must still emit either way."""
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
    so tests can assert on each piece directly. This module keeps no
    module-level state; nothing survives boot outside this object."""

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
    except config.ConfigError as exc:
        result.config_error = exc
        print("BOOT: robot config load failed -- motion refused:", exc)

    # --- Step 2: diffdrive configure/begin/start + dispatch wiring, ----
    # only on a valid config AND an available diffdrive-shaped module.
    dispatch = None
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
    return result
