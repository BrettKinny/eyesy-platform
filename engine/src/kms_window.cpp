#include "kms_window.h"
#include "ofAppRunner.h"
#include "ofEvents.h"
#include "ofMainLoop.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#if defined(TARGET_LINUX) && defined(TARGET_OPENGLES)
#include "ofGLProgrammableRenderer.h"
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <fcntl.h>
#include <gbm.h>
#include <cerrno>
#include <poll.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

// Direct KMS/GBM scanout window: EGL renders into a GBM surface, and each
// finished frame is committed with a vsync'd page flip on the HDMI connector.
// Mode blobs come only from the kernel's connector list; on this BCM2837
// board, client-constructed modes have twice left the transmitter latched
// (HDMI_VID_CTL bit 25, blanked pixels until power cycle), and Xorg's blobs
// additionally arrive name-less with zero flags. See
// docs/HDMI-DISPLAY-ISSUE.md before changing mode handling.

// Nonempty when the mode chooser fell back to modes[0]; surfaced in
// status.json by the engine (see kmsModeFallbackNote) so the fallback is
// loud without a console.
static std::string kmsModeFallbackNoteValue;
class KmsWindow final : public ofAppBaseGLESWindow {
  public:
    KmsWindow() : coreEvents(new ofCoreEvents) {}
    ~KmsWindow() override {
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
        (void)settings;
        drmFd = open("/dev/dri/card0", O_RDWR | O_CLOEXEC);
        if (drmFd < 0)
            throw std::runtime_error("KMS: cannot open /dev/dri/card0");
        if (drmSetMaster(drmFd) != 0)
            throw std::runtime_error(
                "KMS: cannot acquire DRM master (another display client, e.g. "
                "stock eyesypy or Xorg, holds the card; stop it first)");

        gbm = gbm_create_device(drmFd);
        if (!gbm)
            throw std::runtime_error("KMS: gbm_create_device failed");

        pickConnectorAndMode();

        gbmSurface = gbm_surface_create(gbm, width, height, GBM_FORMAT_XRGB8888,
                                        GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
        if (!gbmSurface)
            throw std::runtime_error("KMS: gbm_surface_create failed");

        auto getPlatform = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(
            eglGetProcAddress("eglGetPlatformDisplayEXT"));
        if (!getPlatform)
            throw std::runtime_error("EGL platform display extension unavailable");
        display = getPlatform(EGL_PLATFORM_GBM_MESA, gbm, nullptr);
        if (display == EGL_NO_DISPLAY || !eglInitialize(display, nullptr, nullptr))
            throw std::runtime_error("EGL GBM initialization failed");
        if (!eglBindAPI(EGL_OPENGL_ES_API))
            throw std::runtime_error("EGL GLES API bind failed");
        const EGLint configAttrs[] = {EGL_SURFACE_TYPE,
                                      EGL_WINDOW_BIT,
                                      EGL_RENDERABLE_TYPE,
                                      EGL_OPENGL_ES2_BIT,
                                      EGL_RED_SIZE,
                                      8,
                                      EGL_GREEN_SIZE,
                                      8,
                                      EGL_BLUE_SIZE,
                                      8,
                                      EGL_ALPHA_SIZE,
                                      0,
                                      EGL_NONE};
        EGLint count = 0;
        if (!eglChooseConfig(display, configAttrs, &config, 1, &count) || count != 1)
            throw std::runtime_error("KMS: no EGL GLES2 window config");
        surface = eglCreateWindowSurface(display, config,
                                         reinterpret_cast<EGLNativeWindowType>(gbmSurface), nullptr);
        const EGLint contextAttrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
        context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttrs);
        if (surface == EGL_NO_SURFACE || context == EGL_NO_CONTEXT ||
            !eglMakeCurrent(display, surface, surface, context))
            throw std::runtime_error("KMS: EGL window/context creation failed");

        rendererPtr = std::make_shared<ofGLProgrammableRenderer>(this);
        static_cast<ofGLProgrammableRenderer *>(rendererPtr.get())->setup(2, 0);
        glViewport(0, 0, width, height);

        // Commit the first frame so the CRTC drives HDMI immediately.
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        present();
        fprintf(stderr, "KMS: scanout live %dx%d on crtc %u\n", width, height, crtcId);
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
        for (auto &entry : framebuffers) {
            if (entry.second)
                drmModeRmFB(drmFd, entry.second);
        }
        framebuffers.clear();
        // Deliberately leaves the last scanout CRTC enabled: stock SDL/KMSDRM
        // behaves the same, and the next client re-modesets over it.
        if (retiredBo)
            gbm_surface_release_buffer(gbmSurface, retiredBo);
        retiredBo = nullptr;
        if (frontBo)
            gbm_surface_release_buffer(gbmSurface, frontBo);
        frontBo = nullptr;
        if (gbmSurface) {
            gbm_surface_destroy(gbmSurface);
            gbmSurface = nullptr;
        }
        if (gbm) {
            gbm_device_destroy(gbm);
            gbm = nullptr;
        }
        if (drmFd >= 0) {
            drmDropMaster(drmFd);
            ::close(drmFd);
            drmFd = -1;
        }
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
        return OF_FULLSCREEN;
    }
    void makeCurrent() override {
        eglMakeCurrent(display, surface, surface, context);
    }
    void swapBuffers() override {
        present();
    }
    void startRender() override {
        makeCurrent();
        rendererPtr->startRender();
    }
    void finishRender() override {
        rendererPtr->finishRender();
        glFinish();
        present();
    }
    EGLDisplay getEGLDisplay() override {
        return display;
    }
    EGLContext getEGLContext() override {
        return context;
    }
    EGLSurface getEGLSurface() override {
        return surface;
    }

