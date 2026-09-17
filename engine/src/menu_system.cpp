#include "menu_system.h"
#include <algorithm>
#include <iomanip>
#include <sstream>

namespace {
// Stock reference frame: the overlay is authored against a 480-line surface.
constexpr float referenceHeight = 480.f;
const ofColor PANEL(6, 8, 14);
const ofColor LGRAY(200, 200, 200);
const ofColor GREEN(0, 255, 0);
const ofColor RED(255, 0, 0);
const ofColor YELLOW(255, 255, 0);
const char *const screenNames[] = {"Main Menu", "Video Settings", "Audio & MIDI",
                                   "Palettes", "Hardware Test"};
const char *const triggerSources[] = {"audio", "MIDI note", "audio + note", "MIDI quarter"};
const char *const homeEntries[] = {"Video Settings", "Audio & MIDI", "Palettes",
                                   "Hardware Test"};

const std::vector<std::string> &videoModes() {
    static const std::vector<std::string> modes{"", "1280x720@60", "1920x1080@60",
                                                "1360x768@60", "1280x1024@60"};
    return modes;
}

void bar(float fraction, int width, ofColor color) {
    fraction = float(std::clamp(double(fraction), 0.0, 1.0));
    ofSetColor(60, 60, 60);
    ofNoFill();
    ofDrawRectangle(0, 0, width, 8);
    ofSetColor(color);
    ofFill();
    ofDrawRectangle(0, 0, width * fraction, 8);
}
} // namespace

int MenuSystem::rows() const {
    switch (page) {
    case 0:
        return homeRows;
    case 1:
        return int(videoModes().size());
    case 2:
        return 3;
    case 3:
        return 2;
    default:
        return 4;
    }
}

void MenuSystem::toggle() {
    open = !open;
    if (open) {
        page = 0;
        cursor = 0;
        resetDiagnostics();
    }
}

void MenuSystem::close() {
    open = false;
    page = 0;
    cursor = 0;
}

void MenuSystem::resetDiagnostics() {
    // The next observe() arms the baselines from live hardware state.
    armed = false;
    potSeen.fill(false);
    noteSeen.fill(false);
    peakSeen = 0;
}

void MenuSystem::observe(const MenuTelemetry &telemetry) {
    presses = telemetry.presses;
    if (!armed) {
        // Arm against the hardware as it is now: the pot sweep test measures
        // movement made while the test screen is up, like the stock screen.
        potBaseline = telemetry.knobs;
        pressBaseline = presses;
        armed = true;
        return;
    }
    for (size_t i = 0; i < potSeen.size(); ++i)
        potSeen[i] = potSeen[i] || std::abs(telemetry.knobs[i] - potBaseline[i]) > .05;
    for (int note : {60, 62, 64})
        if (telemetry.notes[note] > 0)
            noteSeen[size_t((note - 60) / 2)] = true;
    peakSeen = std::max(peakSeen, std::max(telemetry.peakLeft, telemetry.peakRight));
}

std::array<bool, 4> MenuSystem::diagnostics() const {
    return {std::count(potSeen.begin(), potSeen.end(), true) >= 2,
            presses >= pressBaseline + 3,
            noteSeen[0] && noteSeen[1] && noteSeen[2], peakSeen > .5f};
}

void MenuSystem::key(Key pressed, MenuSettings &settings, eyesy::PaletteManager &palettes) {
    if (!open)
        return;
    const int count = rows();
    switch (pressed) {
    case Key::Up:
        cursor = (cursor + count - 1) % count;
        return;
    case Key::Down:
        cursor = (cursor + 1) % count;
        return;
    case Key::Confirm:
        if (page == 0) {
            page = cursor + 1;
            cursor = 0;
        } else if (page == 1) {
            settings.videoMode = videoModes()[size_t(cursor)];
        } else if (page == 4) {
            resetDiagnostics();
        }
        return;
    case Key::Back:
        if (page == 0)
            close();
        else {
            page = 0;
            cursor = 0;
        }
        return;
    default:
        break;
    }
    // Value rows: only the sub-screens with adjustable values move.
    const int step = pressed == Key::Increase ? 1 : -1;
    if (page == 1)
        cursor = (cursor + step + count) % count;
    else if (page == 2) {
        if (cursor == 0)
            settings.gain = std::clamp(settings.gain + step * .05, 0.0, 4.0);
        if (cursor == 1)
            settings.midiChannel = std::clamp(settings.midiChannel + step, 1, 16);
        if (cursor == 2)
            settings.triggerSource = std::clamp(settings.triggerSource + step, 0, 3);
    } else if (page == 3) {
        if (cursor == 0)
            step > 0 ? palettes.nextFg() : palettes.prevFg();
        if (cursor == 1)
            step > 0 ? palettes.nextBg() : palettes.prevBg();
    }
}

