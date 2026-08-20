#include "platform_ports.h"

extern "C" {
#include "py/mphal.h"  // mp_hal_ticks_us()
}

#include "codal_fwd.h"  // codal::create_fiber/schedule/fiber_sleep;
                         // forward-declare only, see codal_fwd.h

namespace Native {

uint64_t PlatformClock::nowMicros() const {
  const uint32_t raw = mp_hal_ticks_us();
  if (!primed_) {
    primed_ = true;
    lastRaw_ = raw;
    epochBase_ = 0;
  } else if (raw < lastRaw_) {
    // Wrapped since last sample (32-bit us counter, ~71.5 min period);
    // polled every ~24 ms, so a wrap is never missed.
    epochBase_ += (1ull << 32);
  }
  lastRaw_ = raw;
  return epochBase_ + raw;
}

void PlatformSleeper::sleepMillis(uint32_t duration) {
  if (stepMode_) {
    mp_hal_delay_ms(duration);
  } else {
    codal::fiber_sleep(duration);
  }
}

void PlatformSleeper::yield() {
  // Unreachable in step mode today -- the kernel only calls yield() from
  // run()'s fiber loop (differential_drive.cpp:375), and step mode never
  // runs it. Branched anyway so the port stays correct if that changes.
  if (stepMode_) {
    mp_hal_delay_ms(1);
  } else {
    codal::schedule();
  }
}

namespace {
// Never actually invoked -- the kernel fiber's entry never returns
// (FiberLauncher::launch()'s documented contract). Exists only because
// codal::create_fiber() requires a completion callback argument.
void noopFiberCompletion(void*) {}
}  // namespace

void PlatformFiberLauncher::launch(void (*entry)(void*), void* context) {
  codal::create_fiber(entry, context, noopFiberCompletion);
}

}  // namespace Native
