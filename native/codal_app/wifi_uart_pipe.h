// wifi_uart_pipe.h -- Native::WifiUartPipe: the raw UARTE1 byte-pipe
// shim. Byte-in/byte-out only -- no AT parsing (see
// native/wifi_uart_fwd.h).
//
// Lives under native/codal_app/ (copied by build.sh's --with-wifi step)
// because it needs full CODAL access (NRF52Serial, uBit.io.*) that
// native/codal_fwd.h's plain-Makefile build does not provide.
#pragma once

#include "wifi_uart_fwd.h"

namespace Native {

// Raw byte pipe over the module's UARTE1 link. Non-blocking,
// main-context-only -- never called from a VM/GC hook.
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

  // Staged-read buffer: refill from the UARTE's RX ring in bursts, serve
  // one byte at a time from here between refills.
  static constexpr size_t kStageBuffer = 128;
  uint8_t stage_[kStageBuffer] = {};
  int stageLen_ = 0;
  int stagePos_ = 0;
};

}  // namespace Native
