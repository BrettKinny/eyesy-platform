// SPDX-License-Identifier: BSD-3-Clause
#include "input_workflow.h"
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <unistd.h>
#include <vector>

using Bytes = std::vector<unsigned char>;
static void p16(Bytes &v, uint32_t n) { v.push_back(n); v.push_back(n >> 8); }
static void p32(Bytes &v, uint32_t n) { p16(v, n); p16(v, n >> 16); }
static void set32(Bytes &v, size_t offset, uint32_t n) {
    for (unsigned i = 0; i < 4; ++i) v.at(offset + i) = n >> (8 * i);
}
struct Temp {
    char name[32] = "/tmp/eyesy-mut-XXXXXX";
    int fd = mkstemp(name);
    ~Temp() { if (fd >= 0) { close(fd); unlink(name); } }
    bool replace(const Bytes &bytes) {
        return ftruncate(fd, 0) == 0 && lseek(fd, 0, SEEK_SET) == 0 &&
            write(fd, bytes.data(), bytes.size()) == static_cast<ssize_t>(bytes.size());
    }
};
static Bytes wav(bool floating) {
    Bytes v = {'R','I','F','F'};
    p32(v, 0);
    v.insert(v.end(), {'W','A','V','E','f','m','t',' '});
    p32(v, 16);
    p16(v, floating ? 3 : 1);
    p16(v, 2);
    p32(v, 48000);
    const unsigned sampleBytes = floating ? 4 : 2;
    p32(v, 48000 * 2 * sampleBytes);
    p16(v, 2 * sampleBytes);
    p16(v, 8 * sampleBytes);
    v.insert(v.end(), {'d','a','t','a'});
    p32(v, 32 * 2 * sampleBytes);
    for (unsigned i = 0; i < 64; ++i) {
        if (floating) {
            float value = i % 2 ? -0.5f : 0.25f;
            uint32_t bits;
            std::memcpy(&bits, &value, sizeof(bits));
            p32(v, bits);
        } else {
            p16(v, static_cast<uint16_t>(i % 2 ? -16384 : 8192));
        }
    }
    set32(v, 4, v.size() - 8);
    return v;
}
static bool invariant(const eyesy::WavFile &out) {
    if (out.sampleRate < 8000 || out.sampleRate > 192000 ||
        !out.channels || out.channels > 32 || out.frames.empty() ||
        out.frames.size() * sizeof(out.frames[0]) > 64u * 1024u * 1024u)
        return false;
    for (auto frame : out.frames)
        if (!std::isfinite(frame.left) || !std::isfinite(frame.right) ||
            frame.left < -1 || frame.left > 1 || frame.right < -1 || frame.right > 1)
            return false;
    return true;
}
int main() {
    constexpr uint32_t seed = 0xE1E5;
    std::mt19937 rng(seed);
    Temp file;
    if (file.fd < 0) return 2;
    // A campaign must first prove that BOTH starting fixtures actually parse.
    for (bool floating : {false, true}) {
        eyesy::WavFile out;
        std::string error;
        if (!file.replace(wav(floating)) || !eyesy::loadWav(file.name, out, error) ||
            !invariant(out) || out.frames.size() != 32 ||
            std::abs(out.frames[0].left - .25f) > .001f ||
            std::abs(out.frames[0].right + .5f) > .001f) {
            std::cerr << "invalid mutation seed: " << error << '\n';
            return 3;
        }
    }
    uint32_t accepted = 0, rejected = 0;
    for (unsigned n = 0; n < 10000; ++n) {
        Bytes data = wav((n / 6) % 2);
        switch (n % 6) {
        case 0:
            for (unsigned i = 0, count = 1 + rng() % 4; i < count; ++i)
                data[44 + rng() % (data.size() - 44)] ^= 1u << (rng() % 8);
            break;
        case 1: {
            const unsigned offsets[] = {4, 16, 40};
            set32(data, offsets[rng() % 3], rng());
            break;
        }
        case 2:
            data.resize(rng() % data.size());
            break;
        case 3: {
            Bytes duplicate;
            if ((n / 6) % 2) duplicate.assign(data.begin() + 12, data.begin() + 36);
            else duplicate.assign(data.begin() + 36, data.end());
            data.insert(data.end(), duplicate.begin(), duplicate.end());
            set32(data, 4, data.size() - 8);
            break;
        }
        case 4: {
            const Bytes junk = {'J','U','N','K',3,0,0,0,1,2,3,0};
            data.insert(data.begin() + 36, junk.begin(), junk.end());
            set32(data, 4, data.size() - 8);
            break;
        }
        default:
            data.resize(rng() % 128);
            for (auto &byte : data) byte = rng();
            break;
        }
        if (!file.replace(data)) return 4;
        eyesy::WavFile out;
        std::string error;
        if (eyesy::loadWav(file.name, out, error)) {
            ++accepted;
            if (!invariant(out)) return 5;
        } else {
            ++rejected;
            if (error.empty()) return 6;
        }
    }
    if (accepted < 500 || rejected < 500) return 7;
    std::cout << "WAV mutation stress passed seed=" << seed
              << " cases=10000 accepted=" << accepted << " rejected=" << rejected << '\n';
}
