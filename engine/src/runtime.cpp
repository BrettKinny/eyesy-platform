#include "runtime.h"
#include "ofGLProgrammableRenderer.h"
#include <climits>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>

namespace {
enum Operation {
    CLEAR,
    COLOR,
    RECT,
    CIRCLE,
    LINE,
    TEXT,
    PUSH,
    POP,
    TRANSLATE,
    ROTATE,
    SCALE,
    PARAM,
    RANDOM,
    PALETTE,
    PALETTE_DEFINE,
    PALETTE_FG,
    PALETTE_BG,
    LFO,
    FBO_NEW,
    FBO_BEGIN,
    FBO_END,
    FBO_DRAW,
    SHADER_NEW,
    SHADER_DRAW,
    IMAGE_NEW,
    IMAGE_DRAW,
    MESH,
    DEPTH,
    MESH_NEW,
    MESH_UPDATE,
    MESH_DRAW,
    CAMERA_BEGIN,
    CAMERA_END
};
void number(lua_State *l, const char *key, double value) {
    lua_pushnumber(l, value);
    lua_setfield(l, -2, key);
}
template <class T> void array(lua_State *l, const T &values) {
    lua_createtable(l, values.size(), 0);
    int i = 1;
    for (auto v : values) {
        lua_pushnumber(l, v);
        lua_rawseti(l, -2, i++);
    }
}
void pushJson(lua_State *l, const ofJson &j, int depth = 0) {
    if (depth > 16)
        throw std::runtime_error("scene state nesting exceeds 16");
    if (j.is_null())
        lua_pushnil(l);
    else if (j.is_boolean())
        lua_pushboolean(l, j.get<bool>());
    else if (j.is_number())
        lua_pushnumber(l, j.get<double>());
    else if (j.is_string())
        lua_pushstring(l, j.get<std::string>().c_str());
    else {
        lua_newtable(l);
        if (j.is_array()) {
            int i = 1;
            for (auto &v : j) {
                pushJson(l, v, depth + 1);
                lua_rawseti(l, -2, i++);
            }
        } else
            for (auto it = j.begin(); it != j.end(); ++it) {
                pushJson(l, it.value(), depth + 1);
                lua_setfield(l, -2, it.key().c_str());
            }
    }
}
// error({}) and friends raise non-string values; lua_tostring returns NULL
// for those, which must never reach a std::string.
std::string luaError(lua_State *l) {
    const char *message = lua_tostring(l, -1);
    return message ? message : std::string("Lua error (") + luaL_typename(l, -1) + " value)";
}
ofJson readJson(lua_State *l, int index, int depth = 0) {
    if (depth > 16)
        throw std::runtime_error("scene state cyclic or deeper than 16");
    if (index < 0)
        index = lua_gettop(l) + index + 1;
    switch (lua_type(l, index)) {
    case LUA_TNIL:
        return nullptr;
    case LUA_TBOOLEAN:
        return bool(lua_toboolean(l, index));
    case LUA_TNUMBER: {
        double n = lua_tonumber(l, index);
        if (!std::isfinite(n))
            throw std::runtime_error("nonfinite scene value");
        return n;
    }
    case LUA_TSTRING:
        return std::string(lua_tostring(l, index));
    case LUA_TTABLE: {
        ofJson result = ofJson::object();
        lua_pushnil(l);
        int count = 0;
        while (lua_next(l, index)) {
            if (++count > 4096 || lua_type(l, -2) != LUA_TSTRING) {
                lua_pop(l, 2);
                throw std::runtime_error("scene state requires string keys, at most 4096 fields");
            }
            auto key = std::string(lua_tostring(l, -2));
            result[key] = readJson(l, -1, depth + 1);
            lua_pop(l, 1);
        }
        return result;
    }
    default:
        throw std::runtime_error("scene state must contain JSON-compatible values");
    }
}
} // namespace
std::filesystem::path ModeRuntime::asset(const std::string &relative) const {
    auto path = std::filesystem::weakly_canonical(directory / relative);
    auto rel = path.lexically_relative(directory);
    if (rel.empty() || rel.is_absolute() || *rel.begin() == "..")
        throw std::runtime_error("asset must be inside mode folder");
    return path;
}
static std::vector<std::array<float, 3>> builtinPalette(const std::string &name) {
    if (name == "sunset")
        return {{{0.08f, 0.02f, 0.18f}, {0.9f, 0.12f, 0.22f}, {1.0f, 0.72f, 0.2f}}};
    if (name == "ocean")
        return {{{0.01f, 0.03f, 0.14f}, {0.0f, 0.45f, 0.7f}, {0.35f, 0.95f, 0.85f}}};
    if (name == "ember")
        return {{{0.03f, 0.005f, 0.0f}, {0.65f, 0.04f, 0.005f}, {1.0f, 0.75f, 0.12f}}};
    if (name == "mint")
        return {{{0.02f, 0.08f, 0.1f}, {0.1f, 0.65f, 0.48f}, {0.85f, 1.0f, 0.72f}}};
    return {};
}
void ModeRuntime::resetGraphics() {
    while (matrixDepth > 0) {
        ofPopMatrix();
        --matrixDepth;
    }
    if (cameraActive) {
        camera.end();
        cameraActive = false;
    }
    while (!targetStack.empty()) {
        fbos.at(targetStack.back())->end();
        targetStack.pop_back();
    }
    ofDisableDepthTest();
    ofSetColor(255);
    ofFill();
    ofEnableAlphaBlending();
}
void ModeRuntime::close() {
    if (lua) {
        if (error.empty())
            call("teardown");
        resetGraphics();
        lua_close(lua);
        lua = nullptr;
    }
    parameters.clear();
    fbos.clear();
    shaders.clear();
    shaderFiles.clear();
    audioTexture.clear();
    audioPixels.clear();
    meshes.clear();
    images.clear();
    palettes.clear();
    nextHandle = 1;
    modeRef = contextRef = LUA_NOREF;
}
bool ModeRuntime::load(const std::filesystem::path &folder, int w, int h) {
    close();
    error.clear();
    width = w;
    height = h;
    directory = std::filesystem::weakly_canonical(folder);
    randomState = 1;
    for (const char *name : {"sunset", "ocean", "ember", "mint"})
        palettes[name] = builtinPalette(name);
    lua = luaL_newstate();
    if (!lua) {
        error = "cannot allocate Lua state";
        return false;
    }
    luaL_openlibs(lua);
    lua_newtable(lua);
    const std::pair<const char *, int> methods[] = {{"clear", CLEAR},
                                                    {"color", COLOR},
                                                    {"rect", RECT},
                                                    {"circle", CIRCLE},
                                                    {"line", LINE},
                                                    {"text", TEXT},
                                                    {"push", PUSH},
                                                    {"pop", POP},
                                                    {"translate", TRANSLATE},
                                                    {"rotate", ROTATE},
                                                    {"scale", SCALE},
                                                    {"param", PARAM},
                                                    {"random", RANDOM},
                                                    {"palette", PALETTE},
                                                    {"define_palette", PALETTE_DEFINE},
                                                    {"lfo", LFO},
                                                    {"target", FBO_NEW},
                                                    {"begin_target", FBO_BEGIN},
                                                    {"end_target", FBO_END},
                                                    {"draw_target", FBO_DRAW},
                                                    {"shader", SHADER_NEW},
                                                    {"draw_shader", SHADER_DRAW},
                                                    {"image", IMAGE_NEW},
                                                    {"draw_image", IMAGE_DRAW},
                                                    {"mesh", MESH},
                                                    {"depth", DEPTH},
                                                    {"new_mesh", MESH_NEW},
                                                    {"update_mesh", MESH_UPDATE},
                                                    {"draw_mesh", MESH_DRAW},
                                                    {"begin_camera", CAMERA_BEGIN},
                                                    {"end_camera", CAMERA_END}};
    for (auto entry : methods) {
        lua_pushlightuserdata(lua, this);
        lua_pushinteger(lua, entry.second);
        lua_pushcclosure(lua, dispatch, 2);
        lua_setfield(lua, -2, entry.first);
    }
    number(lua, "api_version", 1);
    lua_newtable(lua);
    GLint maxTexture = 0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTexture);
    number(lua, "max_texture_size", maxTexture);
    number(lua, "max_targets", 8);
    number(lua, "max_mesh_vertices", 8192);
    lua_setfield(lua, -2, "capabilities");
    lua_setglobal(lua, "eyesy");
    lua_getglobal(lua, "package");
    lua_getfield(lua, -1, "path");
    std::string path = (directory / "?.lua").string() + ";" + lua_tostring(lua, -1);
    lua_pop(lua, 1);
    lua_pushstring(lua, path.c_str());
    lua_setfield(lua, -2, "path");
    lua_pop(lua, 1);
    lua_newtable(lua);
    number(lua, "width", w);
    number(lua, "height", h);
    for (auto entry : {std::make_pair("palette_fg", PALETTE_FG),
                       std::make_pair("palette_bg", PALETTE_BG)}) {
        lua_pushlightuserdata(lua, this);
        lua_pushinteger(lua, entry.second);
        lua_pushcclosure(lua, dispatch, 2);
        lua_setfield(lua, -2, entry.first);
    }
    contextRef = luaL_ref(lua, LUA_REGISTRYINDEX);
    if (luaL_loadfile(lua, (directory / "main.lua").c_str()) || lua_pcall(lua, 0, 1, 0)) {
        error = luaError(lua);
        lua_pop(lua, 1);
        return false;
    }
    if (!lua_istable(lua, -1)) {
        error = "main.lua must return a mode table";
        lua_pop(lua, 1);
        return false;
    }
    lua_getfield(lua, -1, "api_version");
    bool compatible = lua_isnumber(lua, -1) && lua_tonumber(lua, -1) == 1;
    lua_pop(lua, 1);
    lua_getfield(lua, -1, "draw");
    bool drawable = lua_isfunction(lua, -1);
    lua_pop(lua, 1);
    if (!compatible || !drawable) {
        error = "mode requires api_version = 1 and draw function";
        lua_pop(lua, 1);
        return false;
    }
    modeRef = luaL_ref(lua, LUA_REGISTRYINDEX);
    return call("setup");
}
bool ModeRuntime::call(const char *method, double dt) {
    if (!lua || modeRef == LUA_NOREF || !error.empty())
        return false;
    int top = lua_gettop(lua);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, modeRef);
    lua_getfield(lua, -1, method);
    if (lua_isnil(lua, -1)) {
        lua_settop(lua, top);
        return true;
    }
    lua_rawgeti(lua, LUA_REGISTRYINDEX, contextRef);
    lua_pushnumber(lua, dt);
    ofPushStyle();
    ofPushMatrix();
    int status = lua_pcall(lua, 2, 0, 0);
    resetGraphics();
    ofPopMatrix();
    ofPopStyle();
    if (status) {
        error = std::string(method) + ": " + luaError(lua);
        ofLogError("mode") << error;
    }
    lua_settop(lua, top);
    return status == 0;
}
void ModeRuntime::snapshot(double time, double dt, const std::array<double, 5> &knobs,
                           const eyesy::Analysis &a, const eyesy::MidiState &midi, bool trig,
                           bool autoClear, const std::vector<eyesy::MidiEvent> &events) {
    if (!lua)
        return;
    if (!audioPixels.isAllocated())
        audioPixels.allocate(eyesy::fftSize, 2, OF_PIXELS_GRAY);
    for (size_t i = 0; i < eyesy::fftSize; ++i) {
        audioPixels[i] = std::clamp((a.left[i] + 1) * 127.5f, 0.0f, 255.0f);
        audioPixels[i + eyesy::fftSize] = std::clamp((a.right[i] + 1) * 127.5f, 0.0f, 255.0f);
    }
    audioTexture.loadData(audioPixels);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, contextRef);
    number(lua, "time", time);
    number(lua, "dt", dt);
    lua_pushboolean(lua, trig);
    lua_setfield(lua, -2, "trigger");
    lua_pushboolean(lua, autoClear);
    lua_setfield(lua, -2, "auto_clear");
    array(lua, knobs);
    lua_setfield(lua, -2, "knobs");
    lua_newtable(lua);
    for (auto &entry : parameters) {
        auto &p = entry.second;
        if (p.knob >= 0)
            p.applyKnob(knobs[p.knob]);
        number(lua, p.name.c_str(), p.value);
    }
    lua_setfield(lua, -2, "params");
    lua_newtable(lua);
    array(lua, a.left);
    lua_setfield(lua, -2, "left");
    array(lua, a.right);
    lua_setfield(lua, -2, "right");
    array(lua, a.spectrumL);
    lua_setfield(lua, -2, "fft_left");
    array(lua, a.spectrumR);
    lua_setfield(lua, -2, "fft_right");
    array(lua, a.bands);
    lua_setfield(lua, -2, "bands");
    number(lua, "peak_left", a.peakL);
    number(lua, "peak_right", a.peakR);
    number(lua, "rms_left", a.rmsL);
    number(lua, "rms_right", a.rmsR);
    number(lua, "sample_rate", a.sampleRate);
    number(lua, "age", std::max(0.0, time - a.timestamp));
    lua_pushboolean(lua, a.available);
    lua_setfield(lua, -2, "available");
    lua_setfield(lua, -2, "audio");
    lua_newtable(lua);
    array(lua, midi.notes);
    lua_setfield(lua, -2, "notes");
    array(lua, midi.cc);
    lua_setfield(lua, -2, "cc");
    number(lua, "clocks", midi.clocks);
    lua_newtable(lua);
    int eventIndex = 1;
    for (auto &event : events) {
        lua_newtable(lua);
        number(lua, "status", event.type);
        number(lua, "channel", event.channel + 1);
        number(lua, "a", event.a);
        number(lua, "b", event.b);
        number(lua, "time", event.timestamp);
        lua_rawseti(lua, -2, eventIndex++);
    }
    lua_setfield(lua, -2, "events");
    lua_pushboolean(lua, midi.playing);
    lua_setfield(lua, -2, "playing");
    lua_setfield(lua, -2, "midi");
    lua_pop(lua, 1);
}
ofJson ModeRuntime::save() {
    if (!lua || modeRef == LUA_NOREF || !error.empty())
        return ofJson::object();
    int top = lua_gettop(lua);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, modeRef);
    lua_getfield(lua, -1, "save");
    if (lua_isnil(lua, -1)) {
        lua_settop(lua, top);
        return ofJson::object();
    }
    if (lua_pcall(lua, 0, 1, 0)) {
        std::string e = luaError(lua);
        lua_settop(lua, top);
        throw std::runtime_error(e);
    }
    try {
        auto result = readJson(lua, -1);
        lua_settop(lua, top);
        return result;
    } catch (...) {
        lua_settop(lua, top);
        throw;
    }
}
bool ModeRuntime::restore(const ofJson &state) {
    if (!lua || modeRef == LUA_NOREF)
        return false;
    int top = lua_gettop(lua);
    lua_rawgeti(lua, LUA_REGISTRYINDEX, modeRef);
    lua_getfield(lua, -1, "restore");
    if (lua_isnil(lua, -1)) {
        lua_settop(lua, top);
        return true;
    }
    pushJson(lua, state);
    int status = lua_pcall(lua, 1, 0, 0);
    if (status)
        error = luaError(lua);
    lua_settop(lua, top);
    return !status;
}
int ModeRuntime::dispatch(lua_State *l) {
    auto self = static_cast<ModeRuntime *>(lua_touserdata(l, lua_upvalueindex(1)));
    try {
        return self->invoke(l, lua_tointeger(l, lua_upvalueindex(2)));
    } catch (const std::exception &e) {
        lua_pushstring(l, e.what());
    }
    return lua_error(l);
}
int ModeRuntime::invoke(lua_State *l, int op) {
    auto n = [&](int i, double fallback = 0) {
        if (lua_isnoneornil(l, i))
            return fallback;
        if (!lua_isnumber(l, i))
            throw std::runtime_error("graphics value must be numeric");
        double v = lua_tonumber(l, i);
        if (!std::isfinite(v))
            throw std::runtime_error("nonfinite graphics value");
        return v;
    };
    auto integer = [&](int i, const char *what) {
        if (!lua_isnumber(l, i))
            throw std::runtime_error(std::string(what) + " must be an integer");
        double value = lua_tonumber(l, i);
        if (!std::isfinite(value) || std::trunc(value) != value || value < INT_MIN ||
            value > INT_MAX)
            throw std::runtime_error(std::string(what) + " must be an integer");
        return int(value);
    };
    auto id = [&](int i) { return integer(i, "handle"); };
    auto string = [&](int i, const char *what) {
        if (!lua_isstring(l, i))
            throw std::runtime_error(std::string(what) + " must be a string");
        return std::string(lua_tostring(l, i));
    };
    auto table = [&](int i, const char *what) {
        if (!lua_istable(l, i))
            throw std::runtime_error(std::string(what) + " must be a table");
    };
    switch (op) {
    case CLEAR:
        ofClear(n(1) * 255, n(2) * 255, n(3) * 255, n(4, 1) * 255);
        break;
    case COLOR:
        ofSetColor(n(1) * 255, n(2) * 255, n(3) * 255, n(4, 1) * 255);
        break;
    case RECT:
        ofDrawRectangle(n(1), n(2), n(3), n(4));
        break;
    case CIRCLE:
        ofDrawCircle(n(1), n(2), n(3));
        break;
    case LINE:
        ofSetLineWidth(n(5, 1));
        ofDrawLine(n(1), n(2), n(3), n(4));
        break;
    case TEXT:
        ofDrawBitmapString(string(1, "text"), n(2), n(3));
        break;
    case PUSH:
        if (matrixDepth >= 32)
            throw std::runtime_error("matrix stack exceeds 32");
        ofPushMatrix();
        ++matrixDepth;
        break;
    case POP:
        if (matrixDepth == 0)
            throw std::runtime_error("matrix stack underflow");
        ofPopMatrix();
        --matrixDepth;
        break;
    case TRANSLATE:
        ofTranslate(n(1), n(2), n(3));
        break;
    case ROTATE:
        ofRotateDeg(n(1), n(2), n(3), n(4, 1));
        break;
    case SCALE:
        ofScale(n(1, 1), n(2, 1), n(3, 1));
        break;
    case DEPTH:
        if (lua_toboolean(l, 1))
            ofEnableDepthTest();
        else
            ofDisableDepthTest();
        break;
    case PARAM: {
        std::string name = string(1, "palette name");
        double def = n(2), minimum = n(3), maximum = n(4, 1);
        int knob = id(5) - 1;
        if (name.empty() || minimum >= maximum || knob < -1 || knob > 4)
            throw std::runtime_error("invalid parameter range or knob (0=unassigned, 1..5=knob)");
        if (parameters.count(name))
            throw std::runtime_error("duplicate parameter");
        parameters[name] = {name, std::clamp(def, minimum, maximum), minimum, maximum, knob};
        break;
    }
    case RANDOM:
        randomState ^= randomState << 13;
        randomState ^= randomState >> 17;
        randomState ^= randomState << 5;
        lua_pushnumber(l, double(randomState) / 4294967296.0);
        return 1;
    case LFO:
        lua_pushnumber(l, .5 + .5 * std::sin(n(1) * n(2, 1) * TWO_PI + n(3) * TWO_PI));
        return 1;
    case PALETTE:
        if (lua_isnumber(l, 1)) {
            for (int i = 0; i < 3; ++i)
                lua_pushnumber(l, .5 + .5 * std::cos(TWO_PI * (n(1) + i / 3.0)));
            return 3;
        }
        {
            std::string name = string(1, "palette name");
            auto it = palettes.find(name);
            if (it == palettes.end())
                throw std::runtime_error("unknown palette: " + name);
            double phase = n(2);
            phase -= std::floor(phase);
            const auto &stops = it->second;
            double scaled = phase * (stops.size() - 1);
            size_t a = std::min<size_t>(size_t(scaled), stops.size() - 2);
            float t = float(scaled - a);
            for (int i = 0; i < 3; ++i)
                lua_pushnumber(l, stops[a][i] * (1 - t) + stops[a + 1][i] * t);
        }
        return 3;
    case PALETTE_FG:
    case PALETTE_BG: {
        std::array<float, 3> color{1, 1, 1};
        if (palettes_global) {
            double phase = n(1);
            color = op == PALETTE_FG ? palettes_global->sampleFg(phase)
                                     : palettes_global->sampleBg(phase);
        }
        for (float channel : color)
            lua_pushnumber(l, channel);
        return 3;
    }
    case PALETTE_DEFINE: {
        std::string name = string(1, "palette name");
        table(2, "palette stops");
        size_t count = lua_objlen(l, 2);
        if (name.empty() || name.size() > 64 || count < 2 || count > 16)
            throw std::runtime_error("palette needs a name and 2..16 RGB stops");
        if (!palettes.count(name) && palettes.size() >= 32)
            throw std::runtime_error("palette budget exceeded (32 names)");
        std::vector<std::array<float, 3>> stops;
        stops.reserve(count);
        for (size_t i = 1; i <= count; ++i) {
            lua_rawgeti(l, 2, i);
            table(-1, "palette stop");
            if (lua_objlen(l, -1) != 3) {
                lua_pop(l, 1);
                throw std::runtime_error("palette stops must be RGB triples");
            }
            std::array<float, 3> stop{};
            for (int c = 0; c < 3; ++c) {
                lua_rawgeti(l, -1, c + 1);
                double value = n(-1);
                lua_pop(l, 1);
                stop[c] = float(std::clamp(value, 0.0, 1.0));
            }
            lua_pop(l, 1);
            stops.push_back(stop);
        }
        palettes[name] = std::move(stops);
        break;
    }
    case FBO_NEW: {
        int w = id(1), h = id(2);
        if (w < 1 || h < 1 || w > width || h > height || fbos.size() >= 8)
            throw std::runtime_error("target exceeds size/count budget");
        auto fbo = std::make_shared<ofFbo>();
        ofFbo::Settings s;
        s.width = w;
        s.height = h;
        s.internalformat = GL_RGBA;
        s.textureTarget = GL_TEXTURE_2D;
        s.useDepth = true;
        fbo->allocate(s);
        if (!fbo->isAllocated())
            throw std::runtime_error("render target allocation failed");
        fbo->begin();
        ofClear(0, 0, 0, 255);
        fbo->end();
        int handle = nextHandle++;
        fbos[handle] = fbo;
        lua_pushinteger(l, handle);
        return 1;
    }
    case FBO_BEGIN: {
        int handle = id(1);
        if (!fbos.count(handle) || !targetStack.empty())
            throw std::runtime_error("invalid or nested render target");
        fbos.at(handle)->begin();
        targetStack.push_back(handle);
        break;
    }
    case FBO_END:
        if (targetStack.empty())
            throw std::runtime_error("no active target");
        fbos.at(targetStack.back())->end();
        targetStack.pop_back();
        break;
    case FBO_DRAW: {
        int handle = id(1);
        if (!fbos.count(handle) || (!targetStack.empty() && targetStack.back() == handle))
            throw std::runtime_error("invalid target or feedback read/write alias");
        fbos.at(handle)->draw(n(2), n(3), n(4, width), n(5, height));
        break;
    }
    case IMAGE_NEW: {
        auto file = asset(string(1, "shader path"));
        auto image = std::make_shared<ofImage>();
        if (images.size() >= 32 || !image->load(file.string()))
            throw std::runtime_error("image load failed or budget exceeded");
        int handle = nextHandle++;
        images[handle] = image;
        lua_pushinteger(l, handle);
        return 1;
    }
    case IMAGE_DRAW:
        if (!images.count(id(1)))
            throw std::runtime_error("invalid image");
        images.at(id(1))->draw(n(2), n(3), n(4), n(5));
        break;
    case SHADER_NEW: {
        auto file = asset(string(1, "image path"));
        if (shaders.size() >= 16)
            throw std::runtime_error("shader budget exceeded");
        auto shader = compileShader(file);
        int handle = nextHandle++;
        shaders[handle] = shader;
        shaderFiles[handle] = file;
        lua_pushinteger(l, handle);
        return 1;
    }
    case SHADER_DRAW: {
        auto it = shaders.find(id(1));
        if (it == shaders.end())
            throw std::runtime_error("invalid shader");
        std::map<std::string, std::vector<float>> uniforms;
        if (lua_istable(l, 5)) {
            lua_pushnil(l);
            while (lua_next(l, 5)) {
                if (lua_type(l, -2) != LUA_TSTRING)
                    throw std::runtime_error("uniform names must be strings");
                std::string name = lua_tostring(l, -2);
                std::vector<float> values;
                if (lua_isnumber(l, -1))
                    values.push_back(lua_tonumber(l, -1));
                else if (lua_istable(l, -1)) {
                    auto count = lua_objlen(l, -1);
                    if (count < 1 || count > 4)
                        throw std::runtime_error("uniform vectors need 1..4 elements");
                    for (size_t j = 1; j <= count; ++j) {
                        lua_rawgeti(l, -1, j);
                        if (!lua_isnumber(l, -1))
                            throw std::runtime_error("uniform values must be numeric");
                        values.push_back(lua_tonumber(l, -1));
                        lua_pop(l, 1);
                    }
                } else
                    throw std::runtime_error("uniform value must be scalar or vector");
                for (float value : values)
                    if (!std::isfinite(value))
                        throw std::runtime_error("nonfinite uniform");
                uniforms[name] = values;
                lua_pop(l, 1);
                if (uniforms.size() > 64)
                    throw std::runtime_error("uniform budget exceeded");
            }
        }
        std::map<std::string, int> textures;
        if (lua_istable(l, 6)) {
            lua_pushnil(l);
            while (lua_next(l, 6)) {
                if (lua_type(l, -2) != LUA_TSTRING || !lua_isnumber(l, -1))
                    throw std::runtime_error("textures map names to target handles");
                int handle = integer(-1, "texture handle");
                if (!fbos.count(handle) || (!targetStack.empty() && targetStack.back() == handle))
                    throw std::runtime_error("invalid texture or feedback read/write alias");
                textures[lua_tostring(l, -2)] = handle;
                lua_pop(l, 1);
                if (textures.size() > 6)
                    throw std::runtime_error("texture unit budget exceeded");
            }
        }
        double time = n(2), energy = n(3), control = n(4, .5);
        const int renderWidth = targetStack.empty() ? width : int(fbos.at(targetStack.back())->getWidth());
        const int renderHeight = targetStack.empty() ? height : int(fbos.at(targetStack.back())->getHeight());
        auto &s = *it->second;
        s.begin();
        s.setUniform2f("u_resolution", renderWidth, renderHeight);
        s.setUniform1f("u_time", time);
        s.setUniform1f("u_energy", energy);
        s.setUniform1f("u_control", control);
        if (audioTexture.isAllocated())
            s.setUniformTexture("u_audio", audioTexture, 0);
        for (auto &entry : uniforms) {
            auto &v = entry.second;
            switch (v.size()) {
            case 1:
                s.setUniform1f(entry.first, v[0]);
                break;
            case 2:
                s.setUniform2f(entry.first, v[0], v[1]);
                break;
            case 3:
                s.setUniform3f(entry.first, v[0], v[1], v[2]);
                break;
            case 4:
                s.setUniform4f(entry.first, v[0], v[1], v[2], v[3]);
                break;
            }
        }
        int textureUnit = 1;
        for (auto &entry : textures)
            s.setUniformTexture(entry.first, fbos.at(entry.second)->getTexture(), textureUnit++);
        ofDrawRectangle(0, 0, renderWidth, renderHeight);
        s.end();
        break;
    }
    case MESH: {
        table(1, "mesh vertices");
        size_t count = lua_objlen(l, 1);
        if (count > 8192)
            throw std::runtime_error("mesh exceeds 8192 vertices");
        ofMesh mesh;
        mesh.setMode(OF_PRIMITIVE_LINE_STRIP);
        for (size_t i = 1; i <= count; ++i) {
            lua_rawgeti(l, 1, i);
            if (!lua_istable(l, -1)) {
                lua_pop(l, 1);
                throw std::runtime_error("vertex must be xyz table");
            }
            if (lua_objlen(l, -1) != 3) {
                lua_pop(l, 1);
                throw std::runtime_error("vertex must be xyz table");
            }
            glm::vec3 p;
            for (int c = 0; c < 3; ++c) {
                lua_rawgeti(l, -1, c + 1);
                if (!lua_isnumber(l, -1) || !std::isfinite(lua_tonumber(l, -1))) {
                    lua_pop(l, 1);
                    lua_pop(l, 1);
                    throw std::runtime_error("mesh coordinate must be finite numeric");
                }
                p[c] = lua_tonumber(l, -1);
                lua_pop(l, 1);
            }
            lua_pop(l, 1);
            mesh.addVertex(p);
        }
        mesh.draw();
        break;
    }
    case MESH_NEW: {
        if (meshes.size() >= 32)
            throw std::runtime_error("mesh budget exceeded");
        int handle = nextHandle++;
        meshes[handle] = std::make_shared<ofVboMesh>();
        lua_pushinteger(l, handle);
        return 1;
    }
    case MESH_UPDATE: {
        auto it = meshes.find(id(1));
        if (it == meshes.end())
            throw std::runtime_error("invalid mesh");
        table(2, "mesh vertices");
        size_t count = lua_objlen(l, 2);
        if (count > 8192)
            throw std::runtime_error("mesh vertex budget exceeded");
        auto &mesh = *it->second;
        mesh.clear();
        mesh.setMode(lua_istable(l, 3) ? OF_PRIMITIVE_TRIANGLES : OF_PRIMITIVE_LINE_STRIP);
        for (size_t i = 1; i <= count; ++i) {
            lua_rawgeti(l, 2, i);
            if (!lua_istable(l, -1)) {
                lua_pop(l, 1);
                throw std::runtime_error("vertex must be xyz table");
            }
            if (lua_objlen(l, -1) != 3) {
                lua_pop(l, 1);
                throw std::runtime_error("vertex must be xyz table");
            }
            glm::vec3 point;
            for (int c = 0; c < 3; ++c) {
                lua_rawgeti(l, -1, c + 1);
                if (!lua_isnumber(l, -1) || !std::isfinite(lua_tonumber(l, -1))) {
                    lua_pop(l, 2);
                    throw std::runtime_error("mesh coordinate must be finite numeric");
                }
                double value = lua_tonumber(l, -1);
                lua_pop(l, 1);
                if (!std::isfinite(value))
                    throw std::runtime_error("invalid mesh coordinate");
                point[c] = value;
            }
            lua_pop(l, 1);
            mesh.addVertex(point);
        }
        if (lua_istable(l, 3)) {
            size_t indices = lua_objlen(l, 3);
            if (indices > 49152 || indices % 3)
                throw std::runtime_error("indices must be triangle triples");
            for (size_t i = 1; i <= indices; ++i) {
                lua_rawgeti(l, 3, i);
                int v = integer(-1, "mesh index");
                lua_pop(l, 1);
                if (v < 1 || v > int(count))
                    throw std::runtime_error("mesh index out of range");
                mesh.addIndex(v - 1);
            }
        }
        break;
    }
    case MESH_DRAW: {
        if (!meshes.count(id(1)))
            throw std::runtime_error("invalid mesh");
        // OF 0.12.1's expanded line shader expects adjacency attributes built
        // by its ofMesh path. Raw VBO line strips lack those attributes.
        // Use the native line shader for reusable line-strip VBOs only.
        auto renderer = std::dynamic_pointer_cast<ofGLProgrammableRenderer>(ofGetCurrentRenderer());
        bool restoreLines = renderer && renderer->areLinesShadersEnabled() &&
                            meshes.at(id(1))->getMode() == OF_PRIMITIVE_LINE_STRIP;
        if (restoreLines)
            renderer->disableLinesShaders();
        try {
            meshes.at(id(1))->draw();
        } catch (...) {
            if (restoreLines)
                renderer->enableLinesShaders();
            throw;
        }
        if (restoreLines)
            renderer->enableLinesShaders();
        break;
    }
    case CAMERA_BEGIN:
        if (cameraActive || matrixDepth)
            throw std::runtime_error("camera must begin before matrix transforms");
        camera.setPosition(n(1), n(2), n(3, 800));
        camera.lookAt(glm::vec3(n(4), n(5), n(6)));
        camera.setNearClip(1);
        camera.setFarClip(10000);
        camera.begin();
        cameraActive = true;
        break;
    case CAMERA_END:
        if (!cameraActive || matrixDepth)
            throw std::runtime_error("unbalanced camera/matrix stack");
        camera.end();
        cameraActive = false;
        break;
    }
    return 0;
}
std::shared_ptr<ofShader> ModeRuntime::compileShader(const std::filesystem::path &file) {
    std::ifstream in(file);
    if (!in)
        throw std::runtime_error("shader file missing");
    std::string body((std::istreambuf_iterator<char>(in)), {});
    bool es =
        std::string(reinterpret_cast<const char *>(glGetString(GL_VERSION))).find("OpenGL ES") !=
        std::string::npos;
    std::string vertex = es ? "precision highp float;\nattribute vec4 position;\nvarying vec2 uv;\n"
                            : "#version 150\nin vec4 position;\nout vec2 uv;\n";
    vertex += "uniform mat4 modelViewProjectionMatrix; uniform vec2 u_resolution; void main(){ "
              "uv=position.xy/u_resolution; gl_Position=modelViewProjectionMatrix*position; }";
    std::string fragment = es ? "precision mediump float;\n"
                              : "#version 150\n#define varying in\n#define texture2D texture\nout "
                                "vec4 outputColor;\n#define gl_FragColor outputColor\n";
    auto shader = std::make_shared<ofShader>();
    if (!shader->setupShaderFromSource(GL_VERTEX_SHADER, vertex) ||
        !shader->setupShaderFromSource(GL_FRAGMENT_SHADER, fragment + body))
        throw std::runtime_error("shader compilation failed: " + file.filename().string());
    shader->bindDefaults();
    if (!shader->linkProgram())
        throw std::runtime_error("shader link failed");
    return shader;
}
bool ModeRuntime::reloadShaders() {
    try {
        std::map<int, std::shared_ptr<ofShader>> candidates;
        for (auto &entry : shaderFiles)
            candidates[entry.first] = compileShader(entry.second);
        shaders.swap(candidates);
        shaderWarning.clear();
        return true;
    } catch (const std::exception &e) {
        shaderWarning = e.what();
        return false;
    }
}
