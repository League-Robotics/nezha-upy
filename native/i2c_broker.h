// i2c_broker.h -- I2cBroker: the one shared Hal::I2CBus implementation
// for this image. Every I2C transaction -- the kernel fiber's own Nezha
// (0x10) traffic and every Python sensor read via robotio.i2c_xfer() --
// goes through this same instance, so the per-device clearance ledger
// and the TWIM-errata diagnostic are shared state (spec Section 5, "One
// I2C ledger").
//
// Same clearance-ledger algorithm as reference/modrobot/modrobot.cpp's
// HalI2CBus, ported rather than re-derived, talking to the same
// microbit_hal_i2c_* primitives.
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

  // Singleton accessor -- one broker instance backs both the kernel
  // fiber's leaves and robotio.i2c_xfer(). A function-local static (not
  // a global) so construction order relative to other native globals is
  // never in question.
  static I2cBroker& instance();

 private:
  // 32-bit ticks are enough here: every clearance window is a few ms at
  // most, far below the ~71-minute wrap period. The kernel's own
  // DiffDrive::Clock port uses a real 64-bit extension instead, because
  // its age computations are not bounded the same way.
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
