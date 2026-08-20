#include "i2c_broker.h"

extern "C" {
#include "py/mphal.h"   // mp_hal_ticks_us()
#include "microbithal.h"  // microbit_hal_i2c_writeto/readfrom
}

#include "codal_fwd.h"  // codal::fiber_sleep(); forward-declare only,
                         // see codal_fwd.h

// write()/read() run from two execution contexts: the kernel's own
// CODAL fiber (Nezha traffic) and the main Python context
// (robotio.i2c_xfer()). A clearance wait uses codal::fiber_sleep()
// (safe from any fiber) rather than mp_hal_delay_ms(), whose loop
// touches MicroPython VM state that only the main-context fiber may
// touch.

namespace Native {

int I2cBroker::write(uint16_t address, uint8_t* data, int len, bool repeated,
                      uint32_t preClear, uint32_t postClear) {
  const uint8_t addr7 = static_cast<uint8_t>(address >> 1);
  waitForClearance(addr7, preClear);
  const int result = microbit_hal_i2c_writeto(addr7, data, len, !repeated);
  recordEnd(addr7, postClear);
  return result;
}

int I2cBroker::read(uint16_t address, uint8_t* data, int len, bool repeated,
                     uint32_t preClear, uint32_t postClear) {
  const uint8_t addr7 = static_cast<uint8_t>(address >> 1);
  waitForClearance(addr7, preClear);
  const int result = microbit_hal_i2c_readfrom(addr7, data, len, !repeated);
  recordEnd(addr7, postClear);
  return result;
}

void I2cBroker::waitForClearance(uint8_t addr7, uint32_t preClear) {
  const uint32_t preDeadline = devices_[addr7].lastEnd + preClear;
  uint32_t entryDeadline = devices_[addr7].readyAt;
  if (preDeadline > entryDeadline) {
    entryDeadline = preDeadline;
  }
  const uint32_t now = mp_hal_ticks_us();
  // Unsigned-wraparound-safe as int32_t as long as the gap stays under
  // ~35 minutes -- true for every clearance window this bus schedules.
  const int32_t remainingUs =
      static_cast<int32_t>(entryDeadline - now);
  if (remainingUs <= 0) {
    return;
  }
  ++clearanceSafetyNetCount_;
  const uint32_t shortfallMs =
      (static_cast<uint32_t>(remainingUs) + 999u) / 1000u;
  if (shortfallMs > 0) {
    codal::fiber_sleep(shortfallMs);
  }
}

void I2cBroker::recordEnd(uint8_t addr7, uint32_t postClear) {
  const uint32_t now = mp_hal_ticks_us();
  devices_[addr7].lastEnd = now;
  devices_[addr7].readyAt = now + postClear;
}

I2cBroker& I2cBroker::instance() {
  static I2cBroker broker;
  return broker;
}

}  // namespace Native
