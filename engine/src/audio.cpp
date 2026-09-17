#include "audio.h"
#include <chrono>
bool AudioInput::start(int device) {
    stop();
    wav.reset();
    sampleRate = 48000;
    synthetic = device == -1;
    if (!synthetic) {
        ofSoundStreamSettings settings;
        auto devices = stream.getDeviceList();
        if (device == -2) {
            for (size_t i = 0; i < devices.size(); ++i) {
                auto name = ofToLower(devices[i].name);
                if (devices[i].inputChannels >= 2 &&
                    (name.find("wm8731") != std::string::npos ||
                     name.find("audioinjector") != std::string::npos)) {
                    device = int(i);
                    break;
                }
            }
        }
        if (device < 0 || device >= int(devices.size()) || devices[device].inputChannels < 2)
            return false;
        settings.setInDevice(devices[device]);
        settings.setInListener(this);
        auto rates = devices[device].sampleRates;
        settings.sampleRate = 48000;
        if (!rates.empty() && std::find(rates.begin(), rates.end(), 48000) == rates.end())
            settings.sampleRate =
                std::find(rates.begin(), rates.end(), 44100) != rates.end() ? 44100 : rates.front();
        settings.bufferSize = 256;
        settings.numInputChannels = 2;
        settings.numOutputChannels = 0;
        if (!stream.setup(settings))
            return false;
        sampleRate = stream.getSampleRate();
    }
    running = true;
    worker = std::thread(&AudioInput::work, this);
    return true;
}
bool AudioInput::startWav(const std::filesystem::path &path, std::string &error) {
    stop();
    auto source = std::make_shared<eyesy::WavFile>();
    if (!eyesy::loadWav(path, *source, error))
        return false;
    wav = std::move(source);
    synthetic = false;
    sampleRate = wav->sampleRate;
    running = true;
    worker = std::thread(&AudioInput::work, this);
    return true;
}
void AudioInput::stop() {
    stream.stop();
    stream.close();
    running = false;
    synthesizing = false;
    if (worker.joinable())
        worker.join();
    eyesy::StereoFrame discarded;
    while (ring.pop(discarded)) {
    }
    std::lock_guard<std::mutex> lock(mutex);
    latest = {};
}
void AudioInput::audioIn(ofSoundBuffer &buffer) {
    if (synthesizing.load())
        return;
    auto channels = buffer.getNumChannels();
    if (channels < 2)
        return;
    sampleRate = buffer.getSampleRate();
    for (size_t i = 0; i < buffer.getNumFrames(); ++i)
        ring.push({buffer[i * channels] * gain.load(), buffer[i * channels + 1] * gain.load()});
}
void AudioInput::work() {
    std::array<eyesy::StereoFrame, eyesy::fftSize> history{};
    size_t cursor = 0, filled = 0, hop = 0;
    uint64_t seq = 0, triggerCount = 0, sample = 0;
    eyesy::TriggerDetector detector;
    auto deadline = std::chrono::steady_clock::now();
    size_t wavCursor = 0;
    while (running) {
        if (synthesizing.load()) {
            // Stock OS v3 fills the input buffer with an undulating sine while the
            // trigger is held so audio-reactive modes run without an external source.
            undulatePhase += 0.005;
            double undulate = ((std::sin(undulatePhase * 2 * PI) + 1.0) * 2.0) + 0.5;
            for (int i = 0; i < 256; ++i) {
                float value = float(std::sin((i / 100.0) * 2 * PI * undulate) *
                                    (25000.0 / 32768.0));
                ring.push({value, value});
            }
            deadline += std::chrono::microseconds(5333);
            std::this_thread::sleep_until(deadline);
        } else if (wav) {
            if (wavCursor >= wav->frames.size()) {
                running = false;
                break;
            }
            size_t count = std::min<size_t>(256, wav->frames.size() - wavCursor);
            for (size_t i = 0; i < count; ++i)
                ring.push({wav->frames[wavCursor + i].left * gain.load(),
                           wav->frames[wavCursor + i].right * gain.load()});
            wavCursor += count;
            deadline += std::chrono::microseconds(
                static_cast<int64_t>(count * 1000000.0 / sampleRate.load()));
            std::this_thread::sleep_until(deadline);
        } else if (synthetic) {
            for (int i = 0; i < 256; ++i, ++sample) {
                double t = sample / 48000.0, env = (.35 + .25 * std::sin(t * 2)) * gain.load();
                ring.push({float(env * std::sin(t * 2 * PI * 220)),
                           float(env * std::sin(t * 2 * PI * 440))});
            }
            deadline += std::chrono::microseconds(5333);
            std::this_thread::sleep_until(deadline);
        }
        eyesy::StereoFrame frame;
        bool consumed = false;
        while (ring.pop(frame)) {
            consumed = true;
            history[cursor] = frame;
            cursor = (cursor + 1) % history.size();
            ++filled;
            ++hop;
            if (filled >= history.size() && hop >= 512) {
                hop = 0;
                std::array<eyesy::StereoFrame, eyesy::fftSize> ordered;
                for (size_t i = 0; i < ordered.size(); ++i)
                    ordered[i] = history[(cursor + i) % history.size()];
                auto a = eyesy::analyze(ordered, sampleRate.load());
                if (synthesizing.load()) {
                    float peak = float(25000.0 / 32768.0);
                    a.peakL = std::max(a.peakL, peak);
                    a.peakR = std::max(a.peakR, peak);
                }
                a.sequence = ++seq;
                a.timestamp = ofGetElapsedTimef();
                if (detector.update(std::max(a.peakL, a.peakR), 512.0 / a.sampleRate, a.timestamp))
                    ++triggerCount;
                a.triggerCount = triggerCount;
                std::lock_guard<std::mutex> lock(mutex);
                latest = a;
            }
        }
        if (!consumed && !synthetic)
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
eyesy::Analysis AudioInput::snapshot() {
    std::lock_guard<std::mutex> lock(mutex);
    auto a = latest;
    if (ofGetElapsedTimef() - a.timestamp > .25) {
        a = eyesy::Analysis{};
        a.available = false;
    }
    return a;
}
