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

// DiffDrive::Sleeper -- settle/pace sleeps + cooperative yield. Mode-aware:
// fiber mode (default) uses CODAL fiber_sleep()/schedule(), called only
// from the kernel's own fiber (via FiberLauncher below) -- a fiber switch
// triggered from VM bytecode dispatch or the GC stack scan is the landmine
// this path never touches (see watchdog.h). Step mode uses
// mp_hal_delay_ms(), called from main context by diffdrive.step() -- this
// reaches microbit_hal_idle() so the comms pump runs during a settle.
// stepMode_ is set once, at mode-latch time (moddiffdrive.cpp), never
// after; fiber-mode behavior is therefore unchanged from before this mode
// existed.
class PlatformSleeper final : public DiffDrive::Sleeper {
 public:
  void sleepMillis(uint32_t duration) override;  // [ms]
  void yield() override;

  void setStepMode(bool stepMode) { stepMode_ = stepMode; }

 private:
  bool stepMode_ = false;  // false = fiber mode (default, unchanged)
};

// DiffDrive::FiberLauncher -- starts the kernel loop on its own CODAL
// fiber via create_fiber(). Fails loudly rather than silently no-op'ing
// if launch() is ever called without going through start().
class PlatformFiberLauncher final : public DiffDrive::FiberLauncher {
 public:
  void launch(void (*entry)(void*), void* context) override;
};

}  // namespace Native
