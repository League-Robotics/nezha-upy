// wifi_stdio_hook.h -- Native::WifiStdioHook: the stdio TCP-REPL mirror
// bridge. Owns two small coalescing ring buffers (drop-oldest on
// overflow) and nothing else -- no AT dialogue, no +IPD parsing.
// wifi_at.py demuxes the AT link's own bytes and pushes/pulls through
// this surface once per pump tick.
//
// Lives under native/codal_app/ (copied by build.sh's --with-wifi step)
// so it can be patched into codal_app/mphalport.cpp's stdio HAL
// functions directly.
#pragma once

#include "wifi_uart_fwd.h"

namespace Native {

class WifiStdioHook {
 public:
  static WifiStdioHook& instance();

  void setActive(bool active) { active_ = active; }
  bool active() const { return active_; }

  // -- stdout capture (mp_hal_stdout_tx_strn -> wifi_at.py) ------------
  void captureStdout(const char* str, size_t len);
  size_t pullStdout(uint8_t* out, size_t cap);

  // -- stdin inject (wifi_at.py -> mp_hal_stdin_rx_chr) -----------------
  size_t pushStdin(const uint8_t* data, size_t len);
  bool stdinReadable() const { return stdin_.count != 0; }
  int stdinReadChr();

 private:
  static constexpr size_t kRingSize = 256;

  struct Ring {
    uint8_t buf[kRingSize] = {};
    size_t head = 0;
    size_t tail = 0;
    size_t count = 0;

    // Drop-oldest on overflow.
    size_t push(const uint8_t* data, size_t len) {
      size_t n = 0;
      for (; n < len; ++n) {
        if (count >= kRingSize) {
          tail = (tail + 1) % kRingSize;
          --count;
        }
        buf[head] = data[n];
        head = (head + 1) % kRingSize;
        ++count;
      }
      return n;
    }

    size_t pop(uint8_t* out, size_t cap) {
      size_t n = 0;
      while (n < cap && count > 0) {
        out[n++] = buf[tail];
        tail = (tail + 1) % kRingSize;
        --count;
      }
      return n;
    }
  };

  bool active_ = false;
  Ring stdout_;
  Ring stdin_;
  size_t& stdinCount_ = stdin_.count;
};

}  // namespace Native
