// SPDX-License-Identifier: BSD-3-Clause
// Portions ported from Critter & Guitari EYESY_OS; see THIRD_PARTY_NOTICES.md.
#include "palette_manager.h"
#include <algorithm>
#include <cmath>

namespace eyesy {
namespace {
constexpr double twoPi = 6.283185307179586;

// Stock EYESY OS v3 defaults, copied verbatim from
// engines/python/stuff/color_palettes.py::abcd_palettes. System/palettes.json
// replaces this table when present. One palette per line: name, then the a, b, c, d
// cosine coefficients (r, g, b), kept as written so rows diff against the source.
// clang-format off
const CosinePalette stockPalettes[] = {
    {"Original", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}},
    {"Greyscale", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}},
    {"Red : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.000000f, 0.450000f, 0.450000f}, {0.000000f, 0.530000f, 0.530000f}},
    {"Black : Red", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, -0.500000f}, {0.500000f, 0.000000f, 0.000000f}, {0.500000f, 0.500000f, 0.000000f}},
    {"Orange : White", {1.000000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.000000f, 0.250000f, 0.490000f}, {0.000000f, -1.267000f, -0.503000f}},
    {"Black : Orange", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.450000f, 0.250000f, 0.000000f}, {-0.490000f, 0.503000f, 0.500000f}},
    {"Yellow : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.000000f, 0.000000f, 0.500000f}, {0.000000f, 0.000000f, 0.500000f}},
    {"Black : Yellow", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, -0.500000f}, {0.500000f, 0.500000f, 0.000000f}, {0.500000f, 0.500000f, 0.000000f}},
    {"Green : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.000000f, 0.500000f}, {0.500000f, 0.000000f, 0.500000f}},
    {"Black : Green", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, -0.500000f}, {0.000000f, 0.500000f, 0.000000f}, {0.500000f, 0.500000f, 0.000000f}},
    {"Light Blue : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.000000f, 0.000000f}, {-0.500000f, 0.000000f, 0.000000f}},
    {"Black : Light Blue", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.000000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}},
    {"Blue : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.450000f, 0.450000f, 0.000000f}, {0.530000f, 0.533000f, 0.000000f}},
    {"Black : Blue", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, -0.500000f}, {0.000000f, 0.000000f, 0.500000f}, {0.500000f, 0.500000f, 0.000000f}},
    {"Purple : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.300000f, 0.460000f, 0.000000f}, {0.700000f, 0.523000f, 0.000000f}},
    {"Black : Purple", {0.500000f, -0.620000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {0.200000f, 0.000000f, 0.500000f}, {-0.500000f, 0.000000f, -0.493000f}},
    {"Pink : White", {0.498000f, 0.490000f, 0.498000f}, {0.498000f, 0.498000f, 0.498000f}, {0.000000f, -0.500000f, 0.000000f}, {-0.003000f, 0.503000f, -0.002000f}},
    {"Black : Pink", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, -0.500000f}, {0.500000f, 0.000000f, 0.500000f}, {0.500000f, 0.500000f, 0.000000f}},
    {"Dark Blue : Light Blue", {0.500000f, 0.500000f, 0.500000f}, {0.498000f, 0.498000f, -0.500000f}, {0.000000f, 0.500000f, 0.000000f}, {0.500000f, 0.500000f, 0.500000f}},
    {"Classic Anaglyph", {0.000000f, 0.000000f, 0.000000f}, {1.000000f, 1.000000f, 1.000000f}, {0.300000f, 0.250000f, 0.250000f}, {0.870000f, 0.755000f, 0.755000f}},
    {"Red : Teal : White", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {1.000000f, 0.500000f, 0.500000f}, {0.000000f, -0.517000f, -0.517000f}},
    {"Purple : Teal : Ivory", {1.710000f, 0.500000f, 0.918000f}, {-1.392000f, 0.510000f, 0.720000f}, {-0.249000f, 0.359000f, 0.127000f}, {0.088000f, -0.403000f, 2.617000f}},
    {"Deep Myrtle : Electric Purple", {0.000000f, -0.050000f, 0.000000f}, {0.780000f, 0.630000f, 1.000000f}, {0.300000f, 0.588000f, 0.250000f}, {0.730000f, -0.247000f, 0.755000f}},
    {"Pansy", {0.000000f, 0.000000f, 0.000000f}, {1.000000f, 1.000000f, 1.000000f}, {0.250000f, 0.250000f, 0.500000f}, {0.737000f, 0.737000f, 0.737000f}},
    {"Raw Sienna : Cyan", {0.000000f, 0.288000f, 0.000000f}, {1.000000f, 1.000000f, 1.000000f}, {0.300000f, 0.250000f, 0.250000f}, {0.870000f, 0.755000f, 0.755000f}},
    {"Watermelon", {2.158000f, 0.590000f, 0.918000f}, {-1.392000f, 0.510000f, 0.720000f}, {-0.240000f, 0.800000f, 0.127000f}, {0.088000f, -0.362000f, 2.617000f}},
    {"Amaranth Purple : Ivory", {1.710000f, 0.500000f, 0.918000f}, {-1.080000f, 0.510000f, 0.720000f}, {-0.249000f, 0.359000f, 0.127000f}, {0.088000f, -0.403000f, 2.617000f}},
    {"Amethyst : Malachite", {0.510000f, 0.510000f, 0.510000f}, {0.291000f, 0.291000f, 0.291000f}, {1.000000f, -0.770000f, 0.230000f}, {-0.190000f, -0.247000f, -0.153000f}},
    {"Neon Green : Citrine", {0.500000f, 0.740000f, -1.810000f}, {0.450000f, 0.190000f, 2.210000f}, {-0.310000f, 0.898000f, 0.210000f}, {-0.632000f, -0.957000f, 1.998000f}},
    {"Apricot : Electric Purple", {0.500000f, 0.280000f, 0.608000f}, {0.500000f, 0.500000f, 0.500000f}, {0.250000f, 1.520000f, 0.250000f}, {0.000000f, 0.000000f, -0.312000f}},
    {"Baja", {0.498000f, -0.470000f, -0.680000f}, {0.468000f, 1.028000f, 1.620000f}, {-1.150000f, 0.718000f, 0.450000f}, {-0.252000f, -0.487000f, 1.817000f}},
    {"Abajo", {0.498000f, -0.390000f, -0.680000f}, {0.468000f, 1.028000f, 1.620000f}, {-1.150000f, 0.558000f, 0.450000f}, {-0.252000f, -0.487000f, 1.817000f}},
    {"Aquamarine : Light Purple", {0.340000f, 0.530000f, 0.518000f}, {-0.240000f, -0.450000f, -0.150000f}, {-1.552000f, 0.718000f, 0.850000f}, {0.088000f, -0.507000f, 4.557000f}},
    {"Looking West", {0.530000f, 0.698000f, -0.640000f}, {0.450000f, 0.210000f, 1.620000f}, {-0.310000f, 1.840000f, 0.210000f}, {-0.670000f, -0.742000f, 1.998000f}},
    {"Looking West Evening", {0.490000f, 0.358000f, -1.642000f}, {0.450000f, 0.190000f, 2.210000f}, {-0.310000f, 1.840000f, 0.210000f}, {-0.632000f, -0.957000f, 1.998000f}},
    {"2090s", {1.068000f, 0.648000f, 0.718000f}, {-1.212000f, -0.362000f, 0.068000f}, {-0.562000f, 0.878000f, 0.280000f}, {0.538000f, -0.527000f, -0.382000f}},
    {"Highlights", {0.500000f, 0.500000f, 0.500000f}, {0.500000f, 0.500000f, 0.500000f}, {1.000000f, 0.500000f, 0.500000f}, {0.000000f, 0.000000f, -0.523000f}},
    {"Perfume", {1.098000f, 1.170000f, 0.648000f}, {0.500000f, -0.272000f, 1.568000f}, {-0.492000f, 0.900000f, 0.280000f}, {-1.250000f, 0.193000f, 0.628000f}},
    {"Gymnopedie No. 3", {0.500000f, 0.530000f, 0.680000f}, {0.498000f, 0.498000f, 0.250000f}, {0.840000f, 1.700000f, 3.440000f}, {0.120000f, 0.583000f, 0.498000f}},
    {"Almost Rainbow", {1.400000f, 0.590000f, 0.770000f}, {-1.392000f, 0.640000f, 0.720000f}, {-1.220000f, 1.070000f, 0.127000f}, {0.088000f, -0.362000f, 2.617000f}},
    {"KRYCB", {-0.212000f, -0.470000f, -0.682000f}, {3.138000f, 3.138000f, 3.138000f}, {-0.790000f, 0.718000f, 0.428000f}, {-0.672000f, -0.422000f, 4.557000f}},
    {"Discrete Variety!", {0.000000f, 0.000000f, 0.000000f}, {1.000000f, 1.000000f, 1.000000f}, {250.000000f, 251.000000f, 252.000000f}, {0.000000f, 0.683000f, 0.000000f}},
    {"Palette 1", {0.332000f, 0.347000f, 0.404000f}, {0.944000f, 0.346000f, 0.315000f}, {0.368000f, 0.980000f, 1.422000f}, {4.571000f, 2.412000f, 4.308000f}},
};
// clang-format on

