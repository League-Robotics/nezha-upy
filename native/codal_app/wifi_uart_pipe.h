// wifi_uart_pipe.h -- Native::WifiUartPipe: the raw UARTE1 byte-pipe
// shim (ticket 006, M4). See native/wifi_uart_fwd.h for the split of
// responsibility (this file is byte-in/byte-out ONLY -- no AT parsing).
//
// Lives under native/codal_app/ (copied by build.sh's --with-wifi step
// into micropython-microbit-v2/src/codal_app/, the CMake-driven CODAL
// build) rather than native/ proper, because it needs full CODAL access
// (NRF52Serial, uBit.io.*) that native/codal_fwd.h's own header
// documents codal_port's plain Makefile build does NOT provide.
// reference/modrobot/wifi_stdio.cpp already established this exact
// codal_app/ placement for the same reason.
#pragma once

#include "wifi_uart_fwd.h"

namespace Native {

// Raw byte pipe over the module's UARTE1 link. Non-blocking, main-
// context-only (the scheduled pump, via wifi_at.py's calls into the
// wifiuart MicroPython module) -- never called from a VM/GC hook.
class WifiUartPipe {
 public:
  static WifiUartPipe& instance();

  void init(uint32_t baudRateHz);
  size_t write(const uint8_t* data, size_t len);
  size_t any();
  size_t read(uint8_t* out, size_t cap);

 private:
  void refillStage();

  bool started_ = false;

  // Staged-read buffer -- mirrors wifi_stdio.cpp's own nextByte()
  // pattern: refill from the UARTE's RX ring in bursts, serve one byte
  // at a time from here in between refills.
  static constexpr size_t kStageBuffer = 128;
  uint8_t stage_[kStageBuffer] = {};
  int stageLen_ = 0;
  int stagePos_ = 0;
};

}  // namespace Native
