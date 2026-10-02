// SPDX-License-Identifier: BSD-3-Clause
// Portions ported from Critter & Guitari EYESY_OS; see THIRD_PARTY_NOTICES.md.
#pragma once
#include <array>
#include <cstdint>
#include <string>

// Stock EYESY OS v3 instrument HUD, ported from `osd.py::render_overlay_480`.
// The panel is laid out in the stock 480-line coordinate space and scaled to the
// render surface, so the element geometry stays comparable with stock.
struct HudState {
    std::string mode;
    int modeIndex = 0, modeCount = 0;
    bool sceneLoaded = false;
    std::string scene;
    int sceneIndex = 0, sceneCount = 0;
    int width = 1280, height = 720;
    std::string version = "3.0";
    bool usb = false;
    std::array<double, 5> knobs{};
    // Sequencer colour coding: 0 = idle (light gray), 1 = recording (red),
    // 2 = playing (green).
    int sequencer = 0;
    const std::array<int, 128> *notes = nullptr;
    float peakLeft = 0, peakRight = 0;
    double gain = 1;
    bool trigger = false;
    bool persist = false;
    float fps = 0;
    // 16 pre-sampled colour stops for the FG and BG palette preview swatches.
    std::array<std::array<float, 3>, 16> fgPreview{};
    std::array<std::array<float, 3>, 16> bgPreview{};
};

class OsdHud {
  public:
    // Draws the stock overlay; all geometry is authored in the stock 480-line
    // space and scaled to the render surface.
    void draw(const HudState &state);
    // Batched GL draw calls issued by the last frame: outlines, fills, text.
    size_t drawCalls() const {
        return calls;
    }

  private:
    size_t calls = 0;
};