  private:
    void pickConnectorAndMode() {
        auto *res = drmModeGetResources(drmFd);
        if (!res)
            throw std::runtime_error("KMS: drmModeGetResources failed");
        std::unique_ptr<drmModeRes, void (*)(drmModeRes *)> resGuard(
            res, [](drmModeRes *p) { drmModeFreeResources(p); });

        drmModeConnector *connector = nullptr;
        int bestScore = -1;
        std::vector<drmModeConnector *> connectors;
        for (int i = 0; i < res->count_connectors; ++i) {
            drmModeConnector *candidate = drmModeGetConnector(drmFd, res->connectors[i]);
            if (!candidate)
                continue;
            connectors.emplace_back(candidate);
            if (candidate->connection != DRM_MODE_CONNECTED)
                continue;
            // HDMI first: composite is always "connected" and never wanted.
            int score = strstr(drmModeGetConnectorTypeName(candidate->connector_type), "HDMI") ? 2 : 1;
            if (score > bestScore) {
                bestScore = score;
                connector = candidate;
            }
        }
        auto freeConnectors = [&connectors]() {
            for (auto *c : connectors)
                drmModeFreeConnector(c);
        };
        if (bestScore < 0) {
            freeConnectors();
            throw std::runtime_error(
                "KMS: no connected display (is an HDMI sink attached and, on the "
                "capture bench, is the dongle streamer keeping HPD asserted?)");
        }
        if (connector->count_modes <= 0) {
            freeConnectors();
            throw std::runtime_error("KMS: connected display reports no modes (EDID missing)");
        }

        drmModeModeInfo *chosen = nullptr;
        // An operator preference (--video-mode, set from the menu) is honored
        // only when the kernel's EDID list offers a matching mode: blobs are
        // never constructed here (see docs/HDMI-DISPLAY-ISSUE.md).
        int wantWidth = 0, wantHeight = 0;
        double wantRate = 0;
        if (!modePreference.empty() &&
            sscanf(modePreference.c_str(), "%dx%d@%lf", &wantWidth, &wantHeight, &wantRate) >= 2)
            for (int i = 0; i < connector->count_modes; ++i) {
                auto &m = connector->modes[i];
                if (m.hdisplay == wantWidth && m.vdisplay == wantHeight &&
                    (wantRate <= 0 || std::abs(double(m.vrefresh) - wantRate) < 1.5)) {
                    chosen = &m;
                    break;
                }
            }
        if (!chosen)
            for (int i = 0; i < connector->count_modes; ++i) {
                auto &m = connector->modes[i];
                if (m.hdisplay == 1280 && m.vdisplay == 720 &&
                    m.vrefresh >= 55 && m.vrefresh <= 65) {
                    chosen = &m;
                    break;
                }
            }
        if (!chosen) {
            chosen = &connector->modes[0];
            std::ostringstream note;
            if (!modePreference.empty())
                note << "requested " << modePreference << " is not in the EDID; ";
            note << "using modes[0] \"" << chosen->name << "\" " << chosen->hdisplay << "x"
                 << chosen->vdisplay << "@" << chosen->vrefresh;
            kmsModeFallbackNoteValue = note.str();
            fprintf(stderr, "KMS: WARNING mode fallback: %s\n", kmsModeFallbackNoteValue.c_str());
        }
        mode = *chosen;
        connectorId = connector->connector_id;
        width = mode.hdisplay;
        height = mode.vdisplay;
        fprintf(stderr,
                "KMS: connector %s mode \"%s\" %ux%u@%u clock %u flags 0x%x type 0x%x\n",
                drmModeGetConnectorTypeName(connector->connector_type), mode.name,
                mode.hdisplay, mode.vdisplay, mode.vrefresh,
                mode.clock, mode.flags, mode.type);
        if (!mode.name[0] || mode.flags == 0)
            fprintf(stderr, "KMS: WARNING degenerate kernel mode blob\n");

        // CRTC: prefer the connector's current encoder chain, then any
        // encoder whose possible_crtcs mask admits a free CRTC.
        std::vector<uint32_t> encoderIds;
        if (connector->encoder_id)
            encoderIds.push_back(connector->encoder_id);
        for (int i = 0; i < connector->count_encoders; ++i)
            if (connector->encoders[i] != connector->encoder_id)
                encoderIds.push_back(connector->encoders[i]);
        for (uint32_t encoderId : encoderIds) {
            drmModeEncoder *encoder = drmModeGetEncoder(drmFd, encoderId);
            if (!encoder)
                continue;
            std::unique_ptr<drmModeEncoder, void (*)(drmModeEncoder *)> encoderGuard(
                encoder, [](drmModeEncoder *p) { drmModeFreeEncoder(p); });
            if (encoder->crtc_id) {
                crtcId = encoder->crtc_id;
                break;
            }
            for (int c = 0; c < res->count_crtcs; ++c) {
                if (encoder->possible_crtcs & (1u << c)) {
                    crtcId = res->crtcs[c];
                    break;
                }
            }
            if (crtcId)
                break;
        }
        freeConnectors();
        if (!crtcId)
            throw std::runtime_error("KMS: no usable CRTC for connector");
    }

