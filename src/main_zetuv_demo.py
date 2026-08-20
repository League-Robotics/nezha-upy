"""main -- zetuv on-device student-code entry point (sprint 003 ticket
001, ``clasi/sprints/003-button-a-square-tour-trigger-on-zetuv/``,
UC-002/UC-003). Wires physical button A to the ``demo_square`` tour:
idle prompt -> button A -> HEART -> square tour -> idle prompt,
repeatable. Runs after ``boot.py`` (frozen, already assembled the
comms/diffdrive layer at power-on) exactly as micro:bit's own
drag-and-drop convention expects -- see ``src/boot.py``'s own module
docstring for the hand-off (``main.c``'s ``mp_main()`` looks for a
FILESYSTEM ``main.py`` via ``mp_import_stat()``, confirmed there
directly, not assumed).

**This file is deployed to the device filesystem as ``main.py``** --
it is the student-code slot, not a frozen module (freezing a module
named ``main`` would never be found by ``mp_main()``'s filesystem-only
probe -- see ``src/boot.py``'s docstring for the same reasoning applied
to why ``boot.py`` itself is named ``boot``, not ``main``). This copy
under ``src/main_zetuv_demo.py`` exists purely for version control --
it is never imported from here, never frozen, and has no effect except
when copied onto a device's filesystem as ``main.py``
(``mpremote ... fs cp src/main_zetuv_demo.py :main.py``).

**Why ``demo_square`` is deployed as a precompiled ``demo_square.mpy``
and invoked via ``sys.modules.pop`` + ``import``, not raw-source
``exec()`` -- bench-forced, not a stylistic choice**: ``src/
demo_square.py`` is a SCRIPT, not a library -- its own module
docstring and this repo's sprint 002 bench log both document it as
designed to be run via ``mpremote ... run src/demo_square.py``,
deliberately never added to ``manifest.py`` (freezing it would make a
bare ``import demo_square`` from any REPL an accidental motor-drive
trigger). Its last line is an unconditional top-level ``if
_ON_DEVICE: run()`` -- no reload-safe entry point, no name-guard. A
plain, one-time ``import demo_square`` would auto-run the tour once on
the FIRST button press (Python's own import-caching side effect) but
silently do NOTHING on every subsequent press, breaking this ticket's
own "repeatable presses" requirement -- so each press needs a *fresh*
load of the module.

The first implementation tried here was exactly that: pop
``demo_square`` from ``sys.modules`` (if present) then re-``import``
it, or equivalently re-``exec()`` its ~13 KB raw ``.py`` source into a
fresh namespace on every press. **Bench-verified this ticket: both
forms fail identically on real hardware** -- compiling ~13 KB of raw
Python source at runtime exhausts this device's heap
(``MemoryError: memory allocation failed, allocating 6129 bytes``,
bench log) -- the target has nowhere near enough free RAM to run its
own compiler over a file that size on top of everything else already
resident (boot's comms/radio/diffdrive stack). The FIX, also
bench-verified: deploy a **precompiled** ``demo_square.mpy``
(``mpy-cross src/demo_square.py -o demo_square.mpy`` -- 2346 bytes,
versus 12947 bytes of raw source) instead of the ``.py`` source.
Loading precompiled bytecode needs no on-device compilation at all --
MicroPython's own import machinery resolves ``import demo_square``
against a ``.mpy`` file on the filesystem exactly like a ``.py`` one
(standard, port-wide behaviour, not specific to this repo). Popping
``demo_square`` from ``sys.modules`` before each import still forces a
fresh (re)execution of that (cheap-to-load) bytecode every press --
re-triggering ``demo_square``'s own top-level ``if _ON_DEVICE: run()``
each time -- but now at bytecode-load cost, not compile cost. This is
the root-cause fix, not a workaround: it is deployment FORMAT (source
vs. precompiled bytecode) that changes, not this file's own logic,
which is unchanged from the first attempt. See the bench log's own
section for the failing run's exact evidence.

**Why the fail-closed check does NOT use ``config.load_robot_config()``
-- bench-probed this session, not assumed**: zetuv's resident frozen
``config``/``boot`` Python modules were probed directly this session
(``docs/bench-log-zetuv-2026-08-19.md``, sprint 003 ticket 001
section) and found to be STALE STUBS on THIS image --
``dir(config)`` is only ``['__class__', '__name__']``,
``config.load_robot_config`` raises ``AttributeError``. This is a
real, disclosed finding, flagged in the bench log as out of this
ticket's scope to fix (this file's own job does not require a current
``config``/``boot`` -- ``demo_square`` already bypasses both, driving
``diffdrive`` directly with hardcoded geometry constants, per its own
module docstring, so it works regardless of ``config``'s state). The
fail-closed check here is therefore a light, self-contained probe:
``robot.json`` present and non-empty, and the ``diffdrive`` native
module importable -- exactly the two conditions this ticket's
acceptance criteria name ("no /robot.json / diffdrive refuses"),
without depending on the stale ``config`` module.

**Path convention -- bench-probed, not assumed**: ``src/boot.py``'s
own ``CONFIG_PATH`` constant is ``"/robot.json"`` (leading slash), but
probing directly on zetuv this session found ``open("/robot.json")``
and ``os.stat("/robot.json")`` BOTH raise ``OSError: ENOENT`` on this
port, while the bare relative form ``"robot.json"`` (no leading slash)
opens the exact same, already-present 2413-byte file successfully
(bench log). This is disclosed there as a real, separate finding for
whoever next touches ``boot.py``/``config.py`` -- out of scope to fix
here. This file uses the bare (no-leading-slash) form throughout, since
that is the form bench-confirmed to actually work on this device.

**Main-context discipline**: the idle loop below only ever polls
``button_a.was_pressed()`` and sleeps -- ``sleep()`` reaches
``microbit_hal_idle()``, keeping the kernel fiber fed (sprint 001
ticket 007's own student-facing API contract note, cited in this
ticket). Nothing here is driven from ``microbit.run_every()`` or any
other callback/IRQ context -- there is no callback registered by this
file at all. ``KeyboardInterrupt`` is never swallowed -- the one
``except Exception`` guard around the tour explicitly re-raises it
first, and the outer loop's own guard does the same.

**Verifying ``__name__`` semantics -- bench-confirmed, not assumed**:
``codal_port/main.c``'s ``microbit_pyexec_file()`` compiles and calls
the filesystem ``main.py`` as a bare function (``mp_call_function_0``),
not through the normal module-import path -- so whether ``__name__``
reads ``"__main__"`` in that context was not safe to assume (and
``src/demo_square.py``'s own ORIGINAL precedent -- before sprint 006
ticket 001 -- of using an explicit ``_ON_DEVICE`` flag rather than a
``__name__`` guard suggests this was an open question before too; that
module now uses a ``__name__`` guard of its own for a different reason
-- see its own module docstring's "Auto-run trigger" section). Verified
directly this session: a
throwaway diagnostic ``main.py`` that wrote ``__name__`` to a file on
boot confirmed ``__name__ == "__main__"`` in exactly this execution
context (bench log). ``run()`` below is therefore gated on
``if __name__ == "__main__":`` -- this fires at boot (the real
``__main__`` context) but NOT when this file's source is separately
``exec()``'d into a namespace with a different ``__name__`` for
REPL-driven verification (see the bench log's own verification
commands), so a verification exec of this whole file never re-enters
the infinite idle loop; the individual functions (``on_button_a()``
in particular) remain directly callable either way.

**Button B / 50 cm straight drive -- sprint 006 ticket 001**
(``clasi/sprints/006-zetuv-90mm-wheels-and-button-b-50cm-drive/``,
UC-003/UC-014), stakeholder directive live at the bench: "set the B
button to cause it to drive forward 50 cm". ``on_button_b()`` mirrors
``on_button_a()`` exactly (distinct display feedback -> drive ->
fault-guarded -> ``display.clear()``), except it shows ``Image.ARROW_E``
(a **distinct** indicator from button A's ``Image.HEART``, per this
ticket's own acceptance criteria) and calls ``run_straight_drive()``
instead of ``run_tour()``. ``run_straight_drive()`` uses the SAME
``sys.modules.pop(TOUR_MODULE_NAME, None) + import demo_square``
reload pattern ``run_tour()`` already uses (repeatable presses, same
reasoning as above), then explicitly calls
``demo_square.run_single_leg(STRAIGHT_DRIVE_DISTANCE_MM)`` -- the SAME
encoder-terminated, lease-refreshed straight-drive primitive
(``demo_square._run_segment()``) the square tour's own legs use,
reused rather than reimplemented (this ticket's own explicit
instruction; see ``src/demo_square.py``'s own module docstring,
"Single-leg entry point (button B)" section, for the shared
``_configure_and_start()``/``_leg_ticks()``/``_run_segment()`` pieces).

**Why ``run_tour()``/``run_straight_drive()`` now call
``demo_square.run()``/``demo_square.run_single_leg()`` EXPLICITLY,
rather than relying on import's own side effect** (this changed this
ticket, from the "import itself runs the tour" design described above
under "Why demo_square is deployed..."): ``demo_square`` now exposes
TWO distinct behaviours (the full tour, and a single leg), and a plain
``import`` statement cannot select between them -- see
``src/demo_square.py``'s own docstring, "Auto-run trigger changed"
section, for the full reasoning. Both functions below therefore import
then call their target function directly; this also means production
button behaviour does not depend on ``demo_square``'s own bottom
``__name__`` guard at all.

**Config-driven geometry -- both buttons automatically rescale, no
separate edit needed**: ``demo_square.py``'s own fresh per-press
re-import (unchanged mechanism, described above) now ALSO re-reads
``wheels.wheel_diameter_mm``/``wheels.ticks_per_rev`` from
``robot.json`` at each such reload (see that module's own "Config-driven
geometry" docstring section for the full rationale, including why this
does NOT go through ``config.load_robot_config()``) -- so both
``run_tour()``'s square-tour legs and ``run_straight_drive()``'s single
leg source the SAME geometry, automatically, on every press. This file
(``main.py``) itself reads no geometry -- ``robot_ready()``'s own
fail-closed probe (above) only checks ``robot.json`` presence/
non-emptiness, unchanged.

**Distance, bench-derived**: ``STRAIGHT_DRIVE_DISTANCE_MM = 500.0``
mirrors ``demo_square.LEG_DISTANCE_MM`` (also 500.0, unchanged since
sprint 002) -- at the fallback 90 mm wheel diameter this targets
``500.0 * demo_square.TICKS_PER_MM`` ~= 1724 ticks per wheel (~1.77
wheel revolutions; see ``data/zetuv.json``'s own updated ``_wheels_note``
for the derivation and the stakeholder's own calibration formula for
future iterations).
"""

