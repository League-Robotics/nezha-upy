// motor.h -- Hal::Motor, the pure abstract base vendor/nezha_motor.h and
// vendor/motor_armor.h are both written against (`class NezhaMotor :
// public Hal::Motor`, `class MotorArmor : public Hal::Motor`).
//
// Reverse-engineered from the union of both files' `override` lists,
// not copied from radio-robot's current (already-diverged)
// src/firm/hal/motor.h -- see device_types.h.
//
// wedged()/wedgeSuspect() default false and setForcedWedge() defaults
// to a no-op (neither vendored override provides them); every other
// method is pure virtual.
#pragma once

#include <cstdint>

#include "hal/device_config.h"
#include "hal/device_types.h"

namespace Hal {

class Motor {
 public:
  virtual ~Motor() = default;

  virtual void begin() = 0;
  virtual void requestSample() = 0;

  // --- Command staging -- tick() executes. ---
  virtual void setDuty(float duty) = 0;         // [-1, 1] raw duty
  virtual void setNeutral(Neutral mode) = 0;

  // Immediate, unstaged zero -- must not wait for a tick() that may
  // never come.
  virtual void emergencyStop() = 0;

  // Guarded whole-config replacement: refuses (returns false, leaves
  // config unchanged) unless the motor has never been commanded or is
  // independently verified at rest.
  [[nodiscard]] virtual bool reconfigure(const MotorConfig& config) = 0;

  virtual void tick(uint64_t nowUs) = 0;   // [us]

  // DBG fault injection -- default no-op; only MotorArmor overrides it.
  virtual void setForcedWedge(bool) {}

  // --- Getters ---
  virtual float position() const = 0;        // [counts] (counts-native leaf)
  virtual float velocity() const = 0;         // [counts/s] signed
  virtual float appliedDuty() const = 0;      // [-1, 1] last landed write
  virtual bool connected() const = 0;
  virtual uint64_t sampleTime() const = 0;    // [us] last SUCCESSFUL collect

  // --- Resets ---
  virtual void resetPosition() = 0;   // hard -- bus-touching, immediate
  virtual void rebaseline() = 0;      // software-only re-anchor

  // --- Observability -- armor-provided; a bare motor reports false. ---
  virtual bool wedged() const { return false; }
  virtual bool wedgeSuspect() const { return false; }
};

}  // namespace Hal
