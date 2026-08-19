#include "platform_ports.h"

extern "C" {
#include "py/mphal.h"  // mp_hal_ticks_us()
}

#include "codal_fwd.h"  // codal::create_fiber/schedule/fiber_sleep --
                         // see codal_fwd.h's own header for why this is
                         // a forward-declare header, not "main.h"

namespace Native {

uint64_t PlatformClock::nowMicros() const {
  const uint32_t raw = mp_hal_ticks_us();
  if (!primed_) {
    primed_ = true;
    lastRaw_ = raw;
    epochBase_ = 0;
  } else if (raw < lastRaw_) {
    // Wrapped since the last sample (mp_hal_ticks_us() is a 32-bit
    // microsecond counter, ~71.5 min period). Polled every kernel cycle
    // (~24 ms), so a wrap is never missed between samples.
    epochBase_ += (1ull << 32);
  }
  lastRaw_ = raw;
  return epochBase_ + raw;
}

void PlatformSleeper::sleepMillis(uint32_t duration) {
  codal::fiber_sleep(duration);
}

void PlatformSleeper::yield() {
  codal::schedule();
}

namespace {
// The kernel fiber's entry (DifferentialDrive::run(), reached via this
// launcher) never returns -- "entry never returns" is differential_drive.h's
// own documented contract for FiberLauncher::launch(). This completion
// callback is therefore never actually invoked; it exists only because
// codal::create_fiber() takes one explicitly (codal_fwd.h's forward
// declaration has no default value to fall back on -- see its own file
// header for why it is declared without one).
void noopFiberCompletion(void*) {}
}  // namespace

void PlatformFiberLauncher::launch(void (*entry)(void*), void* context) {
  codal::create_fiber(entry, context, noopFiberCompletion);
}

}  // namespace Native
