#pragma once

#ifdef TARGET_OPENGLES
#include <EGL/egl.h>
#endif
#include "ofAppBaseWindow.h"
#include <memory>

// Creates an EGL surfaceless GLES2 pbuffer window on TARGET_OPENGLES.  The
// desktop build deliberately returns an unsupported window (see .cpp).
std::shared_ptr<ofAppBaseWindow> createOffscreenWindow(int width, int height);
