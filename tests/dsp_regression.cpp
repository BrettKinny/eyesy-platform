// SPDX-License-Identifier: BSD-3-Clause
#include "core.h"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>

#define CHECK(x)                                                                                   \
    do {                                                                                           \
        if (!(x)) {                                                                                \
            std::cerr << "failed: " #x << '\n';                                                    \
            return 1;                                                                              \
        }                                                                                          \
    } while (0)
int main() {
    using namespace eyesy;
    std::array<StereoFrame, fftSize> input{};
    auto pi = 3.141592653589793;
    for (size_t i = 0; i < fftSize; ++i)
        input[i].left = .5f * std::sin(2 * pi * 32 * i / fftSize);
    auto sine = analyze(input, 48000);
    CHECK(std::abs(sine.spectrumL[32] - .5f) < .002f);
    CHECK(std::max_element(sine.spectrumL.begin(), sine.spectrumL.end()) - sine.spectrumL.begin() ==
          32);
    std::complex<double> direct{};
    double windowSum = 0;
    for (size_t i = 0; i < fftSize; ++i) {
        double w = .5 * (1 - std::cos(2 * pi * i / (fftSize - 1)));
        windowSum += w;
        direct += input[i].left * w * std::polar(1.0, -2 * pi * 32 * i / fftSize);
    }
    CHECK(std::abs(std::abs(direct) / windowSum * 2 - sine.spectrumL[32]) < 1e-6);
    input = {};
    for (auto &frame : input)
        frame.left = .25f;
    auto dc = analyze(input, 48000);
    CHECK(std::abs(dc.spectrumL[0] - .25f) < .002f);
    input = {};
    for (size_t i = 0; i < fftSize; ++i)
        input[i].left = (i & 1) ? -.5f : .5f;
    auto nyquist = analyze(input, 48000);
    CHECK(std::abs(nyquist.spectrumL[fftSize / 2] - .5f) < .002f);
    input[17].left = std::numeric_limits<float>::quiet_NaN();
    CHECK(analyze(input, 48000).available);
    CHECK(!analyze(input, 0).available);
    std::cout << "DSP regression checks passed\n";
}
