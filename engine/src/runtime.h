// SPDX-License-Identifier: BSD-3-Clause
#pragma once
#include "core.h"
#include "ofMain.h"
#include "palette_manager.h"
#include <filesystem>
#include <lua.hpp>
#include <map>
#include <vector>

class ModeRuntime {
  public:
    std::string error;
    std::filesystem::path directory;
    std::map<std::string, eyesy::Parameter> parameters;
    // Global FG/BG palettes exposed to modes as ctx.palette_fg / ctx.palette_bg.
    void setPalettes(const eyesy::PaletteManager *value) {
        palettes_global = value;
    }
    bool load(const std::filesystem::path &folder, int width, int height);
    bool call(const char *method, double dt = 0);
    void snapshot(double time, double dt, const std::array<double, 5> &knobs,
                  const eyesy::Analysis &audio, const eyesy::MidiState &midi, bool trigger,
                  bool autoClear, const std::vector<eyesy::MidiEvent> &events = {});
    ofJson save();
    bool restore(const ofJson &state);
    bool reloadShaders();
    std::string shaderWarning;
    void close();
    ~ModeRuntime() {
        close();
    }
    size_t resourceCount() const {
        return fbos.size() + shaders.size() + images.size() + meshes.size();
    }

  private:
    lua_State *lua = nullptr;
    int modeRef = LUA_NOREF, contextRef = LUA_NOREF;
    int width = 1280, height = 720, nextHandle = 1;
    uint32_t randomState = 1;
    int matrixDepth = 0;
    bool cameraActive = false;
    ofCamera camera;
    ofTexture audioTexture;
    ofPixels audioPixels;
    std::map<int, std::shared_ptr<ofFbo>> fbos;
    std::map<int, std::shared_ptr<ofShader>> shaders;
    std::map<int, std::shared_ptr<ofImage>> images;
    std::map<int, std::filesystem::path> shaderFiles;
    std::map<int, std::shared_ptr<ofVboMesh>> meshes;
    std::map<std::string, std::vector<std::array<float, 3>>> palettes;
    const eyesy::PaletteManager *palettes_global = nullptr;
    std::vector<int> targetStack;
    static int dispatch(lua_State *L);
    int invoke(lua_State *L, int operation);
    std::filesystem::path asset(const std::string &relative) const;
    void resetGraphics();
    std::shared_ptr<ofShader> compileShader(const std::filesystem::path &file);
};
