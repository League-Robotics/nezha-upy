// i2c_bus.h -- Hal::I2CBus, the pure abstract interface
// vendor/nezha_motor.cpp calls through. preClear/postClear default to
// 0 (reverse-engineered from call sites). See device_types.h for why
// this lives in native/, not vendor/.
//
// I2cBroker (native/i2c_broker.h) is the concrete, one-and-only
// implementation -- every Python sensor transaction and kernel-fiber
// Nezha transaction share its clearance-timer/TWIM-errata state.
#pragma once

#include <cstdint>

namespace Hal {

class I2CBus {
 public:
  virtual ~I2CBus() = default;

  // address: 8-bit wire address (7-bit addr << 1); returns a
  // CODAL-style status int (0 == success). preClear/postClear [us]:
  // per-device clearance timers I2cBroker enforces before/after.
  virtual int write(uint16_t address, uint8_t* data, int len,
                     bool repeated = false, uint32_t preClear = 0,
                     uint32_t postClear = 0) = 0;
  virtual int read(uint16_t address, uint8_t* data, int len,
                    bool repeated = false, uint32_t preClear = 0,
                    uint32_t postClear = 0) = 0;

  // Count of transactions that arrived before their device's clearance
  // deadline and had to wait -- exposed to Python for observability.
  virtual uint32_t clearanceSafetyNetCount() const = 0;
};

}  // namespace Hal
