// SPDX-License-Identifier: BSD-3-Clause
#pragma once

#include "core.h"
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace eyesy {
struct WavFile {
    double sampleRate = 0;
    unsigned channels = 0;
    std::vector<StereoFrame> frames;
};

// Loads bounded PCM/IEEE-float WAV data for analysis preview. No audio output is opened.
bool loadWav(const std::filesystem::path &path, WavFile &result, std::string &error,
             size_t maxFrames = 48000u * 600u);

struct RecordedInput {
    uint64_t frame = 0;
    std::string type;
    int index = 0, key = 0, status = 0, channel = 0, a = 0, b = 0;
    double value = 0, gain = 1, freq = 1;
};

class InputRecorder {
    std::vector<RecordedInput> events_;
    size_t limit_;
    bool truncated_ = false;

  public:
    explicit InputRecorder(size_t limit = 10000) : limit_(limit) {}
    bool record(const RecordedInput &event);
    const std::vector<RecordedInput> &events() const {
        return events_;
    }
    bool truncated() const {
        return truncated_;
    }
    size_t size() const {
        return events_.size();
    }
};

bool validReplayEvent(const RecordedInput &event, std::string &error);
} // namespace eyesy
