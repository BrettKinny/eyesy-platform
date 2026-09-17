#include "audio.h"
#include "kms_window.h"
#include "knob_sequencer.h"
#include "menu_system.h"
#include "offscreen_window.h"
#include "osd_hud.h"
#include "runtime.h"
#include <alsa/asoundlib.h>
#include <arpa/inet.h>
#include <csignal>
#include <fcntl.h>
#include <fstream>
#include <set>
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
    std::string videoMode;
    int frames = 0, device = -1, port = 0, ledPort = 4001, switchEvery = 0;
    bool fullscreen = false, probe = false, offscreen = false, kms = false;
    size_t recordLimit = 10000;
};
// Status LED colors the eyesyhw daemon understands on OSC /led.
constexpr int LED_WHITE = 7, LED_MAGENTA = 6, LED_RED = 1, LED_GREEN = 3;
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
    int selected = 0, sceneIndex = -1, selectedKnob = 0, sock = -1, ledSock = -1, ledState = -1;
    uint64_t frame = 0, triggerCount = 0, reloads = 0, modeErrors = 0;
    double lastFrame = 0, lastWatch = 0, lastStatus = 0;
    bool trigger = false, osd = true, autoClear = true, shift = false;
    std::array<int, 11> keyHeldTicks{};
    double savePressTime = 0;
    bool saveHeld = false;
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
    MenuSystem menu;
    MenuSettings settings;
    MenuTelemetry telemetry;
    uint64_t pressCount = 0;
    double audioRetry = 0;
    double gainKnobCapture = 0, gainSnapshot = 1;
    bool gainKnobUnlocked = false;
    void persistSettings() {
        atomicJson(options.storage / "config.json", {{"schema_version", 1},
                                                     {"audio_gain", settings.gain},
                                                     {"midi_channel", settings.midiChannel},
                                                     {"trigger_source", settings.triggerSource},
                                                     {"fg_palette", int(palettes.fg())},
                                                     {"bg_palette", int(palettes.bg())},
                                                     {"video_mode", settings.videoMode}});
    }
    void recordEvent(const eyesy::RecordedInput &event) {
        if (!options.record.empty())
            recorder.record(event);
    }
    eyesy::KnobSequencer knobSeq;
    eyesy::PaletteManager palettes;
    OsdHud hud;
    HudState hudState;
    void handleMenuKey(int key, MenuSystem::Key mapped = MenuSystem::Key::Other) {
        if (mapped == MenuSystem::Key::Other) {
            if (key == 6)
                mapped = MenuSystem::Key::Up;
            else if (key == 7)
                mapped = MenuSystem::Key::Down;
            else if (key == 4)
                mapped = MenuSystem::Key::Decrease;
            else if (key == 5)
                mapped = MenuSystem::Key::Increase;
            else if (key == 8)
                mapped = MenuSystem::Key::Confirm;
            else if (key == 1)
                mapped = MenuSystem::Key::Back;
        }
        menu.key(mapped, settings, palettes);
        audio.setGain(float(settings.gain));
        if (!menu.active()) {
            try {
                persistSettings();
            } catch (const std::exception &e) {
                message = e.what();
            }
        }
    }
    void refreshHud() {
        hudState.mode = runtime.directory.filename().string();
        hudState.modeIndex = selected;
        hudState.modeCount = int(catalog.size());
        hudState.sceneLoaded = sceneIndex >= 0 && sceneIndex < int(scenes.size());
        // Our scenes are single timestamped files, so the HUD shows the stem
        // clipped to the space the stock folder name occupies.
        hudState.scene = hudState.sceneLoaded
                             ? scenes[sceneIndex].stem().string().substr(0, 22)
                             : std::string();
        hudState.sceneIndex = sceneIndex;
        hudState.sceneCount = int(scenes.size());
        hudState.width = ofGetWidth();
        hudState.height = ofGetHeight();
        hudState.usb = false;
        hudState.knobs = knobs;
        hudState.sequencer = knobSeq.playing() ? 2 : knobSeq.recording() ? 1 : 0;
        hudState.notes = &midi.notes;
        hudState.peakLeft = lastAnalysis.peakL;
        hudState.peakRight = lastAnalysis.peakR;
        hudState.gain = settings.gain;
        hudState.trigger = trigger;
        hudState.persist = !autoClear;
        hudState.fps = ofGetFrameRate();
        hudState.fgPreview = palettes.preview(true);
        hudState.bgPreview = palettes.preview(false);
        telemetry.knobs = knobs;
        telemetry.peakLeft = lastAnalysis.peakL;
        telemetry.peakRight = lastAnalysis.peakR;
        telemetry.notes = midi.notes;
        telemetry.trigger = trigger;
        telemetry.width = ofGetWidth();
        telemetry.height = ofGetHeight();
        telemetry.mode = hudState.mode;
        telemetry.scene = hudState.scene;
        telemetry.modeIndex = selected;
        telemetry.modeCount = int(catalog.size());
        telemetry.sceneIndex = sceneIndex;
        telemetry.sceneCount = int(scenes.size());
        telemetry.fps = ofGetFrameRate();
        telemetry.videoNote = kmsModeFallbackNote();
        telemetry.presses = pressCount;
    }
    // System/palettes.json replaces the embedded stock table when present.
    void loadPalettes() {
        auto path = options.storage / "System" / "palettes.json";
        if (!fs::exists(path))
            return;
        auto data = ofLoadJson(path.string());
        if (!data.is_array() || data.empty())
            return;
        std::vector<eyesy::CosinePalette> parsed;
        const char *keys[] = {"a", "b", "c", "d"};
        for (auto &entry : data) {
            if (!entry.is_object() || !entry.contains("name") || !entry["name"].is_string())
                return;
            eyesy::CosinePalette palette;
            palette.name = entry["name"].get<std::string>();
            std::array<float, 3> *slots[] = {&palette.a, &palette.b, &palette.c, &palette.d};
            for (int i = 0; i < 4; ++i) {
                if (!entry.contains(keys[i]) || !entry[keys[i]].is_array() ||
                    entry[keys[i]].size() != 3)
                    return;
                for (int channel = 0; channel < 3; ++channel) {
                    if (!entry[keys[i]][channel].is_number())
                        return;
                    (*slots[i])[channel] = float(entry[keys[i]][channel].get<double>());
                }
            }
            parsed.push_back(std::move(palette));
        }
        if (palettes.replace(std::move(parsed)))
            message = "Loaded " + path.filename().string();
    }
    void cyclePalette(int key) {
        if (key == 4)
            palettes.prevFg();
        if (key == 5)
            palettes.nextFg();
        if (key == 6)
            palettes.prevBg();
        if (key == 7)
            palettes.nextBg();
        if (key >= 4 && key <= 7)
            message = std::string(key <= 5 ? "FG" : "BG") + " palette: " +
                      palettes.entries()[key <= 5 ? palettes.fg() : palettes.bg()].name;
    }
    void syncLed() {
        sendLed(knobSeq.playing()          ? LED_GREEN
                : knobSeq.recording()      ? LED_RED
                : knobSeq.state() == eyesy::KnobSequencer::State::Enabled ? LED_MAGENTA
                                                                          : LED_WHITE);
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
    // Report the hardware status LED to eyesyhw (OSC /led on its input port,
    // 4001; the engine's own OSC receive port is 4000).
    void sendLed(int color) {
        if (ledSock < 0 || color == ledState)
            return;
        ledState = color;
        std::vector<uint8_t> packet;
        if (eyesy::encodeOscInt("/led", color, packet))
            send(ledSock, packet.data(), packet.size(), MSG_NOSIGNAL);
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
        runtime.snapshot(ofGetElapsedTimef(), 0, knobs, audio.snapshot(), midi, trigger, autoClear);
        ++reloads;
        watchFiles();
        canvas.begin();
        ofClear(0, 0, 0, 255);
        canvas.end();
    }
    void hardwareKey(int key, bool down) {
        if (!deterministic)
            recordEvent({frame, down ? "hardware_key" : "hardware_release", 0, key});
        if (key >= 0 && key < int(keyHeldTicks.size()))
            keyHeldTicks[key] = down ? 1 : 0;
        if (key == 2) {
            shift = down;
            if (down) {
                // Grab the physical knob 1 so a small move unlocks the takeover.
                gainKnobCapture = knobs[0];
                gainKnobUnlocked = false;
                gainSnapshot = settings.gain;
            } else if (gainSnapshot != settings.gain) {
                try {
                    persistSettings();
                } catch (const std::exception &) {
                }
            }
            return;
        }
        if (key == 10)
            audio.setSynthesizing(down);
        if (key == 8) {
            if (down) {
                if (!shift) {
                    savePressTime = ofGetElapsedTimef();
                    saveHeld = true;
                }
            } else if (saveHeld) {
                saveHeld = false;
                if (!shift)
                    saveScene();
            }
        }
        if (!down)
            return;
        pressCount++;
        if (menu.active()) {
            handleMenuKey(key);
            return;
        }
        if (shift) {
            if (key == 1) {
                menu.toggle();
                osd = true;
                message.clear();
            }
            if (key == 8)
                updateCurrentScene();
            if (key == 9)
                knobSeq.playStopKey();
            if (key == 10)
                knobSeq.recordKey(knobs);
            if (key >= 4 && key <= 7)
                cyclePalette(key);
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
        if (key == 9)
            screenshot();
        if (key == 10)
            trigger = true;
    }
    ofJson sceneJson() {
        ofJson j = {{"schema_version", 1},
                    {"mode", runtime.directory.filename().string()},
                    {"parameters", ofJson::object()},
                    {"state", runtime.save()},
                    {"auto_clear", autoClear},
                    {"fg_palette", int(palettes.fg())},
                    {"bg_palette", int(palettes.bg())}};
        for (auto &p : runtime.parameters)
            j["parameters"][p.first] = p.second.value;
        // Stock stores the sequence beside the scene only while it is playing;
        // a stopped sequence is dropped on the next save.
        if (knobSeq.playing())
            j["knob_sequence"] = knobSeq.sequence();
        return j;
    }
    void refreshScenes() {
        scenes.clear();
        auto folder = options.storage / "scenes";
        if (fs::exists(folder))
            for (auto &entry : fs::directory_iterator(folder))
                if (entry.path().extension() == ".json")
                    scenes.push_back(entry.path());
        std::sort(scenes.begin(), scenes.end());
    }
    void saveScene() {
        try {
            auto path = options.storage / "scenes" /
                        ("scene-" + ofGetTimestampString("%Y%m%d-%H%M%S-%i") + ".json");
            atomicJson(path, sceneJson());
            refreshScenes();
            auto it = std::find(scenes.begin(), scenes.end(), path);
            if (it != scenes.end())
                sceneIndex = it - scenes.begin();
            message = "Saved " + path.filename().string();
        } catch (const std::exception &e) {
            message = e.what();
        }
    }
    void updateCurrentScene() {
        try {
            if (sceneIndex < 0 || sceneIndex >= int(scenes.size())) {
                message = "No scene to update";
                return;
            }
            atomicJson(scenes[sceneIndex], sceneJson());
            message = "Updated " + scenes[sceneIndex].filename().string();
        } catch (const std::exception &e) {
            message = e.what();
        }
    }
    void deleteCurrentScene() {
        if (sceneIndex < 0 || sceneIndex >= int(scenes.size())) {
            message = "No scene to delete";
            return;
        }
        auto removed = scenes[sceneIndex];
        std::error_code error;
        fs::remove(removed, error);
        if (error) {
            message = error.message();
            return;
        }
        scenes.erase(scenes.begin() + sceneIndex);
        if (scenes.empty()) {
            sceneIndex = -1;
            message = "Deleted scene (none left)";
            return;
        }
        // Stock steps to the same slot, then clamps; keep that ordering.
        if (sceneIndex >= int(scenes.size()))
            sceneIndex = int(scenes.size()) - 1;
        recallScene(0);
        message = "Deleted " + removed.filename().string();
    }
    void recallScene(int direction) {
        try {
            refreshScenes();
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
            palettes.setFg(j.value("fg_palette", int(palettes.fg())));
            palettes.setBg(j.value("bg_palette", int(palettes.bg())));
            runtime.restore(j.value("state", ofJson::object()));
            bool restored = false;
            if (j.contains("knob_sequence") && j["knob_sequence"].is_array()) {
                std::vector<std::array<double, 5>> data;
                bool valid = true;
                for (auto &frame : j["knob_sequence"]) {
                    if (!frame.is_array() || frame.size() != 5) {
                        valid = false;
                        break;
                    }
                    std::array<double, 5> values{};
                    for (size_t i = 0; i < values.size(); ++i) {
                        if (!frame[i].is_number()) {
                            valid = false;
                            break;
                        }
                        values[i] = frame[i].get<double>();
                    }
                    if (!valid)
                        break;
                    data.push_back(values);
                }
                restored = valid && knobSeq.load(data, true);
            }
            if (!restored)
                knobSeq.clear();
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
            if (e.address == "/knobs" && e.integers.size() == 6) {
                std::array<double, 5> next{};
                for (int k = 0; k < 5; ++k)
                    next[k] = std::clamp(e.integers[k] / 1023.0, 0.0, 1.0);
                if (shift) {
                    // Shift + Knob 1 takes over live audio input gain; the mode
                    // parameter stays parked until shift is released.
                    if (std::abs(gainKnobCapture - next[0]) > .05)
                        gainKnobUnlocked = true;
                    double requested =
                        gainKnobUnlocked ? std::clamp(next[0] * 4.0, 0.0, 4.0) : settings.gain;
                    if (std::abs(requested - settings.gain) > .01) {
                        settings.gain = requested;
                        audio.setGain(float(settings.gain));
                        message = "Audio gain " + ofToString(settings.gain, 2) + "x";
                    }
                    next[0] = knobs[0];
                }
                knobs = next;
                for (int k = 0; k < 5; ++k)
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
            if (m.type >= 0xf0 || m.channel == settings.midiChannel - 1) {
                midi.apply(m);
                midiEvents.push_back(m);
                recordEvent({frame, "midi", 0, 0, m.type, m.channel, m.a, m.b, 0});
                if (m.type == 0x90 && m.b && (settings.triggerSource == 1 || settings.triggerSource == 2))
                    trigger = true;
                if (m.type == 0xf8 && settings.triggerSource == 3 && midi.clocks % 24 == 0)
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
        report["audio_synthesizing"] = audio.isSynthesizing();
        report["led"] = ledState;
        report["sequencer"] = knobSeq.playing()          ? "playing"
                              : knobSeq.recording()      ? "recording"
                              : knobSeq.state() == eyesy::KnobSequencer::State::Enabled ? "enabled"
                                                                                        : "stopped";
        report["sequencer_frames"] = knobSeq.size();
        report["fg_palette"] = int(palettes.fg());
        report["bg_palette"] = int(palettes.bg());
        report["palette_count"] = int(palettes.size());
        report["hud_draw_calls"] = hud.drawCalls();
        report["mode_index"] = selected;
        report["mode_count"] = int(catalog.size());
        report["scene_index"] = sceneIndex;
        report["scene_count"] = int(scenes.size());
        report["scene"] = sceneIndex >= 0 && sceneIndex < int(scenes.size())
                              ? scenes[sceneIndex].stem().string()
                              : std::string();
        report["video_mode"] = settings.videoMode;
        report["auto_clear"] = autoClear;
        report["osd"] = osd;
        report["menu_screen"] = menu.active() ? menu.screen() : -1;
        report["menu_row"] = menu.active() ? menu.row() : -1;
        auto diagnostics = menu.diagnostics();
        report["diagnostics"] = {{"pots", diagnostics[0]},
                                 {"buttons", diagnostics[1]},
                                 {"midi", diagnostics[2]},
                                 {"audio", diagnostics[3]}};
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
        ofFbo::Settings fboSettings;
        fboSettings.width = 1280;
        fboSettings.height = 720;
        fboSettings.internalformat = GL_RGBA;
        fboSettings.textureTarget = GL_TEXTURE_2D;
        fboSettings.useDepth = true;
        canvas.allocate(fboSettings);
        canvas.begin();
        ofClear(0, 0, 0, 255);
        canvas.end();
        fs::create_directories(options.storage);
        if (fs::exists(options.storage / "config.json"))
            try {
                auto config = ofLoadJson((options.storage / "config.json").string());
                if (config.at("schema_version") != 1)
                    throw std::runtime_error("unsupported settings");
                settings.gain = std::clamp(config.value("audio_gain", 1.0), 0.0, 4.0);
                settings.midiChannel = std::clamp(config.value("midi_channel", 1), 1, 16);
                settings.triggerSource = std::clamp(config.value("trigger_source", 2), 0, 3);
                palettes.setFg(size_t(std::max(0, config.value("fg_palette", 0))));
                palettes.setBg(size_t(std::max(0, config.value("bg_palette", 0))));
                // A --video-mode argument wins over the stored preference.
                if (options.videoMode.empty())
                    settings.videoMode = config.value("video_mode", std::string());
            } catch (const std::exception &e) {
                message = std::string("Settings ignored: ") + e.what();
            }
        audio.setGain(settings.gain);
        loadPalettes();
        runtime.setPalettes(&palettes);
        if (options.port) {
            sock = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(options.port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (sock < 0 || bind(sock, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
                throw std::runtime_error("OSC port unavailable; another engine may be active");
        }
        ledSock = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
        if (ledSock >= 0) {
            sockaddr_in led{};
            led.sin_family = AF_INET;
            led.sin_port = htons(options.ledPort);
            led.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            if (connect(ledSock, reinterpret_cast<sockaddr *>(&led), sizeof(led)) < 0) {
                close(ledSock);
                ledSock = -1;
            }
        }
        sendLed(LED_WHITE);
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
                if (m.type >= 0xf0 || m.channel == settings.midiChannel - 1) {
                    midi.apply(m);
                    midiEvents.push_back(m);
                    if (m.type == 0x90 && m.b && (settings.triggerSource == 1 || settings.triggerSource == 2))
                        trigger = true;
                    if (m.type == 0xf8 && settings.triggerSource == 3 && midi.clocks % 24 == 0)
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
        if (saveHeld && !shift && wall - savePressTime >= 1.0) {
            saveHeld = false;
            deleteCurrentScene();
        }
        // Held scroll keys repeat after ~200ms, then every 50ms (stock key matrix).
        // Stock suspends the repeater entirely while the menu is up.
        for (int key : {4, 5, 6, 7, 10}) {
            if (!keyHeldTicks[key] || menu.active())
                continue;
            ++keyHeldTicks[key];
            if (keyHeldTicks[key] <= 10 || keyHeldTicks[key] % 3)
                continue;
            if (key == 10) {
                if (!shift)
                    trigger = true;
                continue;
            }
            if (shift)
                cyclePalette(key);
            else if (key == 4)
                loadMode(selected - 1);
            else if (key == 5)
                loadMode(selected + 1);
            else if (key == 6)
                recallScene(-1);
            else if (key == 7)
                recallScene(1);
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
                      ((settings.triggerSource == 0 || settings.triggerSource == 2) && a.triggerCount > triggerCount);
            triggerCount = a.triggerCount;
        }
        lastAnalysis = a;
        if (!options.probe) {
            knobs = knobSeq.run(knobs);
            syncLed();
            refreshHud();
            menu.observe(telemetry);
            runtime.snapshot(now, dt, knobs, a, midi, trigger, autoClear, midiEvents);
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
        if (osd || menu.active()) {
            ofPushStyle();
            if (menu.active())
                menu.draw(settings, telemetry, palettes);
            else {
                hud.draw(hudState);
                if (!message.empty()) {
                    ofSetColor(0, 0, 0, 190);
                    ofDrawRectangle(0, ofGetHeight() - 40, ofGetWidth(), 40);
                    ofSetColor(255);
                    ofDrawBitmapString(message, 16, ofGetHeight() - 16);
                }
            }
            ofPopStyle();
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
            menu.toggle();
            osd = true;
            message.clear();
            return;
        }
        if (menu.active()) {
            if (key == OF_KEY_UP)
                handleMenuKey(0, MenuSystem::Key::Up);
            if (key == OF_KEY_DOWN)
                handleMenuKey(0, MenuSystem::Key::Down);
            if (key == OF_KEY_LEFT)
                handleMenuKey(0, MenuSystem::Key::Decrease);
            if (key == OF_KEY_RIGHT)
                handleMenuKey(0, MenuSystem::Key::Increase);
            if (key == OF_KEY_RETURN)
                handleMenuKey(0, MenuSystem::Key::Confirm);
            if (key == OF_KEY_BACKSPACE || key == OF_KEY_ESC)
                handleMenuKey(0, MenuSystem::Key::Back);
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
        if (ledSock >= 0)
            close(ledSock);
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
            else if (arg == "--led-port")
                o.ledPort = std::stoi(next());
            else if (arg == "--video-mode")
                o.videoMode = next();
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
        if (o.frames < 0 || o.switchEvery < 0 || o.port < 0 || o.port > 65535 || o.device < -2 ||
            o.ledPort < 1 || o.ledPort > 65535)
            throw std::runtime_error(
                "invalid frame count, switch interval, audio device or OSC port");
        ofGLFWWindowSettings windowSettings;
#ifdef TARGET_OPENGLES
        windowSettings.setGLESVersion(2);
#else
        windowSettings.setGLVersion(3, 2);
#endif
        windowSettings.setSize(1280, 720);
        windowSettings.windowMode = o.fullscreen ? OF_FULLSCREEN : OF_WINDOW;
        auto window = o.kms ? createKmsWindow(o.videoMode)
                            : o.offscreen ? createOffscreenWindow(1280, 720)
                                          : ofCreateWindow(windowSettings);
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
