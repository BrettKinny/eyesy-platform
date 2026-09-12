#pragma once
#include "core.h"
#include "input_workflow.h"
#include "ofMain.h"
#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

class AudioInput : public ofBaseSoundInput {
    eyesy::AudioRing<16384> ring;
    ofSoundStream stream;
    std::thread worker;
    std::atomic<bool> running{false};
    std::atomic<double> sampleRate{48000};
    std::atomic<float> gain{1};
    std::shared_ptr<eyesy::WavFile> wav;
    std::mutex mutex;
    eyesy::Analysis latest;
    bool synthetic = true;
    void work();

  public:
    bool start(int device = -1);
    bool startWav(const std::filesystem::path &path, std::string &error);
    void setGain(float value) {
        gain = std::clamp(value, 0.0f, 4.0f);
    }
    void stop();
    void audioIn(ofSoundBuffer &buffer) override;
    eyesy::Analysis snapshot();
    uint64_t dropped() const {
        return ring.dropped.load();
    }
    bool isSynthetic() const {
        return synthetic;
    }
    ~AudioInput() {
        stop();
    }
};