    uint32_t fbFor(gbm_bo *bo) {
        auto it = framebuffers.find(bo);
        if (it != framebuffers.end())
            return it->second;
        uint32_t handle = gbm_bo_get_handle(bo).u32;
        uint32_t stride = gbm_bo_get_stride(bo);
        uint32_t offset = 0;
        uint32_t fb = 0;
        if (drmModeAddFB2(drmFd, width, height, GBM_FORMAT_XRGB8888, &handle, &stride,
                          &offset, &fb, 0) != 0)
            throw std::runtime_error("KMS: drmModeAddFB2 failed");
        framebuffers.emplace(bo, fb);
        return fb;
    }

    static void pageFlipHandler(int, unsigned, unsigned, unsigned, void *userData) {
        auto *self = static_cast<KmsWindow *>(userData);
        self->flipPending = false;
        if (self->retiredBo) {
            gbm_surface_release_buffer(self->gbmSurface, self->retiredBo);
            self->retiredBo = nullptr;
        }
    }

    void waitForFlip() {
        if (!flipPending)
            return;
        pollfd pfd{drmFd, POLLIN, 0};
        int result;
        do {
            result = poll(&pfd, 1, 100);
        } while (result < 0 && errno == EINTR); // SIGTERM must not abort the flip wait; the
                                                // flag-driven exit happens in update().
        if (result < 0)
            throw std::runtime_error("KMS: page flip poll failed");
        if (result == 0) {
            // Timed out: treat the flip as complete and release its buffer
            // so the next frame never overwrites a lingering retired lock.
            flipPending = false;
            if (retiredBo) {
                gbm_surface_release_buffer(gbmSurface, retiredBo);
                retiredBo = nullptr;
            }
            return;
        }
        drmEventContext ctx{};
        ctx.version = DRM_EVENT_CONTEXT_VERSION;
        ctx.page_flip_handler = &KmsWindow::pageFlipHandler;
        drmHandleEvent(drmFd, &ctx);
    }

