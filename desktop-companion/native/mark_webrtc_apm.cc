// Mark native AEC3 wrapper; build inside a compatible WebRTC checkout.
#include <algorithm>
#include <cstdint>
#include "rtc_base/scoped_ref_ptr.h"
#include "modules/audio_processing/include/audio_processing.h"
#include "api/environment/environment_factory.h"
#include "api/audio/builtin_audio_processing_builder.h"

#ifdef _WIN32
#define MARK_EXPORT extern "C" __declspec(dllexport)
#else
#define MARK_EXPORT extern "C"
#endif

struct MarkAPM {
  rtc::scoped_refptr<webrtc::AudioProcessing> apm;
  int delay_ms;
};

static rtc::scoped_refptr<webrtc::AudioProcessing> NewAPM() {
  auto apm = webrtc::BuiltinAudioProcessingBuilder().Build(webrtc::CreateEnvironment());
  if (!apm) return nullptr;
  webrtc::AudioProcessing::Config config;
  config.echo_canceller.enabled = true;
  config.high_pass_filter.enabled = true;
  apm->ApplyConfig(config);
  return apm;
}

MARK_EXPORT void* mark_apm_create(int delay_ms) {
  auto apm = NewAPM();
  if (!apm) return nullptr;
  return new MarkAPM{apm, std::clamp(delay_ms, 0, 500)};
}
MARK_EXPORT void mark_apm_destroy(void* ctx) {
  delete static_cast<MarkAPM*>(ctx);
}
MARK_EXPORT int mark_apm_reset(void* ctx) {
  if (!ctx) return -1;
  auto* state = static_cast<MarkAPM*>(ctx);
  auto fresh = NewAPM();
  if (!fresh) return -2;
  state->apm = fresh;
  return 0;
}
MARK_EXPORT int mark_apm_render(void* ctx, const void* pcm, int size) {
  if (!ctx || !pcm || size != 480) return -1;
  const auto* input = static_cast<const int16_t*>(pcm);
  int16_t render[480];
  for (int i = 0; i < 240; ++i) {
    render[2*i] = input[i];
    render[2*i+1] = static_cast<int16_t>(
        (int(input[i]) + int(input[std::min(i+1, 239)])) / 2);
  }
  auto* state = static_cast<MarkAPM*>(ctx);
  return state->apm->ProcessReverseStream(
      render, webrtc::StreamConfig(48000, 1),
      webrtc::StreamConfig(48000, 1), render);
}
MARK_EXPORT int mark_apm_capture(void* ctx, const void* pcm, void* out, int size) {
  if (!ctx || !pcm || !out || size != 320) return -1;
  auto* state = static_cast<MarkAPM*>(ctx);
  state->apm->set_stream_delay_ms(state->delay_ms);
  return state->apm->ProcessStream(
      static_cast<const int16_t*>(pcm),
      webrtc::StreamConfig(16000, 1),
      webrtc::StreamConfig(16000, 1),
      static_cast<int16_t*>(out));
}
