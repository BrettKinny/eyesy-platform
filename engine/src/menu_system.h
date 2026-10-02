// SPDX-License-Identifier: BSD-3-Clause
// Portions ported from Critter & Guitari EYESY_OS; see THIRD_PARTY_NOTICES.md.
#pragma once
#include "ofMain.h"
#include "palette_manager.h"
#include <array>
#include <cstdint>
#include <string>

// Operator settings owned by the engine and edited through the on-screen menu.
struct MenuSettings {
    double gain = 1;
    int midiChannel = 1;
    int triggerSource = 2;
    // Preferred KMS output mode ("WxH" or "WxH@R"); empty follows the EDID.
    std::string videoMode;
};

// Live values the menu reads. Nothing here is owned by the menu.
struct MenuTelemetry {
    std::array<double, 5> knobs{};
    float peakLeft = 0, peakRight = 0;
    std::array<int, 128> notes{};
    bool trigger = false;
    int width = 1280, height = 720;
    std::string mode, scene;
    int modeIndex = 0, modeCount = 0, sceneIndex = -1, sceneCount = 0;
    float fps = 0;
    // KMS mode note (empty unless the chooser fell back), shown on the video page.
    std::string videoNote;
    // Monotonic hardware button press counter, for the diagnostics page.
    uint64_t presses = 0;
};

// Fullscreen configuration menu, ported from the stock home screen plus the
// Video / Audio+MIDI / Palettes / Hardware test sub-screens.
class MenuSystem {
  public:
    enum class Key { Up, Down, Decrease, Increase, Confirm, Back, Other };

    bool active() const {
        return open;
    }
    void toggle();
    void close();
    int screen() const {
        return page;
    }
    int row() const {
        return cursor;
    }
    // Applies one navigation key. Palette rows move the shared palette manager.
    void key(Key pressed, MenuSettings &settings, eyesy::PaletteManager &palettes);
    void observe(const MenuTelemetry &telemetry);
    void resetDiagnostics();
    // Pass/fail for the hardware test rows: pots, buttons, MIDI notes, audio.
    std::array<bool, 4> diagnostics() const;
    void draw(const MenuSettings &settings, const MenuTelemetry &telemetry,
              const eyesy::PaletteManager &palettes);

  private:
    static constexpr int homeRows = 4;
    int rows() const;
    int page = 0, cursor = 0;
    bool open = false;
    // Hardware test state.
    std::array<bool, 5> potSeen{};
    std::array<bool, 3> noteSeen{};
    std::array<double, 5> potBaseline{};
    uint64_t pressBaseline = 0;
    uint64_t presses = 0;
    float peakSeen = 0;
    bool armed = false;
};
