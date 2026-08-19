// nezha_leaf.h -- NezhaLeaf: the DiffDrive::Motor port implementation for
// this platform, composing the VENDORED (never edited) NezhaMotor wrapped
// in the VENDORED MotorArmor decorator.
//
// differential_drive.h's own file header says the kernel is "deliberately
// NOT derived from any firmware HAL" and that "a MicroPython C module
// implements the same four ports against its own platform instead" --
// this class is that adapter for the Motor port specifically. It is a
// ONE-LINE FORWARDING adapter (differential_drive.h's own phrase for this
// exact pattern) from Hal::Motor's surface onto DiffDrive::Motor's
// narrower surface: every method vendor/nezha_motor.{h,cpp} +
// vendor/motor_armor.h already implement and test is reused unedited;
// nothing here re-derives the anti-latch write shaping, the split-phase
// encoder protocol, or the wedge-detection policy.
//
// DiffDrive::Motor has no setNeutral()/reconfigure()/resetPosition()/
// setForcedWedge() -- the kernel never calls them, so this adapter simply
// never forwards them. wedged()/wedgeSuspect() forward to the armor's
// real wedge-latch state (this platform HAS the failure mode, unlike the
// "no armor" case differential_drive.h's own port doc allows for).
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
  // config: port + fwdSign + write-shaping fields for this one channel
  // (left_port/right_port/fwd_sign_* land here, per this ticket's scope --
  // see native/README.md). broker: the ONE shared I2cBroker instance
  // (i2c_broker.h) -- never a private bus per leaf.
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
