#pragma once
#include <array>
#include <cstddef>
#include <vector>

namespace eyesy {
// Stock EYESY OS v3 knob sequencer: five knob channels are captured frame by
// frame while recording, replayed on a loop, and persisted with the scene when
// a sequence is playing. Kept free of openFrameworks so the state machine is
// unit-testable natively.
class KnobSequencer {
  public:
    enum class State { Stopped, Enabled, Recording, Playing };
    static constexpr size_t capacity = 1000;
    // Stock arms on `abs(delta) >= .005` for any knob.
    static constexpr double motionThreshold = .005;

    State state() const {
        return current;
    }
    bool playing() const {
        return current == State::Playing;
    }
    bool recording() const {
        return current == State::Recording;
    }
    size_t size() const {
        return frames.size();
    }

    // Key 10 (Shift + Trigger) and key 9 (Shift + Screenshot) toggles.
    void recordKey(const std::array<double, 5> &knobs);
    void playStopKey();
    void play();
    void stop();
    void clear();
    void recordEnable(const std::array<double, 5> &knobs);

    // Called once per frame with the physical knob positions; returns what the
    // mode should see, with playback overriding the live values.
    std::array<double, 5> run(const std::array<double, 5> &knobs);

    const std::vector<std::array<double, 5>> &sequence() const {
        return frames;
    }
    size_t index() const {
        return cursor;
    }
    bool load(const std::vector<std::array<double, 5>> &data, bool resume);

  private:
    void beginRecording();
    State current = State::Stopped;
    std::vector<std::array<double, 5>> frames;
    std::array<double, 5> armSnapshot{};
    size_t cursor = 0;
};
} // namespace eyesy