import os
import sys

from microbit import Image, button_a, button_b, display, sleep

# See module docstring "Path convention" -- bare, no leading slash;
# the leading-slash form fails ENOENT on this port even though the
# same file opens fine under the bare form.
ROBOT_CONFIG_PATH = "robot.json"

# Deployed as docstring-stripped raw .py source, NOT a precompiled
# .mpy -- this firmware's MICROPY_PERSISTENT_CODE_LOAD is off, so it
# cannot load .mpy from the filesystem at all (sprint 003's own
# Constraint B finding, bench log); sprint 004's own deploy session
# (bench log Sec 27) independently confirmed the actually-deployed copy
# is stripped raw source, not the .mpy this comment originally claimed.
TOUR_MODULE_NAME = "demo_square"

# Sprint 006 ticket 001: exactly 500 mm commanded for button B -- see
# module docstring's "Button B / 50 cm straight drive" section.
STRAIGHT_DRIVE_DISTANCE_MM = 500.0

IDLE_POLL_MS = 150
FAULT_SHOW_MS = 1000
REFUSED_SHOW_MS = 600

# A slow single-pixel "breathing" pulse at the display's centre --
# proves the idle loop is alive (not merely a frozen static image),
# per this ticket's "user sees it's armed" requirement.
_BREATH_LEVELS = (1, 3, 5, 7, 9, 7, 5, 3)