void MenuSystem::draw(const MenuSettings &settings, const MenuTelemetry &telemetry,
                      const eyesy::PaletteManager &palettes) {
    if (!open)
        return;
    const float scale = telemetry.height > 0 ? telemetry.height / referenceHeight : 1.f;
    ofPushMatrix();
    ofScale(scale, scale);
    ofFill();
    ofSetColor(PANEL.r, PANEL.g, PANEL.b);
    ofDrawRectangle(0, 0, 720, 480);
    ofSetColor(LGRAY);
    ofDrawBitmapString(std::string("EYESY  /  ") + screenNames[page], 20, 30);
    ofDrawBitmapString("Scene +/-: move   Mode +/-: change   Save: enter   OSD: back", 20, 470);
    for (int index = 0; index < rows(); ++index) {
        const float y = 90 + index * 34.f;
        ofSetColor(index == cursor ? YELLOW : LGRAY);
        ofDrawBitmapString(index == cursor ? ">" : " ", 20, y);
        std::ostringstream line;
        switch (page) {
        case 0:
            line << homeEntries[index];
            break;
        case 1:
            line << (videoModes()[size_t(index)].empty() ? "Auto (EDID mode)"
                                                         : videoModes()[size_t(index)]);
            if (videoModes()[size_t(index)] == settings.videoMode)
                line << "   *";
            break;
        case 2:
            if (index == 0)
                line << "Audio gain   " << std::fixed << std::setprecision(2) << settings.gain
                     << "x";
            if (index == 1)
                line << "MIDI channel " << settings.midiChannel;
            if (index == 2)
                line << "Trigger      " << triggerSources[settings.triggerSource];
            break;
        case 3:
            line << (index == 0 ? "FG palette   " : "BG palette   ")
                 << (index == 0 ? palettes.fg() : palettes.bg()) << " of " << palettes.size()
                 << "   " << palettes.entries()[index == 0 ? palettes.fg() : palettes.bg()].name;
            break;
        default: {
            const bool passed = diagnostics()[size_t(index)];
            const char *names[] = {"Pots (move two knobs)", "Buttons (press any three)",
                                   "MIDI notes 60/62/64", "Audio trigger level"};
            line << names[index] << "   " << (passed ? "PASS" : "FAIL");
            break;
        }
        }
        ofDrawBitmapString(line.str(), 40, y);
    }
    if (page == 1) {
        ofSetColor(LGRAY);
        ofDrawBitmapString("Output: " + ofToString(telemetry.width) + " x " +
                               ofToString(telemetry.height) + "   (restart to apply)",
                           40, 300);
        if (!telemetry.videoNote.empty())
            ofDrawBitmapString("KMS: " + telemetry.videoNote, 40, 324);
    }
    if (page == 2) {
        ofSetColor(LGRAY);
        ofPushMatrix();
        ofTranslate(300, 90);
        bar(settings.gain / 4, 260, GREEN);
        ofPopMatrix();
        ofPushMatrix();
        ofTranslate(300, 124);
        bar((settings.midiChannel - 1) / 15.f, 260, GREEN);
        ofPopMatrix();
        ofPushMatrix();
        ofTranslate(300, 158);
        bar(0, 260, GREEN);
        ofPopMatrix();
    }
    if (page == 3) {
        for (int row = 0; row < 2; ++row) {
            const bool foreground = row == 0;
            for (int pixel = 0; pixel < 120; ++pixel) {
                auto color = foreground ? palettes.sampleFg(pixel / 120.0)
                                        : palettes.sampleBg(pixel / 120.0);
                ofSetColor(color[0] * 255, color[1] * 255, color[2] * 255);
                ofDrawRectangle(300, 90 + row * 140 + pixel, 300, 1);
            }
        }
    }
    if (page == 4) {
        ofSetColor(LGRAY);
        std::ostringstream live;
        live << "knobs  ";
        for (double knob : telemetry.knobs)
            live << std::fixed << std::setprecision(2) << knob << "  ";
        live << "  peak " << std::setprecision(2) << peakSeen
             << "  presses " << (presses - pressBaseline);
        ofDrawBitmapString(live.str(), 40, 330);
        ofDrawBitmapString("notes 60/62/64: " +
                               std::string(noteSeen[0] ? "60 " : "-- ") +
                               (noteSeen[1] ? "62 " : "-- ") + (noteSeen[2] ? "64" : "--"),
                           40, 360);
        ofSetColor(telemetry.trigger ? YELLOW : LGRAY);
        ofDrawBitmapString("trigger " + std::string(telemetry.trigger ? "high" : "low"), 40, 390);
    }
    ofPopMatrix();
}
