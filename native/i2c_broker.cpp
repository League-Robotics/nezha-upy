#include "i2c_broker.h"

extern "C" {
#include "py/mphal.h"   // mp_hal_ticks_us()
#include "microbithal.h"  // microbit_hal_i2c_writeto/readfrom
}

#include "codal_fwd.h"  // codal::fiber_sleep() -- see codal_fwd.h's own
                         // header for why this is a forward-declare
                         // header, not "main.h"

// Both write()/read() may run on TWO different execution contexts: the
// kernel's own CODAL fiber (Nezha 0x10 traffic, NezhaMotor::tick() et al)
// and the main Python execution context (robotio.i2c_xfer(), a plain
// builtin call). A clearance wait therefore uses codal::fiber_sleep()
// (a bare CODAL primitive, safe from any fiber, exactly what the
// microbit_hal_idle() yield patch already relies on) rather than
// mp_hal_delay_ms(), whose loop calls mp_handle_pending() -- MicroPython
// VM/exception-scheduling state that must not be touched from a fiber
// other than the one MicroPython itself is running on.

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
  // Unsigned wraparound-safe: (entryDeadline - now) as int32_t is correct
  // as long as the actual gap never exceeds ~35 minutes, true for every
  // clearance window this bus ever schedules (postClear tops out at a few
  // ms).
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
