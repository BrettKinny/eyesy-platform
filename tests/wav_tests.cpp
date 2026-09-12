#include "input_workflow.h"
#include <cmath>
#include <cstdint>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <unistd.h>
#include <vector>

static void p16(std::vector<unsigned char> &v, uint32_t n) {
    v.push_back(n);
    v.push_back(n >> 8);
}
static void p32(std::vector<unsigned char> &v, uint32_t n) {
    p16(v, n);
    p16(v, n >> 16);
}
static void appendChunk(const std::string &path, const std::vector<unsigned char> &chunk) {
    std::ifstream in(path, std::ios::binary);
    std::vector<unsigned char> d((std::istreambuf_iterator<char>(in)), {});
    uint32_t size = uint32_t(d.size() - 8 + chunk.size());
    for (int i = 0; i < 4; ++i) d[4 + i] = uint8_t(size >> (8 * i));
    d.insert(d.end(), chunk.begin(), chunk.end());
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char *>(d.data()), d.size());
}
static std::string writeWav(unsigned bits, bool floating, bool mono, bool odd,
                            bool badSize = false) {
    unsigned ch = mono ? 1 : 2, bytes = bits / 8, align = ch * bytes;
    std::vector<unsigned char> fmt, data;
    p16(fmt, floating ? 3 : 1);
    p16(fmt, ch);
    p32(fmt, 48000);
    p32(fmt, 48000 * align);
    p16(fmt, align);
    p16(fmt, bits);
    auto add = [&](int32_t n) {
        if (bits == 8)
            data.push_back(unsigned(n + 128));
        else if (bits == 16)
            p16(data, uint16_t(n));
        else if (bits == 24) {
            data.push_back(n);
            data.push_back(n >> 8);
            data.push_back(n >> 16);
        } else
            p32(data, uint32_t(n));
    };
    if (floating) {
        float a = .25f, b = -.5f;
        unsigned char *x = reinterpret_cast<unsigned char *>(&a);
        data.insert(data.end(), x, x + 4);
        if (!mono) {
            x = reinterpret_cast<unsigned char *>(&b);
            data.insert(data.end(), x, x + 4);
        }
    } else {
        add(bits == 8 ? 64 : (bits == 16 ? 16384 : (bits == 24 ? 2097152 : 1073741824)));
        if (!mono)
            add(bits == 8 ? -64 : (bits == 16 ? -16384 : (bits == 24 ? -2097152 : -1073741824)));
    }
    std::vector<unsigned char> w({'R', 'I', 'F', 'F'});
    uint32_t riff = 4 + 8 + fmt.size() + (odd ? 12 : 0) + 8 + data.size() + (data.size() & 1);
    p32(w, badSize ? riff + 100 : riff);
    w.insert(w.end(), {'W', 'A', 'V', 'E'});
    w.insert(w.end(), {'f', 'm', 't', ' '});
    p32(w, fmt.size());
    w.insert(w.end(), fmt.begin(), fmt.end());
    if (odd) {
        w.insert(w.end(), {'J', 'U', 'N', 'K'});
        p32(w, 3);
        w.insert(w.end(), {1, 2, 3, 0});
    }
    w.insert(w.end(), {'d', 'a', 't', 'a'});
    p32(w, data.size());
    w.insert(w.end(), data.begin(), data.end());
    if (data.size() & 1)
        w.push_back(0);
    char dir[] = "/tmp/eyesy-wav-XXXXXX";
    int fd = mkstemp(dir);
    if (fd < 0)
        return {};
    close(fd);
    std::ofstream o(dir, std::ios::binary);
    o.write((char *)w.data(), w.size());
    return dir;
}
static bool good(const std::string &p, unsigned bits, bool mono, bool floating, bool) {
    eyesy::WavFile w;
    std::string e;
    if (!eyesy::loadWav(p, w, e) || w.frames.size() != 1 || w.channels != (mono ? 1u : 2u))
        return false;
    float l = w.frames[0].left, r = w.frames[0].right;
    float expected = (floating || bits == 24) ? .25f : .5f;
    return std::abs(l - expected) < .02f &&
           std::abs(r - (mono ? l : (floating ? -.5f : -expected))) < .02f;
}
int main() {
    eyesy::WavFile w;
    std::string e;
    for (unsigned b : {8u, 16u, 24u, 32u}) {
        auto p = writeWav(b, false, b == 8, false);
        if (!good(p, b, b == 8, false, false)) {
            std::cerr << "bad pcm " << b << "\n";
            return 1;
        }
        unlink(p.c_str());
    }
    auto fp = writeWav(32, true, false, false);
    if (!good(fp, 32, false, true, false)) {
        std::cerr << "bad float\n";
        return 2;
    }
    unlink(fp.c_str());
    auto nan = writeWav(32, true, false, false);
    { int fd = open(nan.c_str(), O_RDWR); unsigned char q[4] = {0, 0, 192, 127}; pwrite(fd, q, 4, 44); close(fd); }
    if (!eyesy::loadWav(nan, w, e) || w.frames[0].left != 0) return 14;
    unlink(nan.c_str());
    auto op = writeWav(16, false, false, true);
    if (!good(op, 16, false, false, true))
        return 3;
    unlink(op.c_str());
    auto bad = writeWav(16, false, false, false, true);
    if (eyesy::loadWav(bad, w, e))
        return 4;
    unlink(bad.c_str());
    auto partial = writeWav(16, false, false, false);
    truncate(partial.c_str(), 47);
    if (eyesy::loadWav(partial, w, e))
        return 6;
    unlink(partial.c_str());
    auto align = writeWav(16, false, false, false);
    {
        int fd = open(align.c_str(), O_RDWR);
        unsigned char x[2] = {3, 0};
        pwrite(fd, x, 2, 32);
        close(fd);
    }
    if (eyesy::loadWav(align, w, e))
        return 7;
    unlink(align.c_str());
    auto rate = writeWav(16, false, false, false);
    {
        int fd = open(rate.c_str(), O_RDWR);
        unsigned char x[4] = {0x3f, 0x1f, 0, 0};
        pwrite(fd, x, 4, 24);
        uint32_t br = 7999 * 4;
        unsigned char b[4] = {uint8_t(br), uint8_t(br >> 8), uint8_t(br >> 16), uint8_t(br >> 24)};
        pwrite(fd, b, 4, 28);
        close(fd);
    }
    if (eyesy::loadWav(rate, w, e))
        return 8;
    unlink(rate.c_str());
    auto empty = writeWav(16, false, false, false);
    {
        int fd = open(empty.c_str(), O_RDWR);
        unsigned char x[4] = {36, 0, 0, 0};
        pwrite(fd, x, 4, 4);
        unsigned char z[4] = {0, 0, 0, 0};
        pwrite(fd, z, 4, 40);
        close(fd);
        truncate(empty.c_str(), 44);
    }
    if (eyesy::loadWav(empty, w, e))
        return 9;
    unlink(empty.c_str());
    auto limited = writeWav(16, false, false, false);
    if (eyesy::loadWav(limited, w, e, 0))
        return 10;
    unlink(limited.c_str());
    char hugeName[] = "/tmp/eyesy-wav-limit-XXXXXX";
    int hugeFd = mkstemp(hugeName);
    std::vector<unsigned char> h = {'R', 'I', 'F', 'F'};
    p32(h, 9000036);
    h.insert(h.end(), {'W', 'A', 'V', 'E', 'f', 'm', 't', ' '});
    p32(h, 16);
    p16(h, 1);
    p16(h, 1);
    p32(h, 48000);
    p32(h, 48000);
    p16(h, 1);
    p16(h, 8);
    h.insert(h.end(), {'d', 'a', 't', 'a'});
    p32(h, 9000000);
    write(hugeFd, h.data(), h.size());
    ftruncate(hugeFd, 9000044);
    close(hugeFd);
    if (eyesy::loadWav(hugeName, w, e) || e.find("decoded") == std::string::npos)
        return 11;
    unlink(hugeName);
    auto dupData = writeWav(16, false, false, false);
    appendChunk(dupData, {'d','a','t','a',0,0,0,0});
    if (eyesy::loadWav(dupData, w, e) || e.find("duplicate") == std::string::npos) return 12;
    unlink(dupData.c_str());
    auto dupFmt = writeWav(16, false, false, false);
    std::vector<unsigned char> extra = {'f','m','t',' ',16,0,0,0,1,0,2,0,0x80,0xbb,0,0,0,0xEE,2,0,16,0,0,0,0,0};
    appendChunk(dupFmt, extra);
    if (eyesy::loadWav(dupFmt, w, e) || e.find("duplicate") == std::string::npos) return 13;
    unlink(dupFmt.c_str());
    eyesy::InputRecorder r(2);
    if (!r.record({0, "hardware_key", 0, 2}) || !r.record({1, "hardware_release", 0, 2}) ||
        r.record({2, "key", 0, 3}))
        return 5;
    std::cout << "WAV format, chunk, bounds, and recorder checks passed\n";
}
