// SPDX-License-Identifier: BSD-3-Clause
#pragma once
#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace eyesy {
// Stock EYESY OS v3 "abcd" cosine palette: color = a + b*cos(2*pi*(c*t + d)),
// clamped to [0,1], evaluated per channel (eyesy.py::get_color_from_phase).
struct CosinePalette {
    std::string name;
    std::array<float, 3> a{}, b{}, c{}, d{};
};

// Global FG/BG palette selection. Modes sample it through ctx.palette_fg /
// ctx.palette_bg; the HUD samples it for the preview swatches. Free of
// openFrameworks so the cosine math and cycling are unit-testable natively.
class PaletteManager {
  public:
    static constexpr size_t previewStops = 16;

    PaletteManager();
    const std::vector<CosinePalette> &entries() const {
        return list;
    }
    size_t size() const {
        return list.size();
    }
    size_t fg() const {
        return fgIndex;
    }
    size_t bg() const {
        return bgIndex;
    }
    void setFg(size_t index);
    void setBg(size_t index);
    void nextFg() {
        setFg(fgIndex + 1);
    }
    void prevFg() {
        setFg(fgIndex + list.size() - 1);
    }
    void nextBg() {
        setBg(bgIndex + 1);
    }
    void prevBg() {
        setBg(bgIndex + list.size() - 1);
    }
    std::array<float, 3> sampleFg(double phase) const;
    std::array<float, 3> sampleBg(double phase) const;
    std::array<std::array<float, 3>, previewStops> preview(bool foreground) const;
    // Replaces the table (System/palettes.json); rejects empty data.
    bool replace(std::vector<CosinePalette> palettes);

  private:
    std::vector<CosinePalette> list;
    size_t fgIndex = 0, bgIndex = 0;
};
} // namespace eyesy
