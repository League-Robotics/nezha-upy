// codal_fwd.h -- forward declarations for the CODAL fiber-scheduler
// calls this module uses, without pulling in CodalFiber.h/MicroBit.h:
// native/*.cpp builds under codal_port's plain Makefile, which lacks
// CODAL's include dirs (those exist only on the separate CMake build
// that compiles codal_app/*.cpp) -- resolved at link time instead.
// Signatures copied from codal-core/inc/core/CodalFiber.h.
#pragma once

namespace codal {
void schedule();
void fiber_sleep(unsigned long t);
struct Fiber;  // opaque here
Fiber* create_fiber(void (*entry_fn)(void*), void* param,
                     void (*completion_fn)(void*));
}  // namespace codal
