// SPDX-License-Identifier: BSD-3-Clause
// Portions ported from Critter & Guitari EYESY_OS; see THIRD_PARTY_NOTICES.md.
#include "osd_hud.h"
#include "ofMain.h"
#include <algorithm>
#include <sstream>

namespace {
// Stock palette constants (eyesy.py).
const ofFloatColor LGRAY(200 / 255.f, 200 / 255.f, 200 / 255.f);
const ofFloatColor GREEN(0, 1, 0);
const ofFloatColor RED(1, 0, 0);
const ofFloatColor YELLOW(1, 1, 0);
const ofFloatColor BLACK(0, 0, 0);
// The overlay is authored against the stock 480-line framebuffer.
constexpr float referenceHeight = 480.f;

void addQuad(ofMesh &mesh, float x, float y, float w, float h, const ofFloatColor &color) {
    glm::vec3 topLeft(x, y, 0), topRight(x + w, y, 0);
    glm::vec3 bottomRight(x + w, y + h, 0), bottomLeft(x, y + h, 0);
    mesh.addVertex(topLeft);
    mesh.addColor(color);
    mesh.addVertex(topRight);
    mesh.addColor(color);
    mesh.addVertex(bottomRight);
    mesh.addColor(color);
    mesh.addVertex(topLeft);
    mesh.addColor(color);
    mesh.addVertex(bottomRight);
    mesh.addColor(color);
    mesh.addVertex(bottomLeft);
    mesh.addColor(color);
}

void addLine(ofMesh &mesh, float x1, float y1, float x2, float y2, const ofFloatColor &color) {
    mesh.addVertex(glm::vec3(x1, y1, 0));
    mesh.addColor(color);
    mesh.addVertex(glm::vec3(x2, y2, 0));
    mesh.addColor(color);
}

void addBox(ofMesh &mesh, float x, float y, float w, float h, const ofFloatColor &color) {
    addLine(mesh, x, y, x + w, y, color);
    addLine(mesh, x, y, x, y + h, color);
    addLine(mesh, x + w, y, x + w, y + h, color);
    addLine(mesh, x, y + h, x + w, y + h, color);
}

ofFloatColor stopColor(const std::array<std::array<float, 3>, 16> &stops, float phase) {
    phase = std::clamp(phase, 0.f, 1.f) * (stops.size() - 1);
    size_t index = std::min<size_t>(size_t(phase), stops.size() - 2);
    float blend = phase - index;
    return ofFloatColor(stops[index][0] * (1 - blend) + stops[index + 1][0] * blend,
                        stops[index][1] * (1 - blend) + stops[index + 1][1] * blend,
                        stops[index][2] * (1 - blend) + stops[index + 1][2] * blend);
}

void drawText(const std::string &text, int line, float x) {
    ofDrawBitmapString(text, x, line + 4);
}
} // namespace

void OsdHud::draw(const HudState &state) {
    const float scale = state.height > 0 ? state.height / referenceHeight : 1.f;
    ofMesh outlines, fills;
    outlines.setMode(OF_PRIMITIVE_LINES);
    fills.setMode(OF_PRIMITIVE_TRIANGLES);

    // Panel backing.
    addQuad(fills, 10, 10, 598, 130, BLACK);

    // BG then FG palette preview swatches (draw_color_palette).
    for (int row = 0; row < 130; ++row)
        addQuad(fills, 450, 10 + row, 170, 1,
                stopColor(state.bgPreview, float(row) / 130.f));
    for (int row = 0; row < 85; ++row)
        addQuad(fills, 475, 35 + row, 125, 1, stopColor(state.fgPreview, float(row) / 85.f));

    // Knob sliders, coloured by sequencer state.
    const ofFloatColor knobColor = state.sequencer == 2   ? GREEN
                                   : state.sequencer == 1 ? RED
                                                          : LGRAY;
    for (int channel = 0; channel < 5; ++channel) {
        float x = 20 + 13.25f * channel;
        addBox(outlines, x, 105, 10, 24, knobColor);
        float knob = float(std::clamp(state.knobs[channel], 0.0, 1.0));
        addQuad(fills, x, 105 + 24 - 24 * knob, 10, 24 * knob, knobColor);
    }

    // 128-note MIDI grid (32 x 4).
    for (int column = 0; column <= 32; ++column)
        addLine(outlines, 89 + column * 6.f, 105, 89 + column * 6.f, 129, LGRAY);
    for (int row = 0; row <= 4; ++row)
        addLine(outlines, 89, 105 + row * 6.f, 281, 105 + row * 6.f, LGRAY);
    if (state.notes)
        for (int note = 0; note < 128; ++note)
            if ((*state.notes)[note] > 0)
                addQuad(fills, 89 + 6.f * (note % 32), 105 + 6.f * (note / 32), 6, 6, LGRAY);

    // Audio gain bar and stereo VU meters.
    const float gainRatio = float(std::clamp(state.gain / 4.0, 0.0, 1.0));
    addBox(outlines, 286, 105, 118, 5, LGRAY);
    addQuad(fills, 286, 105, 118 * gainRatio, 5, LGRAY);
    const float peaks[2] = {state.peakLeft, state.peakRight};
    for (int channel = 0; channel < 2; ++channel) {
        float y = 113 + 9.f * channel;
        for (int segment = 0; segment < 15; ++segment)
            addBox(outlines, 286 + 8.f * segment, y, 6, 7, LGRAY);
        // Stock counts raw 16-bit segments of 2048; ctx peaks are normalised.
        int lit = std::clamp(int(std::clamp(peaks[channel], 0.f, 1.f) * 32768.f / 2048.f), 0, 15);
        for (int segment = 0; segment < lit; ++segment) {
            ofFloatColor color = GREEN;
            if (segment > 8)
                color = YELLOW;
            if (segment == 14)
                color = RED;
            addQuad(fills, 286 + 8.f * segment + 1, y + 1, 5, 6, color);
        }
    }

    // Trigger indicator.
    addBox(outlines, 410, 105, 25, 25, LGRAY);
    if (state.trigger)
        addQuad(fills, 410, 105, 25, 25, YELLOW);

    ofPushMatrix();
    ofTranslate(0, 0);
    ofScale(scale, scale);
    ofSetColor(255);
    fills.draw();
    outlines.draw();
    const ofFloatColor textColor = LGRAY;
    ofSetColor(textColor);
    std::ostringstream mode;
    mode << "Mode: (" << state.modeIndex + 1 << " of " << state.modeCount << ") " << state.mode;
    drawText(mode.str(), 30, 20);
    drawText("FPS: " + ofToString(int(state.fps)), 30, 300);
    drawText(state.usb ? "USB" : "SD", 30, 404);
    std::ostringstream scene;
    if (state.sceneLoaded)
        scene << "Scene: (" << state.sceneIndex + 1 << " of " << state.sceneCount << ") "
              << state.scene;
    else
        scene << "Scene: None";
    drawText(scene.str(), 55, 20);
    drawText(std::string("Persist: ") + (state.persist ? "Yes" : "No"), 55, 300);
    drawText("Screen Size: " + ofToString(state.width) + " x " + ofToString(state.height), 80, 20);
    drawText("v" + state.version, 80, 380);
    ofPopMatrix();
    // Two batched meshes plus one drawBitmapString call per text line.
    calls = 2 + 7;
}
