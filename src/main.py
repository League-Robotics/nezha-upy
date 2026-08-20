"""main -- zetuv on-device student-code entry point. Deployed to the
device filesystem as ``main.py`` -- the student-code slot, never
frozen (a frozen module named ``main`` would never be found by
``mp_main()``'s filesystem-only probe; see ``src/boot.py``'s
docstring). This copy under ``src/main.py`` is for version control
only and has no effect until copied onto a device as ``main.py``.
Runs after ``boot.py`` (frozen, assembles comms/diffdrive at
power-on).

Wires button A to the ``demo_square`` square tour and button B to a
single ``STRAIGHT_DRIVE_DISTANCE_MM`` straight leg, each via a fresh
``sys.modules.pop(...) + import demo_square`` so every press re-runs
``demo_square``'s own top-level auto-run guard and re-reads current
config-driven geometry from ``robot.json``.

LANDMINE: this firmware cannot load a precompiled ``.mpy`` from the
filesystem at all (``MICROPY_PERSISTENT_CODE_LOAD`` off) -- and raw
``.py`` source is large enough to exhaust this device's heap if
compiled at runtime naively. ``demo_square`` must be deployed as
docstring-stripped raw ``.py`` source. Full derivation:
docs/bench-log-zetuv-2026-08-19.md.

``robot_ready()`` checks ``robot.json``/``diffdrive`` directly rather
than via ``config.load_robot_config()`` -- zetuv's resident frozen
``config`` module is a stale stub on this image (bench log). LANDMINE:
``robot.json`` is opened with no leading slash -- the leading-slash
form ENOENTs on this port even though the same file opens fine bare
(bench log).

``run_tour()``/``run_straight_drive()`` call
``demo_square.run()``/``run_single_leg()`` explicitly rather than
relying on import's own side effect -- ``demo_square`` exposes two
behaviours now, so a plain ``import`` can no longer select between
them (see ``demo_square``'s own module docstring).

``run()`` is gated on ``if __name__ == "__main__":`` -- bench-confirmed
true for the filesystem-executed ``main.py`` boot context, but not for
this whole file being separately ``exec()``'d into a namespace with a
different ``__name__`` (REPL verification); individual functions
remain directly callable either way. The idle loop below only ever
polls ``was_pressed()`` and sleeps -- ``sleep()`` reaches
``microbit_hal_idle()``, keeping the kernel fiber fed. No callback/IRQ
context is used anywhere in this file.
"""

import os
import sys

from microbit import Image, button_a, button_b, display, sleep

# Bare path, no leading slash -- see module docstring.
ROBOT_CONFIG_PATH = "robot.json"

# LANDMINE -- see module docstring's deploy-format paragraph and
# docs/bench-log-zetuv-2026-08-19.md.
TOUR_MODULE_NAME = "demo_square"

STRAIGHT_DRIVE_DISTANCE_MM = 500.0  # [mm] button B's commanded distance

IDLE_POLL_MS = 150
FAULT_SHOW_MS = 1000
REFUSED_SHOW_MS = 600

# Idle "breathing" pulse -- proves the loop is alive, not a frozen image.
_BREATH_LEVELS = (1, 3, 5, 7, 9, 7, 5, 3)


def robot_ready():
    """Fail-closed probe -- see module docstring. True only when
    ``robot.json`` exists and is non-empty AND ``diffdrive`` is
    importable. Never raises -- every failure mode returns False."""
    try:
        if os.stat(ROBOT_CONFIG_PATH)[6] <= 0:
            return False
    except OSError:
        return False
    try:
        import diffdrive  # noqa: F401 -- reachability check only
    except ImportError:
        return False
    return True


def run_tour():
    """Fresh (re)import of ``demo_square``, then an explicit
    ``demo_square.run()`` call -- see module docstring. Popping first
    forces a fresh reload (source, not bytecode), which also re-reads
    ``robot.json``'s current geometry every press. Raises whatever
    ``demo_square.run()`` raises; the caller (``on_button_a``) handles
    that."""
    import gc
    gc.collect()  # heap is tight; defragment before the module reload
    sys.modules.pop(TOUR_MODULE_NAME, None)
    from demos import demo_square
    demo_square.run()


def run_straight_drive():
    """Button B's entry point -- same fresh-reload pattern as
    ``run_tour()``, but calls ``demo_square.run_single_leg()`` instead
    of ``demo_square.run()``: the same encoder-terminated,
    lease-refreshed straight-drive primitive the square tour's own legs
    use, reused rather than reimplemented. Raises whatever
    ``demo_square.run_single_leg()`` raises; the caller (``on_button_b``)
    handles that."""
    import gc
    gc.collect()  # heap is tight; defragment before the module reload
    sys.modules.pop(TOUR_MODULE_NAME, None)
    from demos import demo_square
    demo_square.run_single_leg(STRAIGHT_DRIVE_DISTANCE_MM)


def on_button_a():
    """Button-A handler: shows HEART, runs the tour, guarded so a tour
    fault shows SAD (with the error logged) rather than dying silently.
    ``KeyboardInterrupt`` is always re-raised, never swallowed."""
    display.show(Image.HEART)
    try:
        run_tour()
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate broad catch;
        # a tour fault must show something on the display, not die
        # silently. KeyboardInterrupt is excluded above.
        print("main: tour fault:", exc)
        display.show(Image.SAD)
        sleep(FAULT_SHOW_MS)
    display.clear()


def on_button_b():
    """Button-B handler: same shape as ``on_button_a()`` (distinct
    feedback -> drive -> fault-guarded -> clear), but shows
    ``Image.ARROW_E`` and drives ``run_straight_drive()`` (a single
    500 mm leg) instead of the full square tour."""
    display.show(Image.ARROW_E)
    try:
        run_straight_drive()
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate broad catch;
        # same reasoning as on_button_a()'s own guard.
        print("main: straight-drive fault:", exc)
        display.show(Image.SAD)
        sleep(FAULT_SHOW_MS)
    display.clear()


def _idle_frame(tick, ready):
    """One frame of the idle display -- NO (fail-closed) when the
    robot isn't ready, otherwise one step of the breathing pulse."""
    if not ready:
        display.show(Image.NO)
        return
    display.set_pixel(2, 2, _BREATH_LEVELS[tick % len(_BREATH_LEVELS)])


def run():
    """Main-context loop: poll ``button_a``/``button_b.was_pressed()``
    + sleep, never a callback -- see module docstring.
    ``robot_ready()`` is evaluated once at start (the filesystem/
    native-module state it checks does not change while this loop
    runs). Both buttons are polled every tick with the same
    ready/not-ready gating, each consuming its own ``was_pressed()``
    latch independently, so a same-tick double-press runs both
    handlers in sequence (A then B), not either being dropped."""
    ready = robot_ready()
    if not ready:
        print("main: robot not ready (no robot.json, or it's empty, "
              "or diffdrive is unavailable) -- fail-closed, showing NO")
    tick = 0
    while True:
        try:
            _idle_frame(tick, ready)
            if button_a.was_pressed():
                if ready:
                    on_button_a()
                else:
                    display.show(Image.NO)
                    sleep(REFUSED_SHOW_MS)
            if button_b.was_pressed():
                if ready:
                    on_button_b()
                else:
                    display.show(Image.NO)
                    sleep(REFUSED_SHOW_MS)
            sleep(IDLE_POLL_MS)
            tick += 1
        except KeyboardInterrupt:
            raise


if __name__ == "__main__":
    run()
