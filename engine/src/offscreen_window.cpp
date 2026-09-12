#include "offscreen_window.h"
#include "ofAppRunner.h"
#include "ofEvents.h"
#include "ofMainLoop.h"
#include <stdexcept>

#ifdef TARGET_OPENGLES
#include "ofGLProgrammableRenderer.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>

class OffscreenWindow final : public ofAppBaseGLESWindow {
  public:
    OffscreenWindow() : coreEvents(new ofCoreEvents) {}
    ~OffscreenWindow() override {
        close();
    }
    static void loop() {}
    static void pollEvents() {}
    static bool doesLoop() {
        return false;
    }
    static bool allowsMultiWindow() {
        return false;
    }
    static bool needsPolling() {
        return false;
    }

    void setup(const ofGLESWindowSettings &settings) override {
        width = settings.getWidth();
        height = settings.getHeight();
        auto getPlatform = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(
            eglGetProcAddress("eglGetPlatformDisplayEXT"));
        if (!getPlatform)
            throw std::runtime_error("EGL platform display extension unavailable");
        display = getPlatform(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr);
        if (display == EGL_NO_DISPLAY || !eglInitialize(display, nullptr, nullptr))
            throw std::runtime_error("EGL surfaceless initialization failed");
        if (!eglBindAPI(EGL_OPENGL_ES_API))
            throw std::runtime_error("EGL GLES API bind failed");
        const EGLint configAttrs[] = {EGL_SURFACE_TYPE,
                                      EGL_PBUFFER_BIT,
                                      EGL_RENDERABLE_TYPE,
                                      EGL_OPENGL_ES2_BIT,
                                      EGL_RED_SIZE,
                                      8,
                                      EGL_GREEN_SIZE,
                                      8,
                                      EGL_BLUE_SIZE,
                                      8,
                                      EGL_ALPHA_SIZE,
                                      8,
                                      EGL_NONE};
        EGLint count = 0;
        if (!eglChooseConfig(display, configAttrs, &config, 1, &count) || count != 1)
            throw std::runtime_error("No EGL GLES2 pbuffer config");
        const EGLint surfaceAttrs[] = {EGL_WIDTH, width, EGL_HEIGHT, height, EGL_NONE};
        surface = eglCreatePbufferSurface(display, config, surfaceAttrs);
        const EGLint contextAttrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
        context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttrs);
        if (surface == EGL_NO_SURFACE || context == EGL_NO_CONTEXT ||
            !eglMakeCurrent(display, surface, surface, context))
            throw std::runtime_error("EGL pbuffer context creation failed");
        rendererPtr = std::make_shared<ofGLProgrammableRenderer>(this);
        static_cast<ofGLProgrammableRenderer *>(rendererPtr.get())->setup(2, 0);
        glViewport(0, 0, width, height);
    }
    void update() override {
        coreEvents->notifyUpdate();
    }
    void draw() override {
        startRender();
        rendererPtr->setupScreen();
        coreEvents->notifyDraw();
        finishRender();
    }
    bool getWindowShouldClose() override {
        return shouldClose;
    }
    void setWindowShouldClose() override {
        shouldClose = true;
    }
    void close() override {
        rendererPtr.reset();
        if (display != EGL_NO_DISPLAY) {
            eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
            if (context != EGL_NO_CONTEXT)
                eglDestroyContext(display, context);
            if (surface != EGL_NO_SURFACE)
                eglDestroySurface(display, surface);
            eglTerminate(display);
        }
        display = EGL_NO_DISPLAY;
        context = EGL_NO_CONTEXT;
        surface = EGL_NO_SURFACE;
        coreEvents->disable();
    }
    ofCoreEvents &events() override {
        return *coreEvents;
    }
    std::shared_ptr<ofBaseRenderer> &renderer() override {
        return rendererPtr;
    }
    int getWidth() override {
        return width;
    }
    int getHeight() override {
        return height;
    }
    glm::vec2 getWindowSize() override {
        return {width, height};
    }
    glm::vec2 getScreenSize() override {
        return {width, height};
    }
    ofWindowMode getWindowMode() override {
        return OF_WINDOW;
    }
    void makeCurrent() override {
        eglMakeCurrent(display, surface, surface, context);
    }
    void swapBuffers() override {
        eglSwapBuffers(display, surface);
    }
    void startRender() override {
        makeCurrent();
        rendererPtr->startRender();
    }
    void finishRender() override {
        rendererPtr->finishRender();
        glFinish();
        eglSwapBuffers(display, surface);
    }
#if defined(TARGET_LINUX) && defined(TARGET_OPENGLES)
    EGLDisplay getEGLDisplay() override {
        return display;
    }
    EGLContext getEGLContext() override {
        return context;
    }
    EGLSurface getEGLSurface() override {
        return surface;
    }
#endif
  private:
    int width = 0, height = 0;
    bool shouldClose = false;
    std::shared_ptr<ofCoreEvents> coreEvents;
    std::shared_ptr<ofBaseRenderer> rendererPtr;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLConfig config = nullptr;
    EGLSurface surface = EGL_NO_SURFACE;
    EGLContext context = EGL_NO_CONTEXT;
};
#endif

std::shared_ptr<ofAppBaseWindow> createOffscreenWindow(int width, int height) {
#ifdef TARGET_OPENGLES
    if (width <= 0 || height <= 0)
        throw std::invalid_argument("offscreen dimensions must be positive");
    ofInit();
    auto window = std::make_shared<OffscreenWindow>();
    ofGetMainLoop()->addWindow(window);
    ofGLESWindowSettings settings;
    settings.setSize(width, height);
    settings.setGLESVersion(2);
    window->setup(settings);
    return window;
#else
    (void)width;
    (void)height;
    throw std::runtime_error("offscreen EGL window requires TARGET_OPENGLES");
#endif
}
