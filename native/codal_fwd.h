// codal_fwd.h -- forward declarations for the narrow slice of CODAL's
// fiber scheduler this module calls, WITHOUT including CodalFiber.h or
// MicroBit.h.
//
// native/*.cpp compiles under codal_port's Makefile (MicroPython's own
// build -- see codal_port/Makefile's INC list), which does NOT carry
// CODAL's library include directories; those exist only on the SEPARATE
// CMake-driven build that compiles codal_app/*.cpp (confirmed the hard
// way: `#include "main.h"` from native/ resolved to codal_app/main.h,
// whose own `#include "MicroBit.h"` then failed to resolve at all under
// codal_port's include path).
//
// reference/modrobot/modrobot.cpp already established this exact
// pattern for the same reason (forward-declaring
// codal::microbit_serial_number()/microbit_friendly_name() instead of
// including MicroBitDevice.h, with its own comment explaining why) --
// ported here, not re-derived. Pulling CODAL's full header stack into
// MicroPython's own build risks macro/type collisions between the two
// codebases' config systems and isn't needed for three plain function
// declarations, resolved at LINK time against the real codal-core
// library already built into this image.
//
// Signatures copied verbatim from
// lib/codal/libraries/codal-core/inc/core/CodalFiber.h (fetched by
// build.sh Step 1b; not vendored source, not edited here).
#pragma once

namespace codal {
void schedule();
void fiber_sleep(unsigned long t);
struct Fiber;  // opaque here -- this module never dereferences one
Fiber* create_fiber(void (*entry_fn)(void*), void* param,
                     void (*completion_fn)(void*));
}  // namespace codal
