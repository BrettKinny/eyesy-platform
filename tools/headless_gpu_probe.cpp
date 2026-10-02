// SPDX-License-Identifier: BSD-3-Clause
// Standalone surfaceless EGL/GLES2 probe.  This tests an offscreen driver only;
// it does not test HDMI scanout, Xorg, audio, or engine performance.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

static bool has(const char *s, const char *needle) {
  return s && std::string(s).find(needle) != std::string::npos;
}
static void fail(const char *what) { std::cerr << "headless-gpu-probe: " << what << " (EGL/GL error 0x" << std::hex << (unsigned)(glGetError() ? glGetError() : eglGetError()) << ")\n"; std::exit(2); }
static GLuint shader(GLenum type, const char *source) {
  GLuint s = glCreateShader(type); glShaderSource(s, 1, &source, nullptr); glCompileShader(s);
  GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
  if (!ok) { char log[1024] = {}; glGetShaderInfoLog(s, sizeof(log), nullptr, log); std::cerr << log << '\n'; fail("shader compilation failed"); }
  return s;
}
static unsigned percentile(std::vector<unsigned> values, double p) {
  if (values.empty()) return 0;
  size_t i = static_cast<size_t>(p * (values.size() - 1));
  std::nth_element(values.begin(), values.begin() + i, values.end()); return values[i];
}
int main(int argc, char **argv) {
  int frames = 60; bool allow_software = false;
  for (int i = 1; i < argc; ++i) {
    if (!std::strcmp(argv[i], "--allow-software")) allow_software = true;
    else if (!std::strcmp(argv[i], "--frames") && i + 1 < argc) frames = std::atoi(argv[++i]);
    else { std::cerr << "usage: " << argv[0] << " [--frames N] [--allow-software]\n"; return 2; }
  }
  if (frames < 1 || frames > 600) { std::cerr << "frames must be 1..600\n"; return 2; }
  auto get_platform = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(eglGetProcAddress("eglGetPlatformDisplayEXT"));
  if (!get_platform) { std::cerr << "EGL_EXT_platform_base/eglGetPlatformDisplayEXT unavailable\n"; return 2; }
  EGLDisplay display = get_platform(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr);
  if (display == EGL_NO_DISPLAY || !eglInitialize(display, nullptr, nullptr)) fail("EGL initialization failed");
  eglBindAPI(EGL_OPENGL_ES_API);
  const EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT,
                          EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
  EGLConfig config; EGLint count = 0;
  if (!eglChooseConfig(display, attrs, &config, 1, &count) || count != 1) fail("no GLES2 pbuffer config");
  const EGLint pbuf[] = {EGL_WIDTH, 1280, EGL_HEIGHT, 720, EGL_NONE};
  EGLSurface surface = eglCreatePbufferSurface(display, config, pbuf);
  const EGLint ctx_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
  EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, ctx_attrs);
  if (surface == EGL_NO_SURFACE || context == EGL_NO_CONTEXT || !eglMakeCurrent(display, surface, surface, context)) fail("EGL context creation failed");
  const char *renderer = reinterpret_cast<const char *>(glGetString(GL_RENDERER));
  const char *vendor = reinterpret_cast<const char *>(glGetString(GL_VENDOR));
  const char *version = reinterpret_cast<const char *>(glGetString(GL_VERSION));
  bool software = has(renderer, "llvmpipe") || has(renderer, "softpipe") || has(renderer, "swrast");
  const char *vs = "attribute vec2 p; varying vec2 uv; void main(){uv=p*0.5+0.5;gl_Position=vec4(p,0,1);}";
  const char *fs = "precision mediump float; varying vec2 uv; void main(){gl_FragColor=vec4(uv.x,uv.y,0.25,1.0);}";
  GLuint program = glCreateProgram(), v = shader(GL_VERTEX_SHADER, vs), f = shader(GL_FRAGMENT_SHADER, fs);
  glAttachShader(program, v); glAttachShader(program, f); glBindAttribLocation(program, 0, "p"); glLinkProgram(program);
  GLint linked = 0; glGetProgramiv(program, GL_LINK_STATUS, &linked);
  if (!linked) fail("shader link failed");
  glUseProgram(program); const GLfloat quad[] = {-1,-1, 1,-1, -1,1, 1,1}; glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad); glEnableVertexAttribArray(0);
  glViewport(0, 0, 1280, 720); glClearColor(1, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT); glFinish();
  unsigned char pixel[4] = {}; glReadPixels(640, 360, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
  bool correctness = pixel[0] == 255 && pixel[1] == 0 && pixel[2] == 0 && pixel[3] == 255;
  glClearColor(0, 0, 0, 1); std::vector<unsigned> timings; timings.reserve(frames);
  for (int i = 0; i < frames; ++i) { auto start = std::chrono::steady_clock::now(); glDrawArrays(GL_TRIANGLE_STRIP, 0, 4); glFinish(); auto end = std::chrono::steady_clock::now(); timings.push_back((unsigned)std::chrono::duration_cast<std::chrono::microseconds>(end-start).count()); }
  unsigned char gradient[4] = {}; glReadPixels(640, 360, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, gradient);
  correctness = correctness && gradient[0] >= 126 && gradient[0] <= 129 && gradient[1] >= 126 && gradient[1] <= 129 && gradient[2] >= 63 && gradient[2] <= 65 && gradient[3] == 255;
  std::cout << "{\"renderer\":\"" << (renderer ? renderer : "") << "\",\"vendor\":\"" << (vendor ? vendor : "") << "\",\"version\":\"" << (version ? version : "") << "\",\"width\":1280,\"height\":720,\"frames\":" << frames << ",\"p50_us\":" << percentile(timings,.50) << ",\"p95_us\":" << percentile(timings,.95) << ",\"correctness\":" << (correctness ? "true" : "false") << ",\"software_renderer\":" << (software ? "true" : "false") << "}\n";
  eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT); eglDestroyContext(display, context); eglDestroySurface(display, surface); eglTerminate(display);
  return (!correctness || (software && !allow_software)) ? 1 : 0;
}
