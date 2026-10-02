// SPDX-License-Identifier: BSD-3-Clause
#include "core.h"
#include "input_workflow.h"
#include "knob_sequencer.h"
#include "palette_manager.h"
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
    std::vector<uint8_t> led;
    CHECK(encodeOscInt("/led", 7, led));
    CHECK(led.size() == 16 && led[4] == 0 && led[8] == ',' && led[9] == 'i' && led[11] == 0 &&
          led[15] == 7);
    CHECK(!encodeOscInt("led", 7, led));
    for (int32_t code : {7, 6, 1, 3}) {
        CHECK(encodeOscInt("/led", code, led));
        OscEvent decoded;
        CHECK(decodeOsc(led.data(), led.size(), decoded));
        CHECK(decoded.address == "/led" && decoded.integers.size() == 1 &&
              decoded.integers[0] == code);
    }
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
    using Seq = eyesy::KnobSequencer;
    Seq seq;
    std::array<double, 5> k{.5, .5, .5, .5, .5};
    CHECK(seq.state() == Seq::State::Stopped);
    CHECK(seq.run(k) == k);
    seq.recordKey(k);
    CHECK(seq.state() == Seq::State::Enabled && seq.size() == 0);
    CHECK(seq.run(k) == k && seq.state() == Seq::State::Enabled);
    k[2] += .004;
    seq.run(k);
    CHECK(seq.state() == Seq::State::Enabled);
    k[2] += .002;
    seq.run(k);
    CHECK(seq.state() == Seq::State::Recording && seq.size() == 0);
    k = {.1, .2, .3, .4, .5};
    CHECK(seq.run(k) == k && seq.size() == 1);
    k = {.2, .3, .4, .5, .6};
    seq.run(k);
    CHECK(seq.size() == 2);
    seq.playStopKey();
    CHECK(seq.state() == Seq::State::Playing);
    std::array<double, 5> ignored{9, 9, 9, 9, 9};
    const std::array<double, 5> first{.1, .2, .3, .4, .5};
    const std::array<double, 5> second{.2, .3, .4, .5, .6};
    CHECK(seq.run(ignored) == first);
    CHECK(seq.run(ignored) == second);
    CHECK(seq.run(ignored) == first);
    seq.playStopKey();
    CHECK(seq.state() == Seq::State::Stopped && seq.size() == 2);
    seq.recordKey(ignored);
    CHECK(seq.state() == Seq::State::Enabled);
    seq.playStopKey();
    CHECK(seq.state() == Seq::State::Stopped);
    Seq full;
    full.recordEnable(ignored);
    ignored[4] += .01;
    full.run(ignored);
    for (int i = 0; i < 1000; ++i)
        full.run(ignored);
    CHECK(full.state() == Seq::State::Playing && full.size() == 1000);
    Seq loaded;
    CHECK(!loaded.load({}, true));
    CHECK(loaded.load(seq.sequence(), true) && loaded.playing() && loaded.size() == 2);
    loaded.clear();
    CHECK(loaded.state() == Seq::State::Stopped && loaded.size() == 0);
    eyesy::PaletteManager palettes;
    CHECK(palettes.size() == 43);
    auto original = palettes.sampleFg(0);
    CHECK(original[0] == 0 && original[1] == 0 && original[2] == 0);
    auto originalTop = palettes.sampleBg(1);
    CHECK(std::abs(originalTop[0] - 1) < 1e-6 && std::abs(originalTop[2] - 1) < 1e-6);
    palettes.setFg(2);
    auto redWhite = palettes.sampleFg(0);
    CHECK(std::abs(redWhite[0] - 1) < 1e-6);
    CHECK(std::abs(redWhite[1] - .0088565) < 1e-4 && std::abs(redWhite[1] - redWhite[2]) < 1e-6);
    palettes.nextFg();
    CHECK(palettes.fg() == 3 and palettes.bg() == 0);
    palettes.prevFg();
    CHECK(palettes.fg() == 2);
    palettes.setFg(0);
    palettes.prevFg();
    CHECK(palettes.fg() == palettes.size() - 1);
    palettes.nextFg();
    CHECK(palettes.fg() == 0);
    palettes.nextBg();
    CHECK(palettes.bg() == 1);
    palettes.setFg(999);
    CHECK(palettes.fg() == 999 % palettes.size());
    CHECK(palettes.preview(true).size() == eyesy::PaletteManager::previewStops);
    CHECK(!palettes.replace({}));
    std::cout << "audio, FFT, trigger, pickup, OSC, MIDI checks passed\n";
}