def robot_ready():
    """Fail-closed probe -- see module docstring's own section on why
    this does not use ``config.load_robot_config()``. True only when
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
    """Fresh (re)import of ``demo_square`` on every call, then an
    EXPLICIT ``demo_square.run()`` call -- see module docstring's "Why
    ...  call ... EXPLICITLY" section for why this is no longer a bare
    ``import`` relying on its own auto-run side effect (sprint 006
    ticket 001: ``demo_square`` now exposes two behaviours, so the
    caller must say which one it wants). Popping first forces
    MicroPython to reload the module fresh (source, not bytecode --
    see ``TOUR_MODULE_NAME``'s own comment) so this also re-reads
    ``robot.json``'s current geometry every press (``demo_square.py``'s
    own "Config-driven geometry" docstring section). Raises whatever
    ``demo_square.run()`` raises; the caller (``on_button_a``) handles
    that."""
    import gc
    gc.collect()   # defragment: boot's resident firmware layer
                   # (comms/radio/wifi, live since the ujson fix)
                   # leaves the heap tight; collect before the
                   # module reload's contiguous allocations
    sys.modules.pop(TOUR_MODULE_NAME, None)
    import demo_square
    demo_square.run()


def run_straight_drive():
    """Sprint 006 ticket 001: button B's entry point -- same fresh-
    reload pattern as ``run_tour()`` (repeatable presses, current
    config-driven geometry every time), but calls
    ``demo_square.run_single_leg()`` instead of ``demo_square.run()`` --
    the SAME encoder-terminated, lease-refreshed straight-drive
    primitive the square tour's own legs use, reused rather than
    reimplemented (see module docstring's "Button B / 50 cm straight
    drive" section). Raises whatever ``demo_square.run_single_leg()``
    raises; the caller (``on_button_b``) handles that."""
    import gc
    gc.collect()   # defragment: boot's resident firmware layer
                   # (comms/radio/wifi, live since the ujson fix)
                   # leaves the heap tight; collect before the
                   # module reload's contiguous allocations
    sys.modules.pop(TOUR_MODULE_NAME, None)
    import demo_square
    demo_square.run_single_leg(STRAIGHT_DRIVE_DISTANCE_MM)


def on_button_a():
    """The button-A handler -- the exact function bench-verified
    directly via REPL (see the bench log) before the physical robot
    was handed back to the stakeholder for the real button press.

    Shows HEART immediately (the "it's working" feedback), then runs
    the tour, guarded so a tour fault shows SAD (with the error
    logged) rather than dying silently. ``KeyboardInterrupt`` is
    always re-raised, never swallowed, so Ctrl-C still reaches the
    REPL even if pressed mid-tour."""
    display.show(Image.HEART)
    try:
        run_tour()
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate broad catch;
        # see docstring -- a tour fault must show something on the
        # display, not die silently. KeyboardInterrupt is excluded
        # above, so Ctrl-C is never swallowed here.
        print("main: tour fault:", exc)
        display.show(Image.SAD)
        sleep(FAULT_SHOW_MS)
    display.clear()


def on_button_b():
    """Sprint 006 ticket 001: the button-B handler -- same shape as
    ``on_button_a()`` (distinct feedback -> drive -> fault-guarded ->
    clear), except it shows ``Image.ARROW_E`` (a display indicator
    **distinct** from button A's ``Image.HEART``, per this ticket's own
    acceptance criteria) and drives ``run_straight_drive()`` (a single
    500 mm leg) instead of the full square tour. ``KeyboardInterrupt``
    is always re-raised, never swallowed, same as ``on_button_a()``."""
    display.show(Image.ARROW_E)
    try:
        run_straight_drive()
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate broad catch;
        # see on_button_a()'s own comment -- same reasoning applies here.
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
    """Main-context loop: poll ``button_a.was_pressed()`` /
    ``button_b.was_pressed()`` + sleep, never a callback -- see module
    docstring's "Main-context discipline". ``robot_ready()`` is
    evaluated once at start (the filesystem/native-module state it
    checks does not change while this loop runs). Sprint 006 ticket
    001: button B polled the same way as button A, same
    ready/not-ready gating -- both checked every tick, both consume
    their own ``was_pressed()`` latch independently (microbit's own
    button API), so a same-tick double-press runs both handlers in
    sequence (A then B), not either being dropped."""
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
