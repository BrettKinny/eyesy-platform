#include "input_workflow.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>

namespace eyesy {
static uint16_t u16(const unsigned char *p) {
    return uint16_t(p[0]) | uint16_t(p[1]) << 8;
}
static uint32_t u32(const unsigned char *p) {
    return uint32_t(u16(p)) | uint32_t(u16(p + 2)) << 16;
}
static float sample(const unsigned char *p, unsigned bits, bool floating) {
    if (floating) {
        float v;
        std::memcpy(&v, p, 4);
        return std::isfinite(v) ? v : 0;
    }
    if (bits == 8)
        return (int(p[0]) - 128) / 128.0f;
    if (bits == 16)
        return int16_t(u16(p)) / 32768.0f;
    if (bits == 24) {
        int32_t v = int32_t(p[0]) | int32_t(p[1]) << 8 | int32_t(p[2]) << 16;
        if (v & 0x800000)
            v |= ~0xffffff;
        return v / 8388608.0f;
    }
    return int32_t(u32(p)) / 2147483648.0f;
}
bool loadWav(const std::filesystem::path &path, WavFile &out, std::string &error,
             size_t maxFrames) {
    error.clear();
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) {
        error = "cannot open WAV";
        return false;
    }
    auto end = in.tellg();
    if (end < 12) {
        error = "WAV too small";
        return false;
    }
    constexpr uint64_t maxContainerBytes = 256ull * 1024 * 1024;
    constexpr size_t maxDecodedFrames = (64u * 1024 * 1024) / sizeof(StereoFrame);
    const uint64_t fileSize = static_cast<uint64_t>(end);
    if (fileSize > maxContainerBytes) {
        error = "WAV exceeds byte limit";
        return false;
    }
    unsigned char header[12], fmt[16]{};
    in.seekg(0);
    in.read(reinterpret_cast<char *>(header), sizeof(header));
    if (!in || std::memcmp(header, "RIFF", 4) || std::memcmp(header + 8, "WAVE", 4) ||
        uint64_t(u32(header + 4)) + 8 != fileSize) {
        error = "invalid RIFF/WAVE size or header";
        return false;
    }
    bool haveFormat = false, haveData = false;
    uint64_t pos = 12, dataOffset = 0;
    uint32_t pcmSize = 0;
    while (pos < fileSize) {
        if (fileSize - pos < 8) {
            error = "truncated WAV chunk header";
            return false;
        }
        unsigned char chunk[8];
        in.seekg(pos);
        in.read(reinterpret_cast<char *>(chunk), 8);
        auto length = u32(chunk + 4);
        uint64_t next = pos + 8 + uint64_t(length) + (length & 1);
        if (!in || next > fileSize) {
            error = "truncated WAV chunk";
            return false;
        }
        if (!std::memcmp(chunk, "fmt ", 4)) {
            if (haveFormat || length < 16) {
                error = "invalid or duplicate WAV format";
                return false;
            }
            in.read(reinterpret_cast<char *>(fmt), sizeof(fmt));
            haveFormat = true;
        } else if (!std::memcmp(chunk, "data", 4)) {
            if (haveData) {
                error = "duplicate WAV data";
                return false;
            }
            haveData = true;
            dataOffset = pos + 8;
            pcmSize = length;
        }
        pos = next;
    }
    if (!haveFormat || !haveData) {
        error = "WAV lacks fmt/data";
        return false;
    }
    unsigned format = u16(fmt), channels = u16(fmt + 2), rate = u32(fmt + 4),
             blockAlign = u16(fmt + 12), bits = u16(fmt + 14);
    bool floating = format == 3;
    if ((format != 1 && !floating) || channels == 0 || rate < 8000 || rate > 192000 ||
        channels > 32 || (floating && bits != 32) ||
        (!floating && (bits != 8 && bits != 16 && bits != 24 && bits != 32))) {
        error = "unsupported WAV format";
        return false;
    }
    size_t bytes = (bits + 7) / 8, stride = bytes * channels;
    if (!stride || pcmSize / stride > std::min(maxFrames, maxDecodedFrames)) {
        error = "WAV exceeds decoded frame/memory limit";
        return false;
    }
    if (blockAlign != stride || u32(fmt + 8) != rate * stride || pcmSize == 0 || pcmSize % stride) {
        error = "invalid WAV block alignment, byte rate or empty data";
        return false;
    }
    WavFile decoded;
    decoded.sampleRate = rate;
    decoded.channels = channels;
    decoded.frames.resize(pcmSize / stride);
    // Decode in small blocks: never retain both an entire encoded file and its
    // expanded stereo float representation at once.
    std::vector<unsigned char> block(4096 * stride);
    in.seekg(dataOffset);
    for (size_t cursor = 0; cursor < decoded.frames.size();) {
        size_t count = std::min<size_t>(4096, decoded.frames.size() - cursor);
        in.read(reinterpret_cast<char *>(block.data()), count * stride);
        if (!in) {
            error = "truncated WAV samples";
            return false;
        }
        for (size_t i = 0; i < count; ++i) {
            const auto *pcm = block.data() + i * stride;
            float l = sample(pcm, bits, floating);
            float r = channels > 1 ? sample(pcm + bytes, bits, floating) : l;
            decoded.frames[cursor + i] = {std::clamp(l, -1.0f, 1.0f), std::clamp(r, -1.0f, 1.0f)};
        }
        cursor += count;
    }
    out = std::move(decoded);
    return true;
}
bool InputRecorder::record(const RecordedInput &event) {
    if (events_.size() >= limit_) {
        truncated_ = true;
        return false;
    }
    std::string error;
    if (!validReplayEvent(event, error))
        return false;
    events_.push_back(event);
    return true;
}
bool validReplayEvent(const RecordedInput &e, std::string &error) {
    error.clear();
    if (e.type == "knob") {
        if (e.index < 1 || e.index > 5 || !std::isfinite(e.value))
            error = "invalid knob event";
    } else if (e.type == "key" || e.type == "hardware_key" || e.type == "key_release" ||
               e.type == "hardware_release") {
        if (e.key < 0 || e.key > 65535)
            error = "invalid key event";
    } else if (e.type == "midi") {
        if (e.status < 0 || e.status > 255 || e.channel < 0 || e.channel > 15 || e.a < 0 ||
            e.a > 127 || e.b < 0 || e.b > 127)
            error = "invalid MIDI event";
    } else
        error = "unknown input event";
    return error.empty();
}
} // namespace eyesy
