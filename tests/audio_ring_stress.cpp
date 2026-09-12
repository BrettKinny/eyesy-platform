#include "core.h"
#include <atomic>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <thread>

template <size_t N> bool exercise() {
    eyesy::AudioRing<N> ring;
    constexpr uint32_t total = 1000000;
    std::atomic<bool> producerDone{false}, failed{false};
    std::thread producer([&] {
        for (uint32_t i = 0; i < total; ++i) {
            eyesy::StereoFrame f{float(i), -float(i)};
            while (!ring.push(f)) {
                if (failed.load())
                    return;
                std::this_thread::yield();
            }
        }
        producerDone = true;
    });
    std::thread consumer([&] {
        uint32_t expected = 0;
        eyesy::StereoFrame f;
        while (expected < total) {
            if (!ring.pop(f)) {
                std::this_thread::yield();
                continue;
            }
            if (f.left != float(expected) || f.right != -float(expected)) {
                failed = true;
                return;
            }
            ++expected;
        }
    });
    producer.join();
    consumer.join();
    return !failed.load() && producerDone.load();
}
int main() {
    if (!exercise<2>() || !exercise<4>() || !exercise<257>())
        return 1;
    std::cout << "AudioRing concurrent FIFO stress passed\n";
}
