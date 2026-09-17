#pragma once

#ifdef TARGET_OPENGLES
#include <EGL/egl.h>
#endif
#include "ofAppBaseWindow.h"
#include <memory>
#include <string>

// Creates a direct KMS/GBM GLES2 scanout window on TARGET_OPENGLES. The mode
// is always taken from the kernel connector's EDID-derived list (named,
// flagged); clients never construct a mode blob on this hardware (see
// docs/HDMI-DISPLAY-ISSUE.md). `preference` ("WxH" or "WxH@R") is honored only
// when the EDID offers a matching mode. The desktop build deliberately returns
// an unsupported window (see .cpp).
std::shared_ptr<ofAppBaseWindow> createKmsWindow(const std::string &preference = {});

// Nonempty when the mode chooser fell back to modes[0] instead of the
// preferred mode; the engine surfaces it in status.json so the fallback is
// visible without a console (warn, never crash).
std::string kmsModeFallbackNote();