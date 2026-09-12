#include "core.h"
#include "input_workflow.h"
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <limits>
#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::cerr << __LINE__ << ": " #x "\n";                                                 \
            std::exit(1);                                                                          \
        }                                                                                          \
    } while (0)
int main() {
    using namespace eyesy;
    AudioRing<4> ring;
    StereoFrame f;
    CHECK(!ring.pop(f));
    CHECK(ring.push({1, 2}));
    CHECK(ring.push({3, 4}));
    CHECK(ring.push({5, 6}));
    CHECK(!ring.push({7, 8}));
    CHECK(ring.dropped == 1);
    CHECK(ring.pop(f) && f.left == 1 && f.right == 2);
    CHECK(ring.push({7, 8}));
    CHECK(ring.pop(f) && f.left == 3);
    CHECK(ring.pop(f) && f.left == 5);
    CHECK(ring.pop(f) && f.right == 8);
    CHECK(!ring.pop(f));
    std::array<StereoFrame, fftSize> samples{};
    for (size_t i = 0; i < fftSize; ++i)
        samples[i].left = std::sin(2 * 3.141592653589793 * 32 * i / fftSize) * .5;
    auto a = analyze(samples, 48000);
    auto bin = std::max_element(a.spectrumL.begin(), a.spectrumL.end()) - a.spectrumL.begin();
    CHECK(bin == 32);
    CHECK(std::abs(a.spectrumL[32] - .5) < .002);
    CHECK(a.peakR == 0 && a.rmsR == 0);
    CHECK(std::abs(a.rmsL - std::sqrt(.125)) < .001);
    CHECK(a.bands[1] > a.bands[0]);
    CHECK(!analyze(samples, 0).available);
    TriggerDetector t;
    CHECK(t.update(1, .02, 0));
    CHECK(!t.update(1, .02, .02));
    for (int i = 0; i < 50; ++i)
        t.update(0, .02, .04 + i * .02);
    CHECK(t.update(1, .02, 1.1));
    Parameter p{"speed", .7, 0, 1, 0};
    p.restore(.7, .1);
    p.applyKnob(.2);
    CHECK(p.value == .7);
    p.applyKnob(.8);
    CHECK(!p.pickup && p.value == .8);
    p.applyKnob(std::numeric_limits<double>::quiet_NaN());
    CHECK(p.value == .8);
    const uint8_t osc[] = {'/', 'k', 'e', 'y', 0, 0,  0, 0, ',', 'i',
                           'i', 0,   0,   0,   0, 10, 0, 0, 0,   1};
    OscEvent event;
    CHECK(decodeOsc(osc, sizeof(osc), event));
    CHECK(event.integers[0] == 10);
    for (size_t n = 0; n < sizeof(osc); ++n)
        CHECK(!decodeOsc(osc, n, event));
    MidiState m;
    m.apply({0x90, 0, 60, 100});
    CHECK(m.notes[60] == 100);
    m.apply({0x90, 0, 60, 0});
    CHECK(m.notes[60] == 0);
    m.apply({0x90, 0, 64, 100});
    m.apply({0xb0, 0, 123, 0});
    CHECK(m.notes[64] == 0);
    m.apply({0xfa});
    m.apply({0xf8});
    CHECK(m.playing && m.clocks == 1);
    m.apply({0xfc});
    CHECK(!m.playing);
    InputRecorder recorder(2);
    CHECK(recorder.record({0, "knob", 1, 0, 0, 0, 0, 0, .5}));
    CHECK(recorder.record({1, "key", 0, 32}));
    CHECK(!recorder.record({2, "midi", 0, 0, 0x90, 0, 60, 1, 0}));
    CHECK(recorder.truncated() && recorder.size() == 2);
    std::string error;
    CHECK(!validReplayEvent({0, "knob", 6, 0, 0, 0, 0, 0, .5}, error));
    CHECK(!error.empty());
    std::cout << "audio, FFT, trigger, pickup, OSC, MIDI checks passed\n";
}
