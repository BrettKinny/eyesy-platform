// SPDX-License-Identifier: BSD-3-Clause
#include "core.h"
#include <chrono>
#include <cmath>
#include <iostream>

int main() {
    std::array<eyesy::StereoFrame, eyesy::fftSize> input{};
    for (size_t i = 0; i < input.size(); ++i)
        input[i].left = std::sin(2 * 3.141592653589793 * 32 * i / input.size()) * .5f;
    constexpr int warmup = 20, rounds = 1000;
    for (int i = 0; i < warmup; ++i) eyesy::analyze(input, 48000);
    auto start = std::chrono::steady_clock::now();
    volatile float guard = 0;
    for (int i = 0; i < rounds; ++i) guard += eyesy::analyze(input, 48000).spectrumL[32];
    auto elapsed = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - start).count();
    std::cout << "rounds=" << rounds << " total_us=" << elapsed
              << " per_analyze_us=" << elapsed / rounds << " guard=" << guard << '\n';
}
