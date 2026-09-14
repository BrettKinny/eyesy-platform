#pragma once

#ifdef TARGET_OPENGLES
#include <EGL/egl.h>
#endif
#include "ofAppBaseWindow.h"
#include <memory>

// Creates a direct KMS/GBM GLES2 scanout window on TARGET_OPENGLES. The mode
// is always taken from the kernel connector's EDID-derived list (named,
// flagged); clients never construct a mode blob on this hardware (see
// docs/HDMI-DISPLAY-ISSUE.md). The desktop build deliberately returns an
// unsupported window (see .cpp).
std::shared_ptr<ofAppBaseWindow> createKmsWindow();