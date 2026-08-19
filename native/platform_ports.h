// platform_ports.h -- the three small DiffDrive:: ports differential_drive.h
// asks a host platform to implement (Motor is the fourth; see
// nezha_leaf.h). Each is a thin, direct wrapper over a CODAL/MicroPython
// primitive -- no logic of its own.
#pragma once

#include <cstdint>

#include "../vendor/differential_drive.h"

namespace Native {

// DiffDrive::Clock -- monotonic microseconds. mp_hal_ticks_us() itself
// wraps at 2^32 us (~71.5 min); this extends it to a real uint64_t
// monotonic count by tracking wraps across calls. Single instance, polled
// every kernel cycle (~24 ms) -- far more often than the wrap period, so
// a wrap is never missed.
class PlatformClock final : public DiffDrive::Clock {
 public:
  uint64_t nowMicros() const override;

 private:
  // mutable: nowMicros() is logically const (a Clock port reads time, it
  // does not mutate caller-visible state) but must remember the last raw
  // sample to detect a wrap.
  mutable uint32_t lastRaw_ = 0;
  mutable uint64_t epochBase_ = 0;
  mutable bool primed_ = false;
};

// DiffDrive::Sleeper -- settle/pace sleeps + cooperative yield, over CODAL
// fiber_sleep()/schedule(). ONLY ever called from the kernel's own fiber
// (DifferentialDrive::run(), via FiberLauncher::launch() below) -- never
// from the VM hook or GC hook. That is precisely the boundary
// docs/design/specification.md Section 7.1 draws: a fiber calling
// fiber_sleep()/schedule() on ITS OWN stack is the normal, safe CODAL
// cooperative-multitasking pattern; the landmine is a fiber SWITCH
// triggered from inside VM bytecode dispatch or the GC stack scan, which
// this class never does (it is never invoked from either).
class PlatformSleeper final : public DiffDrive::Sleeper {
 public:
  void sleepMillis(uint32_t duration) override;  // [ms]
  void yield() override;
};

// DiffDrive::FiberLauncher -- starts the kernel loop on its own CODAL
// fiber via create_fiber(). Fails loudly (never used by this port, since
// the kernel calls start()) rather than silently no-op'ing if a
// miswired composition ever calls launch() without going through start().
class PlatformFiberLauncher final : public DiffDrive::FiberLauncher {
 public:
  void launch(void (*entry)(void*), void* context) override;
};

}  // namespace Native
