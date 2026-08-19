// i2c_bus.h -- Hal::I2CBus, the pure abstract interface
// vendor/nezha_motor.cpp calls through (bus_.write()/bus_.read()).
// Signature reverse-engineered from every call site in nezha_motor.cpp:
// all four calls pass (address, data, len, repeated, preClear, postClear)
// or a prefix of it, so preClear/postClear must default to 0. See
// device_types.h's file header for why this lives in native/, not
// vendor/.
//
// The concrete implementation is I2cBroker (native/i2c_broker.h) -- the
// ONE I2C ledger this ticket's ports.md/spec require: every Python sensor
// transaction (robotio.i2c_xfer()) and every kernel-fiber Nezha
// transaction go through the same instance, so the per-device
// lastEnd/readyAt clearance timers and the TWIM-errata gap are shared
// state, not two independent bookkeeping copies that can each think the
// bus is clear when it isn't.
#pragma once

#include <cstdint>

namespace Hal {

class I2CBus {
 public:
  virtual ~I2CBus() = default;

  // address: 8-bit wire address (7-bit addr << 1), as every caller in this
  // codebase already passes it (matches vendor/nezha_motor.cpp's
  // `kNezhaDeviceAddr << 1` call sites). Returns a CODAL-style status int
  // (0 == success).
  //
  // preClear/postClear [us]: per-device clearance timers the CONCRETE
  // class enforces before/after a transaction -- see I2cBroker.
  virtual int write(uint16_t address, uint8_t* data, int len,
                     bool repeated = false, uint32_t preClear = 0,
                     uint32_t postClear = 0) = 0;
  virtual int read(uint16_t address, uint8_t* data, int len,
                    bool repeated = false, uint32_t preClear = 0,
                    uint32_t postClear = 0) = 0;

  // Total count of transactions that arrived before their device's
  // clearance deadline and had to wait for it -- should be near-zero if
  // the caller's own cadence is honest. Exposed to Python for
  // observability (robotio.i2c_xfer() stats), not consumed by the kernel.
  virtual uint32_t clearanceSafetyNetCount() const = 0;
};

}  // namespace Hal