    void present() {
        if (!eglSwapBuffers(display, surface))
            throw std::runtime_error("KMS: eglSwapBuffers failed");
        gbm_bo *next = gbm_surface_lock_front_buffer(gbmSurface);
        if (!next)
            throw std::runtime_error("KMS: gbm_surface_lock_front_buffer failed");
        waitForFlip();
        uint32_t fb = fbFor(next);
        if (!frontBo) {
            if (drmModeSetCrtc(drmFd, crtcId, fb, 0, 0, &connectorId, 1, &mode) != 0)
                throw std::runtime_error("KMS: drmModeSetCrtc failed");
        } else {
            if (drmModePageFlip(drmFd, crtcId, fb, DRM_MODE_PAGE_FLIP_EVENT, this) != 0)
                throw std::runtime_error("KMS: drmModePageFlip failed");
            flipPending = true;
            retiredBo = frontBo;
        }
        frontBo = next;
    }

    int width = 0, height = 0;
    bool shouldClose = false;
    std::shared_ptr<ofCoreEvents> coreEvents;
    std::shared_ptr<ofBaseRenderer> rendererPtr;
    EGLDisplay display = EGL_NO_DISPLAY;
    EGLConfig config = nullptr;
    EGLSurface surface = EGL_NO_SURFACE;
    EGLContext context = EGL_NO_CONTEXT;
    int drmFd = -1;
    struct gbm_device *gbm = nullptr;
    struct gbm_surface *gbmSurface = nullptr;
    struct gbm_bo *frontBo = nullptr;
    struct gbm_bo *retiredBo = nullptr;
    bool flipPending = false;
    uint32_t connectorId = 0, crtcId = 0;
    drmModeModeInfo mode{};
    std::unordered_map<gbm_bo *, uint32_t> framebuffers;

  public:
    // Operator-requested output mode ("WxH" or "WxH@R"); empty follows the EDID.
    std::string modePreference;
};

std::shared_ptr<ofAppBaseWindow> createKmsWindow(const std::string &preference) {
    ofInit();
    auto window = std::make_shared<KmsWindow>();
    window->modePreference = preference;
    ofGetMainLoop()->addWindow(window);
    ofGLESWindowSettings settings;
    settings.setGLESVersion(2);
    window->setup(settings);
    return window;
}
#else
std::shared_ptr<ofAppBaseWindow> createKmsWindow(const std::string &) {
    throw std::runtime_error("KMS scanout window requires TARGET_LINUX + TARGET_OPENGLES");
}

#endif

std::string kmsModeFallbackNote() {
#if defined(TARGET_LINUX) && defined(TARGET_OPENGLES)
    return kmsModeFallbackNoteValue;
#else
    return {};
#endif
}