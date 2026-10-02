// SPDX-License-Identifier: BSD-3-Clause
// Portions ported from Critter & Guitari EYESY_OS; see THIRD_PARTY_NOTICES.md.
#include "knob_sequencer.h"
#include <cmath>

namespace eyesy {
void KnobSequencer::recordKey(const std::array<double, 5> &knobs) {
    if (current == State::Playing || current == State::Stopped)
        recordEnable(knobs);
    else
        stop();
}
void KnobSequencer::playStopKey() {
    if (current == State::Stopped || current == State::Recording)
        play();
    else
        stop();
}
void KnobSequencer::play() {
    if (frames.empty()) {
        stop();
        return;
    }
    current = State::Playing;
    cursor = 0;
}
void KnobSequencer::recordEnable(const std::array<double, 5> &knobs) {
    // Arm against the knob positions at arm time; recording starts on the
    // first real move, exactly like the stock sequencer.
    armSnapshot = knobs;
    current = State::Enabled;
}
void KnobSequencer::stop() {
    current = State::Stopped;
}
void KnobSequencer::clear() {
    stop();
    frames.clear();
    cursor = 0;
}
void KnobSequencer::beginRecording() {
    current = State::Recording;
    frames.clear();
    cursor = 0;
}
std::array<double, 5> KnobSequencer::run(const std::array<double, 5> &knobs) {
    switch (current) {
    case State::Stopped:
        break;
    case State::Enabled:
        for (size_t i = 0; i < knobs.size(); ++i)
            if (std::abs(knobs[i] - armSnapshot[i]) >= motionThreshold) {
                beginRecording();
                break;
            }
        break;
    case State::Recording:
        frames.push_back(knobs);
        if (frames.size() >= capacity)
            play();
        break;
    case State::Playing: {
        if (frames.empty()) {
            stop();
            break;
        }
        std::array<double, 5> out = knobs;
        for (size_t i = 0; i < out.size(); ++i)
            out[i] = frames[cursor][i];
        cursor = (cursor + 1) % frames.size();
        return out;
    }
    }
    return knobs;
}
bool KnobSequencer::load(const std::vector<std::array<double, 5>> &data, bool resume) {
    if (data.empty() || data.size() > capacity)
        return false;
    frames = data;
    cursor = 0;
    if (resume)
        play();
    else
        stop();
    return true;
}
} // namespace eyesy
