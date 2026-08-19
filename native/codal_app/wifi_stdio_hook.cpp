#include "wifi_stdio_hook.h"

namespace Native {

WifiStdioHook& WifiStdioHook::instance() {
  static WifiStdioHook hook;
  return hook;
}

void WifiStdioHook::captureStdout(const char* str, size_t len) {
  if (!active_ || len == 0) return;
  stdout_.push(reinterpret_cast<const uint8_t*>(str), len);
}

size_t WifiStdioHook::pullStdout(uint8_t* out, size_t cap) {
  return stdout_.pop(out, cap);
}

size_t WifiStdioHook::pushStdin(const uint8_t* data, size_t len) {
  return stdin_.push(data, len);
}

int WifiStdioHook::stdinReadChr() {
  uint8_t c = 0;
  if (stdin_.pop(&c, 1) != 1) return -1;
  return static_cast<int>(c);
}

}  // namespace Native

// -- extern "C" surface (native/wifi_uart_fwd.h) -------------------------
extern "C" {

void wifiStdioSetActive(int active) {
  Native::WifiStdioHook::instance().setActive(active != 0);
}

int wifiStdioActive(void) {
  return Native::WifiStdioHook::instance().active() ? 1 : 0;
}

size_t wifiStdioStdinPush(const uint8_t* data, size_t len) {
  return Native::WifiStdioHook::instance().pushStdin(data, len);
}

size_t wifiStdioStdoutPull(uint8_t* out, size_t cap) {
  return Native::WifiStdioHook::instance().pullStdout(out, cap);
}

int wifiStdioStdinReadable(void) {
  return Native::WifiStdioHook::instance().stdinReadable() ? 1 : 0;
}

int wifiStdioStdinReadChr(void) {
  return Native::WifiStdioHook::instance().stdinReadChr();
}

void wifiStdioCaptureStdout(const char* str, size_t len) {
  Native::WifiStdioHook::instance().captureStdout(str, len);
}

}  // extern "C"
