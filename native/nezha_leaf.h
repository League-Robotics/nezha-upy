// nezha_leaf.h -- NezhaLeaf: the DiffDrive::Motor port implementation
// for this platform, composing the vendored NezhaMotor wrapped in the
// vendored MotorArmor decorator. A one-line forwarding adapter from
// Hal::Motor's surface onto DiffDrive::Motor's narrower surface -- every
// method is reused unedited from vendor/nezha_motor.{h,cpp} +
// vendor/motor_armor.h.
//
// DiffDrive::Motor has no setNeutral()/reconfigure()/resetPosition()/
// setForcedWedge(), so those are simply never forwarded.
// wedged()/wedgeSuspect() forward to the armor's real wedge-latch state.
#pragma once

#include <cstdint>

#include "../vendor/differential_drive.h"
#include "../vendor/motor_armor.h"
#include "hal/device_config.h"
#include "hardware/nezha/nezha_motor.h"
#include "i2c_broker.h"

namespace Native {

class NezhaLeaf final : public DiffDrive::Motor {
 public:
  // config: port + fwdSign + write-shaping fields for this channel.
  // broker: the one shared I2cBroker instance -- never a private bus
  // per leaf.
  NezhaLeaf(I2cBroker& broker, const Hal::MotorConfig& config)
      : inner_(broker, config), armor_(inner_) {}

  void begin() override { armor_.begin(); }
  void requestSample() override { armor_.requestSample(); }
  void setDuty(float duty) override { armor_.setDuty(duty); }
  void emergencyStop() override { armor_.emergencyStop(); }
  void tick(uint64_t nowUs) override { armor_.tick(nowUs); }

  float position() const override { return armor_.position(); }
  float velocity() const override { return armor_.velocity(); }
  float appliedDuty() const override { return armor_.appliedDuty(); }
  bool connected() const override { return armor_.connected(); }
  uint64_t sampleTime() const override { return armor_.sampleTime(); }

  void rebaseline() override { armor_.rebaseline(); }

  bool wedged() const override { return armor_.wedged(); }
  bool wedgeSuspect() const override { return armor_.wedgeSuspect(); }

 private:
  Hardware::NezhaMotor inner_;
  Hardware::MotorArmor armor_;
};

}  // namespace Native