std::array<float, 3> evaluate(const CosinePalette &palette, double phase) {
    std::array<float, 3> color{};
    for (size_t channel = 0; channel < color.size(); ++channel) {
        double value =
            double(palette.a[channel]) +
            double(palette.b[channel]) *
                std::cos(twoPi * (double(palette.c[channel]) * phase + double(palette.d[channel])));
        color[channel] = float(std::clamp(value, 0.0, 1.0));
    }
    return color;
}
} // namespace

PaletteManager::PaletteManager() {
    replace({std::begin(stockPalettes), std::end(stockPalettes)});
}

void PaletteManager::setFg(size_t index) {
    fgIndex = list.empty() ? 0 : index % list.size();
}
void PaletteManager::setBg(size_t index) {
    bgIndex = list.empty() ? 0 : index % list.size();
}
std::array<float, 3> PaletteManager::sampleFg(double phase) const {
    if (list.empty())
        return {1, 1, 1};
    // Stock evaluates an unwrapped phase so non-integer cosine periods behave
    // exactly as they do on the instrument.
    return evaluate(list[fgIndex % list.size()], std::isfinite(phase) ? phase : 0.0);
}
std::array<float, 3> PaletteManager::sampleBg(double phase) const {
    if (list.empty())
        return {1, 1, 1};
    return evaluate(list[bgIndex % list.size()], std::isfinite(phase) ? phase : 0.0);
}
std::array<std::array<float, 3>, PaletteManager::previewStops>
PaletteManager::preview(bool foreground) const {
    std::array<std::array<float, 3>, previewStops> stops{};
    for (size_t i = 0; i < stops.size(); ++i)
        stops[i] =
            foreground ? sampleFg(double(i) / stops.size()) : sampleBg(double(i) / stops.size());
    return stops;
}
bool PaletteManager::replace(std::vector<CosinePalette> palettes) {
    if (palettes.empty())
        return false;
    list = std::move(palettes);
    fgIndex %= list.size();
    bgIndex %= list.size();
    return true;
}
} // namespace eyesy
