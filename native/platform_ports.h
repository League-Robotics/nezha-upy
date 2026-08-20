// platform_ports.h -- the three small DiffDrive:: ports
// differential_drive.h asks a host platform to implement (Motor is the
// fourth; see nezha_leaf.h). Each is a thin, direct wrapper over a
// CODAL/MicroPython primitive -- no logic of its own.
#pragma once

#include <cstdint>

#include "../vendor/differential_drive.h"

namespace Native {

// DiffDrive::Clock -- monotonic microseconds, extending
// mp_hal_ticks_us()'s 32-bit wrap (~71.5 min) to a real uint64_t by
// tracking wraps; polled every ~24 ms cycle, so a wrap is never missed.
class PlatformClock final : public DiffDrive::Clock {
 public:
  uint64_t nowMicros() const override;

 private:
  // mutable: nowMicros() is logically const but must remember the last
  // raw sample to detect a wrap.
  mutable uint32_t lastRaw_ = 0;
  mutable uint64_t epochBase_ = 0;
  mutable bool primed_ = false;
};

// DiffDrive::Sleeper -- settle/pace sleeps + cooperative yield, over
// CODAL fiber_sleep()/schedule(). FIBER-ONLY: called only from the
// kernel's own fiber (via FiberLauncher below), never the VM or GC hook
// -- a fiber switch triggered from VM bytecode dispatch or the GC stack
// scan is the landmine this class never touches (see watchdog.h).
class PlatformSleeper final : public DiffDrive::Sleeper {
 public:
  void sleepMillis(uint32_t duration) override;  // [ms]
  void yield() override;
};

// DiffDrive::FiberLauncher -- starts the kernel loop on its own CODAL
// fiber via create_fiber(). Fails loudly rather than silently no-op'ing
// if launch() is ever called without going through start().
class PlatformFiberLauncher final : public DiffDrive::FiberLauncher {
 public:
  void launch(void (*entry)(void*), void* context) override;
};

}  // namespace Native
