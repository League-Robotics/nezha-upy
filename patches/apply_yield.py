#!/usr/bin/env python3
"""Apply the corrected microbit_hal_idle() yield patch.

Why this differs from patches/yield.patch's literal diff: that old fix
added `schedule()` directly inside `microbit_hal_background_processing()`
in microbithal.cpp. That function is ALSO called from this port's stock
(un-patched) MICROPY_VM_HOOK_POLL in mpconfigport.h, every ~64
bytecodes. Applying yield.patch's diff therefore puts a fiber-switching
schedule() call on a path reachable from INSIDE VM bytecode dispatch --
the heap-corruption landmine docs/design/specification.md Section 7.1
describes (CODAL's verify_stack_size() does malloc/free mid-switch,
corrupting the bytes under MicroPython's nlr_top chain / the GC's
conservative stack scan). Not hypothetical: this is the mechanism the
2026-08-18 review traces to the observed gopiv 2026-08-14
mp_obj_exception_add_traceback HardFault (reference/FINDINGS.md
Section 3b).

The fix applied here instead touches ONLY microbit_hal_idle() -- adding
fiber_sleep(1) + schedule() there, and nowhere else.
microbit_hal_background_processing() is left completely unmodified.
microbit_hal_idle()'s own callers (mp_hal_delay_ms()'s blocking-sleep
loop, drv_display.c, modmusic.c, modaudio.c) are ordinary nested C
calls during a single bytecode's execution, not inside the VM's
per-instruction dispatch hook or the GC's stack scan -- the exact
distinction spec Section 7.1 draws.

The "GC hook" half of the original two-part patch (a
MICROPY_GC_HOOK_LOOP that also ran background processing) stays
DELIBERATELY NOT applied, permanently: the kernel fiber only needs to
be woken from main-context idle(), never from inside a GC sweep.
"""
import os

base = os.path.join(os.path.dirname(__file__), "..", "micropython-microbit-v2", "src")
path = os.path.join(base, "codal_app", "microbithal.cpp")

OLD_IDLE = """void microbit_hal_idle(void) {
    microbit_hal_background_processing();
    __WFI();
}"""

NEW_IDLE = """void microbit_hal_idle(void) {
    // Cooperative yield to the kernel fiber (native/platform_ports.h's
    // FiberLauncher/Sleeper) -- the ONLY yield point in this image; see
    // this file's own module docstring for why it is scoped to exactly
    // this function and not to microbit_hal_background_processing()
    // (which the stock MICROPY_VM_HOOK_POLL also calls, and which must
    // therefore stay fiber-switch-free).
    codal::fiber_sleep(1);
    microbit_hal_background_processing();
}"""


def main():
    with open(path) as f:
        src = f.read()

    if "codal::fiber_sleep(1);\n    microbit_hal_background_processing();" in src:
        print("microbit_hal_idle(): corrected yield patch already applied")
        return

    if OLD_IDLE not in src:
        print(
            "WARNING: microbit_hal_idle() did not match the expected stock "
            "form -- yield patch NOT applied, patch this by hand"
        )
        return

    src = src.replace(OLD_IDLE, NEW_IDLE)
    with open(path, "w") as f:
        f.write(src)
    print("microbit_hal_idle(): corrected yield patch applied (idle() only, "
          "microbit_hal_background_processing() left untouched)")
    print("mpconfigport.h GC hook: deliberately not applied (see this "
          "file's module docstring) -- permanent, not a TODO")


if __name__ == "__main__":
    main()
