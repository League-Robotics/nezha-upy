// i2c_broker.h -- I2cBroker: the ONE shared Hal::I2CBus implementation for
// this image. Every I2C transaction on the device -- the kernel fiber's
// own Nezha (0x10) traffic AND every Python sensor read routed through
// robotio.i2c_xfer() -- goes through this SAME instance, so the
// per-device lastEnd/readyAt clearance ledger and the
// clearanceSafetyNetCount() (TWIM-errata gap) diagnostic are shared state,
// per spec Section 5 ("One I2C ledger").
//
// Pattern: reference/modrobot/modrobot.cpp's HalI2CBus (the Challenge-1
// fix documented in reference/vevov-micropython-spike-handoff.md -- a
// naive bus shim that ignored preClear/postClear caused flaky mixed
// sensor+motion runs). This is the same clearance-ledger algorithm,
// ported rather than re-derived, talking to the SAME microbit_hal_i2c_*
// primitives.
#pragma once

#include <cstdint>

#include "hal/i2c_bus.h"

namespace Native {

class I2cBroker final : public Hal::I2CBus {
 public:
  int write(uint16_t address, uint8_t* data, int len, bool repeated = false,
            uint32_t preClear = 0, uint32_t postClear = 0) override;
  int read(uint16_t address, uint8_t* data, int len, bool repeated = false,
           uint32_t preClear = 0, uint32_t postClear = 0) override;

  uint32_t clearanceSafetyNetCount() const override {
    return clearanceSafetyNetCount_;
  }

  // Singleton accessor -- ONE broker instance backs both the kernel
  // fiber's leaves (constructed at native init, before the VM starts) and
  // robotio.i2c_xfer() (called from Python). A function-local static
  // (not a global) so construction order relative to other native
  // globals is never in question.
  static I2cBroker& instance();

 private:
  // 32-bit ticks (mp_hal_ticks_us()) are enough here: every clearance
  // window this bus schedules is a few ms at most, far below the ~71-
  // minute wrap period, and the wait math is unsigned-wraparound-safe
  // (see waitForClearance()). The kernel's own DiffDrive::Clock port
  // (platform_ports.cpp) uses a real 64-bit extension instead, because
  // ITS age computations are not bounded the same way.
  struct DeviceState {
    uint32_t lastEnd = 0;   // [us]
    uint32_t readyAt = 0;   // [us]
  };

  void waitForClearance(uint8_t addr7, uint32_t preClear);
  void recordEnd(uint8_t addr7, uint32_t postClear);

  DeviceState devices_[128] = {};
  uint32_t clearanceSafetyNetCount_ = 0;
};

}  // namespace Native
