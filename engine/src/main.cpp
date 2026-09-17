#include "audio.h"
#include "kms_window.h"
#include "offscreen_window.h"
#include "runtime.h"
#include <alsa/asoundlib.h>
#include <arpa/inet.h>
#include <csignal>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace fs = std::filesystem;
// A routine stop (systemd SIGTERM) must exit 0: the platform unit's
// OnFailure= fallback fires on any nonzero exit, so a clean stop that looked
// like a failure spuriously summoned the stock recovery path. Handle SIGTERM
// with a flag and exit cleanly from the next frame; a nonzero exit here comes
// from a teardown throw (main's catch block), not the handler.
static volatile std::sig_atomic_t terminateRequested = 0;
static void requestTermination(int) { terminateRequested = 1; }
struct Options {
    fs::path mode, storage = "local", report, replay, audioWav, record;
    int frames = 0, device = -1, port = 0, switchEvery = 0;
    bool fullscreen = false, probe = false, offscreen = false, kms = false;
    size_t recordLimit = 10000;
};
static void atomicJson(const fs::path &path, const ofJson &data) {
    fs::create_directories(path.parent_path());
    auto tmp = path;
    tmp += ".tmp";
    {
        std::ofstream out(tmp);
        out << data.dump(2) << '\n';
        out.flush();
        if (!out)
            throw std::runtime_error("cannot write " + tmp.string());
    }
    int fd = open(tmp.c_str(), O_RDONLY);
    if (fd < 0)
        throw std::runtime_error("cannot open scene for sync");
    int result = fsync(fd);
    close(fd);
    if (result)
        throw std::runtime_error("scene fsync failed");
    fs::rename(tmp, path);
    fd = open(path.parent_path().c_str(), O_RDONLY | O_DIRECTORY);
    if (fd >= 0) {
        fsync(fd);
        close(fd);
    }
}
static void notify(const std::string &message) {
    const char *path = getenv("NOTIFY_SOCKET");
    if (!path)
        return;
    int sock = socket(AF_UNIX, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    if (sock < 0)
        return;
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    size_t len = std::min(strlen(path), sizeof(address.sun_path) - 1);
    memcpy(address.sun_path, path, len);
    if (address.sun_path[0] == '@')
        address.sun_path[0] = 0;
    sendto(sock, message.data(), message.size(), MSG_NOSIGNAL,
           reinterpret_cast<sockaddr *>(&address), offsetof(sockaddr_un, sun_path) + len + 1);
    close(sock);
}
class EngineApp : public ofBaseApp {
    Options options;
    ModeRuntime runtime;
    AudioInput audio;
    eyesy::MidiState midi;
    std::array<double, 5> knobs{{.5, .5, .5, .5, .5}};
    std::vector<fs::path> catalog, scenes;
    std::vector<double> frameTimes;
    std::map<fs::path, fs::file_time_type> watched;
    ofFbo canvas;
    int selected = 0, sceneIndex = -1, selectedKnob = 0, sock = -1;
    uint64_t frame = 0, triggerCount = 0, reloads = 0, modeErrors = 0;
    double lastFrame = 0, lastWatch = 0, lastStatus = 0;
    bool trigger = false, osd = true, autoClear = true, shift = false;
    std::string message, renderer;
    snd_seq_t *seq = nullptr;
    int seqPort = -1;
    double lastMidiScan = -10;
    std::set<std::pair<int, int>> subscriptions;
    ofJson replayEvents = ofJson::array();
    size_t replayIndex = 0;
    bool deterministic = false;
    double replayGain = 1, replayFreq = 1;
    eyesy::InputRecorder recorder;
    std::vector<eyesy::MidiEvent> midiEvents;
    eyesy::Analysis lastAnalysis;
    bool menu = false;
    int menuRow = 0, midiChannel = 1, triggerSource = 2;
    double audioGain = 1, audioRetry = 0;
    void recordEvent(const eyesy::RecordedInput &event) {
        if (!options.record.empty())
            recorder.record(event);
    }
    void writeRecording() {
        if (options.record.empty())
            return;
        ofJson result = ofJson::array();
        for (const auto &e : recorder.events()) {
            ofJson j = {{"frame", e.frame}, {"type", e.type}};
            if (e.type == "knob")
                j.update({{"index", e.index}, {"value", e.value}});
            else if (e.type == "key" || e.type == "key_release" || e.type == "hardware_key" ||
                     e.type == "hardware_release")
                j["key"] = e.key;
            else
                j.update({{"status", e.status}, {"channel", e.channel}, {"a", e.a}, {"b", e.b}});
            result.push_back(j);
        }
        atomicJson(options.record, result);
    }
    void settingsText() {
        message = "SETTINGS [scene +/-: row; mode +/-: value; save: persist]\n";
        message +=
            (menuRow == 0 ? "> " : "  ") + std::string("Gain ") + ofToString(audioGain, 2) + "  ";
        message += (menuRow == 1 ? "> " : "  ") + std::string("MIDI channel ") +
                   ofToString(midiChannel) + "  ";
        const char *sources[] = {"audio", "MIDI note", "audio + note", "MIDI quarter"};
        message += (menuRow == 2 ? "> " : "  ") + std::string("Trigger ") + sources[triggerSource];
    }
    void settingsKey(int key) {
        if (key == 1) {
            menu = false;
            message.clear();
            return;
        }
        if (key == 6)
            menuRow = (menuRow + 2) % 3;
        if (key == 7)
            menuRow = (menuRow + 1) % 3;
        int direction = key == 4 ? -1 : key == 5 ? 1 : 0;
        if (menuRow == 0)
            audioGain = std::clamp(audioGain + direction * .05, 0.0, 4.0);
        if (menuRow == 1)
            midiChannel = std::clamp(midiChannel + direction, 1, 16);
        if (menuRow == 2)
            triggerSource = std::clamp(triggerSource + direction, 0, 3);
        audio.setGain(audioGain);
        if (key == 8) {
            try {
                atomicJson(options.storage / "config.json", {{"schema_version", 1},
                                                             {"audio_gain", audioGain},
                                                             {"midi_channel", midiChannel},
                                                             {"trigger_source", triggerSource}});
                menu = false;
                message = "Settings saved";
            } catch (const std::exception &e) {
                message = e.what();
            }
            return;
        }
        settingsText();
    }
    void watchFiles() {
        watched.clear();
        if (!fs::is_directory(runtime.directory))
            return;
        for (auto &entry : fs::recursive_directory_iterator(runtime.directory))
            if (entry.is_regular_file())
                watched[entry.path()] = entry.last_write_time();
    }
    void loadMode(int index) {
        if (catalog.empty())
            return;
        selected = (index + int(catalog.size())) % catalog.size();
        if (!runtime.load(catalog[selected], 1280, 720))
            ++modeErrors;
        runtime.snapshot(ofGetElapsedTimef(), 0, knobs, audio.snapshot(), midi, trigger);
        ++reloads;
        watchFiles();
        canvas.begin();
        ofClear(0, 0, 0, 255);
        canvas.end();
    }
    void hardwareKey(int key, bool down) {
        if (!deterministic)
            recordEvent({frame, down ? "hardware_key" : "hardware_release", 0, key});
        if (key == 2) {
            shift = down;
            return;
        }
        if (!down)
            return;
        if (menu) {
            settingsKey(key);
            return;
        }
        if (shift) {
            if (key == 1) {
                menu = true;
                osd = true;
                settingsText();
            }
            return;
        }
        if (key == 1)
            osd = !osd;
        if (key == 3)
            autoClear = !autoClear;
        if (key == 4)
            loadMode(selected - 1);
        if (key == 5)
            loadMode(selected + 1);
        if (key == 6)
            recallScene(-1);
        if (key == 7)
            recallScene(1);
        if (key == 8)
            saveScene();
        if (key == 9)
            screenshot();
        if (key == 10)
            trigger = true;
    }
    void saveScene() {
        try {
            ofJson j = {{"schema_version", 1},
                        {"mode", runtime.directory.filename().string()},
                        {"parameters", ofJson::object()},
                        {"state", runtime.save()},
                        {"auto_clear", autoClear}};
            for (auto &p : runtime.parameters)
                j["parameters"][p.first] = p.second.value;
            auto path = options.storage / "scenes" /
                        ("scene-" + ofGetTimestampString("%Y%m%d-%H%M%S-%i") + ".json");
            atomicJson(path, j);
            message = "Saved " + path.filename().string();
        } catch (const std::exception &e) {
            message = e.what();
        }
    }
    void recallScene(int direction) {
        try {
            scenes.clear();
            auto folder = options.storage / "scenes";
            if (fs::exists(folder))
                for (auto &e : fs::directory_iterator(folder))
                    if (e.path().extension() == ".json")
                        scenes.push_back(e.path());
            std::sort(scenes.begin(), scenes.end());
            if (scenes.empty()) {
                message = "No scenes";
                return;
            }
            sceneIndex = (sceneIndex + direction + int(scenes.size())) % scenes.size();
            auto j = ofLoadJson(scenes[sceneIndex].string());
            if (j.at("schema_version") != 1 || !j.at("parameters").is_object())
                throw std::runtime_error("unsupported scene");
            auto mode = j.at("mode").get<std::string>();
            auto it = std::find_if(catalog.begin(), catalog.end(),
                                   [&](auto &p) { return p.filename() == mode; });
            if (it == catalog.end())
                throw std::runtime_error("scene mode missing: " + mode);
            loadMode(it - catalog.begin());
            for (auto &p : runtime.parameters)
                if (j["parameters"].contains(p.first))
                    p.second.restore(j["parameters"][p.first].get<double>(),
                                     p.second.knob >= 0 ? knobs[p.second.knob] : 0);
            autoClear = j.value("auto_clear", true);
            runtime.restore(j.value("state", ofJson::object()));
            message = "Recalled " + mode;
        } catch (const std::exception &e) {
            message = e.what();
        }
    }
    void screenshot() {
        fs::create_directories(options.storage / "grabs");
        ofPixels pixels;
        canvas.readToPixels(pixels);
        if (ofSaveImage(pixels,
                        (options.storage / "grabs" / (ofGetTimestampString() + ".png")).string()))
            message = "Screenshot saved";
        else
            message = "Screenshot failed";
    }
    void pollOsc() {
        if (sock < 0)
            return;
        uint8_t data[4096];
        for (int i = 0; i < 128; ++i) {
            auto n = recv(sock, data, sizeof(data), MSG_DONTWAIT);
            if (n <= 0)
                break;
            eyesy::OscEvent e;
            if (!eyesy::decodeOsc(data, n, e))
                continue;
            if (e.address == "/knobs" && e.integers.size() == 6)
                for (int k = 0; k < 5; ++k) {
                    knobs[k] = std::clamp(e.integers[k] / 1023.0, 0.0, 1.0);
                    recordEvent({frame, "knob", k + 1, 0, 0, 0, 0, 0, knobs[k]});
                }
            if (e.address == "/key" && e.integers.size() == 2)
                hardwareKey(e.integers[0], e.integers[1] > 0);
            if (e.address == "/reload")
                loadMode(selected);
            if (e.address == "/screengrab")
                screenshot();
        }
    }
    void pollMidi() {
        if (!seq)
            return;
        if (ofGetElapsedTimef() - lastMidiScan > 2) {
            lastMidiScan = ofGetElapsedTimef();
            std::set<std::pair<int, int>> seen;
            snd_seq_client_info_t *client;
            snd_seq_client_info_alloca(&client);
            snd_seq_client_info_set_client(client, -1);
            while (snd_seq_query_next_client(seq, client) >= 0) {
                int c = snd_seq_client_info_get_client(client);
                if (c == snd_seq_client_id(seq) || c == 0)
                    continue;
                snd_seq_port_info_t *port;
                snd_seq_port_info_alloca(&port);
                snd_seq_port_info_set_client(port, c);
                snd_seq_port_info_set_port(port, -1);
                while (snd_seq_query_next_port(seq, port) >= 0) {
                    auto cap = snd_seq_port_info_get_capability(port);
                    int p = snd_seq_port_info_get_port(port);
                    if ((cap & (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ)) ==
                        (SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_SUBS_READ)) {
                        auto pair = std::make_pair(c, p);
                        seen.insert(pair);
                        if (!subscriptions.count(pair))
                            snd_seq_connect_from(seq, seqPort, c, p);
                    }
                }
            }
            if (seen != subscriptions)
                midi.notes.fill(0);
            subscriptions = std::move(seen);
        }
        snd_seq_event_t *e = nullptr;
        for (int i = 0; i < 128 && snd_seq_event_input(seq, &e) >= 0; ++i) {
            eyesy::MidiEvent m;
            switch (e->type) {
            case SND_SEQ_EVENT_NOTEON:
                m = {0x90, e->data.note.channel, e->data.note.note, e->data.note.velocity};
                break;
            case SND_SEQ_EVENT_NOTEOFF:
                m = {0x80, e->data.note.channel, e->data.note.note, 0};
                break;
            case SND_SEQ_EVENT_CONTROLLER:
                m = {0xb0, e->data.control.channel, int(e->data.control.param),
                     e->data.control.value};
                break;
            case SND_SEQ_EVENT_CLOCK:
                m.type = 0xf8;
                break;
            case SND_SEQ_EVENT_START:
                m.type = 0xfa;
                break;
            case SND_SEQ_EVENT_CONTINUE:
                m.type = 0xfb;
                break;
            case SND_SEQ_EVENT_STOP:
                m.type = 0xfc;
                break;
            default:
                break;
            }
            m.timestamp = ofGetElapsedTimef();
            if (m.type >= 0xf0 || m.channel == midiChannel - 1) {
                midi.apply(m);
                midiEvents.push_back(m);
                recordEvent({frame, "midi", 0, 0, m.type, m.channel, m.a, m.b, 0});
                if (m.type == 0x90 && m.b && (triggerSource == 1 || triggerSource == 2))
                    trigger = true;
                if (m.type == 0xf8 && triggerSource == 3 && midi.clocks % 24 == 0)
                    trigger = true;
                if (m.type == 0xb0 && m.a >= 20 && m.a <= 24)
                    knobs[m.a - 20] = std::clamp(m.b / 127.0, 0.0, 1.0);
            }
            snd_seq_free_event(e);
        }
    }
    ofJson status() {
        std::ifstream memory("/proc/self/statm");
        uint64_t pages = 0, resident = 0;
        memory >> pages >> resident;
        ofJson report = {{"schema_version", 1},
                         {"rss_bytes", resident * uint64_t(sysconf(_SC_PAGESIZE))},
                         {"release", std::getenv("EYESY_RELEASE") ? std::getenv("EYESY_RELEASE")
                                                                  : "development"},
                         {"frame", frame},
                         {"mode", runtime.directory.filename().string()},
                         {"error", runtime.error},
                         {"shader_warning", runtime.shaderWarning},
                         {"renderer", renderer},
                         {"offscreen", options.offscreen},
                         {"fps", ofGetFrameRate()},
                         {"resources", runtime.resourceCount()},
                         {"reloads", reloads},
                         {"mode_errors", modeErrors},
                         {"audio_dropped", audio.dropped()},
                         {"mode_fallback", kmsModeFallbackNote()}};
        const auto &a = lastAnalysis;
        report["audio_available"] = a.available;
        report["audio_sample_rate"] = a.sampleRate;
        report["audio_rms_left"] = a.rmsL;
        report["audio_rms_right"] = a.rmsR;
        report["audio_sequence"] = a.sequence;
        report["audio_source"] =
            options.audioWav.empty() ? (options.device == -1 ? "synthetic" : "device") : "wav";
        report["recorded_events"] = recorder.size();
        report["recording_truncated"] = recorder.truncated();
        report["frame_time_samples"] = frameTimes.size();
        report["frame_time_window"] = 4096;
        return report;
    }

  public:
    explicit EngineApp(Options o) : options(std::move(o)), recorder(options.recordLimit) {}
    void setup() override {
        ofSetFrameRate(60);
        ofSetVerticalSync(true);
        ofDisableArbTex();
        ofSetWindowTitle("EYESY Platform");
        renderer = reinterpret_cast<const char *>(glGetString(GL_RENDERER));
        ofLogNotice() << "Renderer: " << renderer;
        ofFbo::Settings settings;
        settings.width = 1280;
        settings.height = 720;
        settings.internalformat = GL_RGBA;
        settings.textureTarget = GL_TEXTURE_2D;
        settings.useDepth = true;
        canvas.allocate(settings);
        canvas.begin();
        ofClear(0, 0, 0, 255);
        canvas.end();
        fs::create_directories(options.storage);
        if (fs::exists(options.storage / "config.json"))
            try {
                auto config = ofLoadJson((options.storage / "config.json").string());
                if (config.at("schema_version") != 1)
                    throw std::runtime_error("unsupported settings");
                audioGain = std::clamp(config.value("audio_gain", 1.0), 0.0, 4.0);
                midiChannel = std::clamp(config.value("midi_channel", 1), 1, 16);
                triggerSource = std::clamp(config.value("trigger_source", 2), 0, 3);
            } catch (const std::exception &e) {
                message = std::string("Settings ignored: ") + e.what();
            }
        audio.setGain(audioGain);
        if (options.port) {
            sock = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(options.port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (sock < 0 || bind(sock, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
                throw std::runtime_error("OSC port unavailable; another engine may be active");
        }
        deterministic = !options.replay.empty();
        if (deterministic && !options.audioWav.empty())
            throw std::runtime_error("--audio-wav cannot be combined with deterministic --replay");
        if (deterministic && !options.record.empty())
            throw std::runtime_error("--record cannot be combined with --replay");
        if (deterministic) {
            if (fs::file_size(options.replay) > 16ull * 1024 * 1024)
                throw std::runtime_error("replay exceeds 16 MiB limit");
            replayEvents = ofLoadJson(options.replay.string());
            if (!replayEvents.is_array())
                throw std::runtime_error("replay must be an event array");
            if (replayEvents.size() > 100000)
                throw std::runtime_error("replay exceeds 100000 event limit");
            uint64_t previous = 0;
            for (auto &e : replayEvents) {
                auto f = e.at("frame").get<uint64_t>();
                if (!e.at("frame").is_number_integer() || e.at("frame").get<int64_t>() < 0 ||
                    f > 5184000)
                    throw std::runtime_error(
                        "replay frame must be an integer within 24 hours at 60fps");
                if (f < previous)
                    throw std::runtime_error("replay events must be ordered");
                eyesy::RecordedInput v;
                v.frame = f;
                v.type = e.at("type").get<std::string>();
                if (v.type == "knob") {
                    v.index = e.at("index").get<int>();
                    v.value = e.at("value").get<double>();
                } else if (v.type == "key" || v.type == "key_release" || v.type == "hardware_key" ||
                           v.type == "hardware_release")
                    v.key = e.at("key").get<int>();
                else if (v.type == "midi") {
                    v.status = e.at("status").get<int>();
                    v.channel = e.value("channel", 0);
                    v.a = e.value("a", 0);
                    v.b = e.value("b", 0);
                } else if (v.type == "audio") {
                    v.gain = e.value("gain", 1.0);
                    v.freq = e.value("freq", 1.0);
                }
                std::string validationError;
                if (!eyesy::validReplayEvent(v, validationError))
                    throw std::runtime_error(validationError);
                previous = f;
            }
        } else if (!options.audioWav.empty()) {
            std::string error;
            if (!audio.startWav(options.audioWav, error))
                throw std::runtime_error("WAV input unavailable: " + error);
        } else if (!audio.start(options.device))
            message = "Audio input unavailable";
        if (snd_seq_open(&seq, "default", SND_SEQ_OPEN_INPUT, SND_SEQ_NONBLOCK) >= 0) {
            snd_seq_set_client_name(seq, "EYESY Platform");
            seqPort = snd_seq_create_simple_port(
                seq, "input", SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
                SND_SEQ_PORT_TYPE_APPLICATION);
        } else
            seq = nullptr;
        if (!options.probe) {
            auto root = options.mode.parent_path();
            for (auto &e : fs::directory_iterator(root))
                if (e.is_directory() && fs::exists(e.path() / "main.lua"))
                    catalog.push_back(e.path());
            std::sort(catalog.begin(), catalog.end());
            auto it = std::find(catalog.begin(), catalog.end(), options.mode);
            loadMode(it == catalog.end() ? 0 : it - catalog.begin());
        }
        for (int k = 0; k < 5; ++k)
            recordEvent({0, "knob", k + 1, 0, 0, 0, 0, 0, knobs[k]});
        notify("READY=1");
        lastFrame = ofGetElapsedTimef();
    }
    void update() override {
        if (terminateRequested) {
            ofExit(0);
            return;
        }
        double wall = ofGetElapsedTimef(), elapsed = std::clamp(wall - lastFrame, 0.0, .25);
        lastFrame = wall;
        double now = deterministic ? frame / 60.0 : wall, dt = deterministic ? 1.0 / 60 : elapsed;
        if (frame > 5)
            frameTimes.push_back(elapsed * 1000);
        if (frameTimes.size() > 4096)
            frameTimes.erase(frameTimes.begin(), frameTimes.begin() + 1024);
        if (!deterministic) {
            pollOsc();
            pollMidi();
        }
        while (replayIndex < replayEvents.size() &&
               replayEvents[replayIndex].at("frame").get<uint64_t>() <= frame) {
            auto e = replayEvents[replayIndex++];
            auto type = e.at("type").get<std::string>();
            if (type == "knob") {
                int index = e.at("index").get<int>();
                double value = e.at("value").get<double>();
                if (index < 1 || index > 5 || !std::isfinite(value))
                    throw std::runtime_error("invalid replay knob");
                knobs[index - 1] = std::clamp(value, 0.0, 1.0);
            } else if (type == "key")
                keyPressed(e.at("key").get<int>());
            else if (type == "hardware_key")
                hardwareKey(e.at("key").get<int>(), true);
            else if (type == "key_release")
                keyReleased(e.at("key").get<int>());
            else if (type == "hardware_release")
                hardwareKey(e.at("key").get<int>(), false);
            else if (type == "midi") {
                eyesy::MidiEvent m{e.at("status").get<int>(), e.value("channel", 0),
                                   e.value("a", 0), e.value("b", 0), now};
                if (m.type >= 0xf0 || m.channel == midiChannel - 1) {
                    midi.apply(m);
                    midiEvents.push_back(m);
                    if (m.type == 0x90 && m.b && (triggerSource == 1 || triggerSource == 2))
                        trigger = true;
                    if (m.type == 0xf8 && triggerSource == 3 && midi.clocks % 24 == 0)
                        trigger = true;
                    if (m.type == 0xb0 && m.a >= 20 && m.a <= 24)
                        knobs[m.a - 20] = std::clamp(m.b / 127.0, 0.0, 1.0);
                }
            } else if (type == "audio") {
                replayGain = std::clamp(e.value("gain", 1.0), 0.0, 4.0);
                replayFreq = std::clamp(e.value("freq", 1.0), 0.25, 4.0);
            } else
                throw std::runtime_error("unknown replay event");
        }
        auto a = audio.snapshot();
        if (!deterministic && options.audioWav.empty() && options.device != -1 && !a.available &&
            wall > audioRetry) {
            audioRetry = wall + 5;
            audio.start(options.device);
        }
        if (deterministic) {
            std::array<eyesy::StereoFrame, eyesy::fftSize> samples;
            for (size_t i = 0; i < samples.size(); ++i) {
                double t = now + i / 48000.0;
                samples[i] = {float(replayGain * .5 * std::sin(t * TWO_PI * 220 * replayFreq)),
                              float(replayGain * .5 * std::sin(t * TWO_PI * 440 * replayFreq))};
            }
            a = eyesy::analyze(samples, 48000);
            a.timestamp = now;
        }
        if (a.triggerCount != triggerCount) {
            trigger = trigger ||
                      ((triggerSource == 0 || triggerSource == 2) && a.triggerCount > triggerCount);
            triggerCount = a.triggerCount;
        }
        lastAnalysis = a;
        if (!options.probe) {
            runtime.snapshot(now, dt, knobs, a, midi, trigger, midiEvents);
            runtime.call("update", dt);
        }
        if (wall - lastWatch > .3 && !options.probe) {
            lastWatch = wall;
            bool changed = false, onlyShaders = true;
            for (auto &p : watched)
                if (!fs::exists(p.first) || fs::last_write_time(p.first) != p.second) {
                    changed = true;
                    onlyShaders = onlyShaders && (p.first.extension() == ".frag");
                }
            if (changed) {
                if (onlyShaders) {
                    runtime.reloadShaders();
                    message = runtime.shaderWarning;
                    watchFiles();
                } else
                    loadMode(selected);
            }
        }
        if (options.switchEvery && frame && frame % options.switchEvery == 0)
            loadMode(selected + 1);
        if (wall - lastStatus > 1) {
            lastStatus = wall;
            atomicJson(options.storage / "status.json", status());
            notify("WATCHDOG=1");
        }
    }
    void draw() override {
        canvas.begin();
        if (autoClear)
            ofClear(0, 0, 0, 255);
        if (options.probe) {
            ofSetColor(40, 160, 255);
            ofDrawCircle(640 + std::sin(ofGetElapsedTimef()) * 300, 360, 100);
            ofSetColor(255);
            ofDrawBitmapString("EYESY GPU / AUDIO PROBE\n" + renderer, 20, 30);
        } else if (runtime.error.empty()) {
            if (!runtime.call("draw"))
                ++modeErrors;
        } else {
            ofClear(24, 8, 12);
            ofSetColor(255, 100, 120);
            ofDrawBitmapString(
                "MODE ERROR\n" + runtime.error + "\nR: reload    Left/Right: switch mode", 30, 60);
        }
        canvas.end();
        ofSetColor(255);
        canvas.draw(0, 0, ofGetWidth(), ofGetHeight());
        if (osd) {
            ofSetColor(0, 0, 0, 190);
            ofDrawRectangle(0, ofGetHeight() - 64, ofGetWidth(), 64);
            ofSetColor(255);
            std::ostringstream line;
            line << "EYESY | " << runtime.directory.filename().string() << " | " << std::fixed
                 << std::setprecision(1) << ofGetFrameRate() << " fps | knob " << selectedKnob + 1
                 << ": " << knobs[selectedKnob] << "\n"
                 << message;
            ofDrawBitmapString(line.str(), 16, ofGetHeight() - 40);
        }
        trigger = false;
        midiEvents.clear();
        ++frame;
        if (options.frames && frame >= uint64_t(options.frames))
            ofExit(runtime.error.empty() ? 0 : 2);
    }
    void keyPressed(int key) override {
        if (!deterministic)
            recordEvent({frame, "key", 0, key});
        if (key == 'm') {
            menu = !menu;
            osd = true;
            if (menu)
                settingsText();
            else
                message.clear();
            return;
        }
        if (menu) {
            if (key == OF_KEY_UP)
                settingsKey(6);
            if (key == OF_KEY_DOWN)
                settingsKey(7);
            if (key == OF_KEY_LEFT)
                settingsKey(4);
            if (key == OF_KEY_RIGHT)
                settingsKey(5);
            if (key == OF_KEY_RETURN)
                settingsKey(8);
            return;
        }
        if (key >= '1' && key <= '5')
            selectedKnob = key - '1';
        if (key == OF_KEY_UP)
            knobs[selectedKnob] = std::min(1.0, knobs[selectedKnob] + .02);
        if (key == OF_KEY_DOWN)
            knobs[selectedKnob] = std::max(0.0, knobs[selectedKnob] - .02);
        if (key == OF_KEY_LEFT)
            loadMode(selected - 1);
        if (key == OF_KEY_RIGHT)
            loadMode(selected + 1);
        if (key == 'r')
            loadMode(selected);
        if (key == ' ')
            trigger = true;
        if (key == 'o')
            osd = !osd;
        if (key == 'c')
            autoClear = !autoClear;
        if (key == 's')
            saveScene();
        if (key == '[')
            recallScene(-1);
        if (key == ']')
            recallScene(1);
        if (key == 'g')
            screenshot();
        if (key == 'n') {
            midi.apply({0x90, 0, 60, 100});
            trigger = true;
        }
    }
    void keyReleased(int key) override {
        if (!deterministic)
            recordEvent({frame, "key_release", 0, key});
        if (key == 'n')
            midi.apply({0x80, 0, 60, 0});
    }
    void exit() override {
        auto report = status();
        std::sort(frameTimes.begin(), frameTimes.end());
        if (!frameTimes.empty()) {
            report["p50_ms"] = frameTimes[frameTimes.size() / 2];
            report["p95_ms"] = frameTimes[size_t((frameTimes.size() - 1) * .95)];
            report["p99_ms"] = frameTimes[size_t((frameTimes.size() - 1) * .99)];
        }
        if (!options.report.empty())
            atomicJson(options.report, report);
        atomicJson(options.storage / "status.json", report);
        if (options.frames)
            screenshot();
        writeRecording();
        audio.stop();
        runtime.close();
        if (sock >= 0)
            close(sock);
        if (seq)
            snd_seq_close(seq);
    }
};
int main(int argc, char **argv) {
    Options o;
    try {
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            auto next = [&]() {
                if (i + 1 >= argc)
                    throw std::runtime_error("missing value for " + arg);
                return std::string(argv[++i]);
            };
            if (arg == "--mode")
                o.mode = fs::absolute(next());
            else if (arg == "--storage")
                o.storage = fs::absolute(next());
            else if (arg == "--frames")
                o.frames = std::stoi(next());
            else if (arg == "--audio-device") {
                auto device = next();
                o.device = device == "auto" ? -2 : std::stoi(device);
            } else if (arg == "--osc-port")
                o.port = std::stoi(next());
            else if (arg == "--report")
                o.report = fs::absolute(next());
            else if (arg == "--replay")
                o.replay = fs::absolute(next());
            else if (arg == "--audio-wav")
                o.audioWav = fs::absolute(next());
            else if (arg == "--record")
                o.record = fs::absolute(next());
            else if (arg == "--record-limit")
                o.recordLimit = std::stoul(next());
            else if (arg == "--switch-every")
                o.switchEvery = std::stoi(next());
            else if (arg == "--fullscreen")
                o.fullscreen = true;
            else if (arg == "--offscreen")
                o.offscreen = true;
            else if (arg == "--kms")
                o.kms = true;
            else
                throw std::runtime_error("unknown argument: " + arg);
        }
        if (!o.probe && !fs::exists(o.mode / "main.lua"))
            throw std::runtime_error("--mode must name a folder containing main.lua");
        if (!o.recordLimit || o.recordLimit > 100000)
            throw std::runtime_error("--record-limit must be 1..100000");
        if (o.frames < 0 || o.switchEvery < 0 || o.port < 0 || o.port > 65535 || o.device < -2)
            throw std::runtime_error(
                "invalid frame count, switch interval, audio device or OSC port");
        ofGLFWWindowSettings settings;
#ifdef TARGET_OPENGLES
        settings.setGLESVersion(2);
#else
        settings.setGLVersion(3, 2);
#endif
        settings.setSize(1280, 720);
        settings.windowMode = o.fullscreen ? OF_FULLSCREEN : OF_WINDOW;
        auto window = o.kms ? createKmsWindow()
                            : o.offscreen ? createOffscreenWindow(1280, 720)
                                          : ofCreateWindow(settings);
        // ofInit (called by every window factory) installs OF's handler, which
        // surfaces SIGTERM as a nonzero exit; replace it for the loop below.
        std::signal(SIGTERM, requestTermination);
        ofRunApp(window, std::make_shared<EngineApp>(o));
        return ofRunMainLoop();
    } catch (const std::exception &e) {
        std::cerr << "eyesy: " << e.what() << '\n';
        return 1;
    }
}
