#include "wifi_uart_pipe.h"

#include "main.h"

namespace Native {
namespace {

// Fixed WiFi jack: TX=P8, RX=P1. A runtime-selectable jack is future
// work if a different robot's wiring needs it.
NRF52Serial g_uart(uBit.io.P8, uBit.io.P1, NRF_UARTE1);

}  // namespace

WifiUartPipe& WifiUartPipe::instance() {
  static WifiUartPipe pipe;
  return pipe;
}

void WifiUartPipe::init(uint32_t baudRateHz) {
  if (started_) return;
  started_ = true;
  g_uart.setRxBufferSize(250);
  g_uart.setTxBufferSize(250);
  g_uart.setBaudrate(baudRateHz);
}

size_t WifiUartPipe::write(const uint8_t* data, size_t len) {
  if (!started_ || len == 0) return 0;
  // Non-blocking: queues as many bytes as fit the TX buffer right now.
  // Never busy-waits or schedule()s -- the caller (wifi_at.py's pump)
  // retries any remainder next tick.
  const int space = 250 - g_uart.txBufferedSize();
  if (space <= 0) return 0;
  size_t take = len;
  if (take > static_cast<size_t>(space)) {
    take = static_cast<size_t>(space);
  }
  g_uart.send(const_cast<uint8_t*>(data), static_cast<int>(take), ASYNC);
  return take;
}

void WifiUartPipe::refillStage() {
  if (stagePos_ < stageLen_) return;
  const int n = g_uart.read(stage_, static_cast<int>(kStageBuffer), ASYNC);
  stageLen_ = n > 0 ? n : 0;
  stagePos_ = 0;
}

size_t WifiUartPipe::any() {
  if (!started_) return 0;
  refillStage();
  return static_cast<size_t>(stageLen_ - stagePos_);
}

size_t WifiUartPipe::read(uint8_t* out, size_t cap) {
  if (!started_ || cap == 0) return 0;
  size_t n = 0;
  while (n < cap) {
    refillStage();
    if (stagePos_ >= stageLen_) break;
    out[n++] = stage_[stagePos_++];
  }
  return n;
}

}  // namespace Native

// -- extern "C" surface (native/wifi_uart_fwd.h) -------------------------
extern "C" {

void wifiUartInit(uint32_t baudRateHz) {
  Native::WifiUartPipe::instance().init(baudRateHz);
}

size_t wifiUartWrite(const uint8_t* data, size_t len) {
  return Native::WifiUartPipe::instance().write(data, len);
}

size_t wifiUartAny(void) {
  return Native::WifiUartPipe::instance().any();
}

size_t wifiUartRead(uint8_t* out, size_t cap) {
  return Native::WifiUartPipe::instance().read(out, cap);
}

}  // extern "C"
