#pragma once
#include <array>
#include <atomic>
#include <cmath>
#include <complex>
#include <cstdint>
#include <string>
#include <vector>

namespace eyesy {
constexpr size_t fftSize = 1024;
struct StereoFrame {
    float left = 0, right = 0;
};
// One producer and one consumer; never blocks the audio callback.
template <size_t Capacity> class AudioRing {
    std::array<StereoFrame, Capacity> data{};
    std::atomic<size_t> read{0}, write{0};

  public:
    std::atomic<uint64_t> dropped{0};
    bool push(StereoFrame frame) {
        auto w = write.load(std::memory_order_relaxed);
        auto next = (w + 1) % Capacity;
        if (next == read.load(std::memory_order_acquire)) {
            ++dropped;
            return false;
        }
        data[w] = frame;
        write.store(next, std::memory_order_release);
        return true;
    }
    bool pop(StereoFrame &frame) {
        auto r = read.load(std::memory_order_relaxed);
        if (r == write.load(std::memory_order_acquire))
            return false;
        frame = data[r];
        read.store((r + 1) % Capacity, std::memory_order_release);
        return true;
    }
};
struct Analysis {
    std::array<float, fftSize> left{}, right{};
    std::array<float, fftSize / 2 + 1> spectrumL{}, spectrumR{};
    std::array<float, 3> bands{};
    float peakL = 0, peakR = 0, rmsL = 0, rmsR = 0;
    double sampleRate = 48000, timestamp = 0;
    uint64_t sequence = 0, triggerCount = 0;
    bool available = false;
};
void spectrum(const std::array<float, fftSize> &input, std::array<float, fftSize / 2 + 1> &output);
Analysis analyze(const std::array<StereoFrame, fftSize> &input, double rate);
class TriggerDetector {
    float envelope = 0;
    double lastTrigger = -1000;
    bool armed = true;

  public:
    float threshold = .2f, releaseThreshold = .1f;
    double attack = .005, release = .08, holdoff = .12;
    bool update(float peak, double dt, double time);
};
struct Parameter {
    std::string name;
    double value = 0, minimum = 0, maximum = 1;
    int knob = -1;
    bool pickup = false;
    double previousKnob = 0;
    void restore(double v, double physicalKnob);
    void applyKnob(double normalized);
};
struct OscEvent {
    std::string address;
    std::vector<int32_t> integers;
    std::string text;
};
bool decodeOsc(const uint8_t *data, size_t size, OscEvent &result);
bool encodeOscInt(const std::string &address, int32_t value, std::vector<uint8_t> &out);
struct MidiEvent {
    int type = 0, channel = 0, a = 0, b = 0;
    double timestamp = 0;
};
class MidiState {
  public:
    std::array<int, 128> notes{};
    std::array<int, 128> cc{};
    uint64_t clocks = 0;
    bool playing = false;
    void apply(const MidiEvent &event);
};
} // namespace eyesy
