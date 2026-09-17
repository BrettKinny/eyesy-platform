#include "core.h"
#include <algorithm>
#include <cstring>

namespace eyesy {
constexpr double pi = 3.14159265358979323846;
namespace {
struct FftTables {
    std::array<double, fftSize> window{};
    std::array<std::complex<double>, fftSize / 2> twiddles{};
    std::array<size_t, fftSize> bitReverse{};
    double windowSum = 0;
    FftTables() {
        for (size_t i = 0; i < fftSize; ++i) {
            window[i] = .5 * (1 - std::cos(2 * pi * i / (fftSize - 1)));
            windowSum += window[i];
            size_t reversed = 0;
            for (size_t bit = fftSize >> 1, source = i; bit; bit >>= 1, source >>= 1)
                reversed = (reversed << 1) | (source & 1);
            bitReverse[i] = reversed;
        }
        for (size_t i = 0; i < twiddles.size(); ++i)
            twiddles[i] = std::polar(1.0, -2 * pi * i / fftSize);
    }
};
const FftTables &fftTables() {
    static const FftTables tables;
    return tables;
}
} // namespace
void spectrum(const std::array<float, fftSize> &input, std::array<float, fftSize / 2 + 1> &output) {
    const auto &tables = fftTables();
    std::array<std::complex<double>, fftSize> values;
    for (size_t i = 0; i < fftSize; ++i)
        values[tables.bitReverse[i]] = input[i] * tables.window[i];
    for (size_t len = 2; len <= fftSize; len <<= 1) {
        for (size_t i = 0; i < fftSize; i += len) {
            for (size_t j = 0; j < len / 2; ++j) {
                auto a = values[i + j];
                auto b = values[i + j + len / 2] * tables.twiddles[j * fftSize / len];
                values[i + j] = a + b;
                values[i + j + len / 2] = a - b;
            }
        }
    }
    for (size_t i = 0; i < output.size(); ++i)
        output[i] = std::abs(values[i]) / tables.windowSum * ((i == 0 || i == fftSize / 2) ? 1 : 2);
}
Analysis analyze(const std::array<StereoFrame, fftSize> &input, double rate) {
    Analysis a;
    a.sampleRate = rate;
    if (!(rate > 0) || !std::isfinite(rate))
        return a;
    for (size_t i = 0; i < fftSize; ++i) {
        a.left[i] = std::isfinite(input[i].left) ? input[i].left : 0;
        a.right[i] = std::isfinite(input[i].right) ? input[i].right : 0;
        a.peakL = std::max(a.peakL, std::abs(a.left[i]));
        a.peakR = std::max(a.peakR, std::abs(a.right[i]));
        a.rmsL += a.left[i] * a.left[i];
        a.rmsR += a.right[i] * a.right[i];
    }
    a.rmsL = std::sqrt(a.rmsL / fftSize);
    a.rmsR = std::sqrt(a.rmsR / fftSize);
    spectrum(a.left, a.spectrumL);
    spectrum(a.right, a.spectrumR);
    for (size_t i = 1; i < a.spectrumL.size(); ++i) {
        double hz = i * rate / fftSize;
        if (hz < 20 || hz > 20000)
            continue;
        auto band = hz < 250 ? 0 : hz < 4000 ? 1 : 2;
        a.bands[band] += (a.spectrumL[i] * a.spectrumL[i] + a.spectrumR[i] * a.spectrumR[i]) * .5f;
    }
    for (auto &band : a.bands)
        band = std::sqrt(band);
    a.available = true;
    return a;
}
bool TriggerDetector::update(float peak, double dt, double time) {
    if (!std::isfinite(peak) || dt <= 0)
        return false;
    double tau = peak > envelope ? attack : release;
    envelope += (peak - envelope) * (1 - std::exp(-dt / std::max(tau, .00001)));
    if (envelope < releaseThreshold)
        armed = true;
    if (armed && envelope >= threshold && time - lastTrigger >= holdoff) {
        armed = false;
        lastTrigger = time;
        return true;
    }
    return false;
}
void Parameter::restore(double v, double physicalKnob) {
    if (std::isfinite(v))
        value = std::clamp(v, minimum, maximum);
    pickup = true;
    previousKnob = std::clamp(physicalKnob, 0.0, 1.0);
}
void Parameter::applyKnob(double n) {
    if (!std::isfinite(n))
        return;
    n = std::clamp(n, 0.0, 1.0);
    double target = maximum > minimum ? (value - minimum) / (maximum - minimum) : 0;
    if (pickup && (std::abs(n - target) < .02 || (n - target) * (previousKnob - target) <= 0))
        pickup = false;
    previousKnob = n;
    if (!pickup)
        value = minimum + n * (maximum - minimum);
}
static bool readString(const uint8_t *data, size_t size, size_t &pos, std::string &out) {
    size_t start = pos;
    while (pos < size && data[pos])
        ++pos;
    if (pos == size)
        return false;
    out.assign(reinterpret_cast<const char *>(data + start), pos - start);
    pos = (pos + 4) & ~size_t(3);
    return pos <= size;
}
bool decodeOsc(const uint8_t *data, size_t size, OscEvent &result) {
    OscEvent e;
    size_t pos = 0;
    std::string tags;
    if (size > 4096 || !readString(data, size, pos, e.address) || e.address.empty() ||
        e.address[0] != '/' || !readString(data, size, pos, tags) || tags.empty() || tags[0] != ',')
        return false;
    for (size_t i = 1; i < tags.size(); ++i) {
        if (tags[i] == 'i') {
            if (size - pos < 4)
                return false;
            uint32_t n = uint32_t(data[pos]) << 24 | uint32_t(data[pos + 1]) << 16 |
                         uint32_t(data[pos + 2]) << 8 | data[pos + 3];
            int32_t signedN;
            std::memcpy(&signedN, &n, 4);
            e.integers.push_back(signedN);
            pos += 4;
        } else if (tags[i] == 's' && e.text.empty()) {
            if (!readString(data, size, pos, e.text))
                return false;
        } else
            return false;
    }
    if (pos != size)
        return false;
    result = std::move(e);
    return true;
}
static void appendOscString(std::vector<uint8_t> &out, const std::string &value) {
    out.insert(out.end(), value.begin(), value.end());
    out.push_back(0);
    while (out.size() % 4)
        out.push_back(0);
}
bool encodeOscInt(const std::string &address, int32_t value, std::vector<uint8_t> &out) {
    if (address.empty() || address[0] != '/')
        return false;
    out.clear();
    appendOscString(out, address);
    appendOscString(out, ",i");
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    out.push_back(uint8_t(bits >> 24));
    out.push_back(uint8_t(bits >> 16));
    out.push_back(uint8_t(bits >> 8));
    out.push_back(uint8_t(bits));
    return true;
}
void MidiState::apply(const MidiEvent &e) {
    if (e.type == 0x90 && e.a >= 0 && e.a < 128)
        notes[e.a] = std::clamp(e.b, 0, 127);
    if (e.type == 0x80 && e.a >= 0 && e.a < 128)
        notes[e.a] = 0;
    if (e.type == 0xb0 && e.a >= 0 && e.a < 128) {
        cc[e.a] = std::clamp(e.b, 0, 127);
        if (e.a == 123 || e.a == 120)
            notes.fill(0);
    }
    if (e.type == 0xf8)
        ++clocks;
    if (e.type == 0xfa) {
        playing = true;
        clocks = 0;
    }
    if (e.type == 0xfb)
        playing = true;
    if (e.type == 0xfc)
        playing = false;
}
} // namespace eyesy
