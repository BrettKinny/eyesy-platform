OF_ROOT ?= /opt/of
PROJECT_ROOT = .
PROJECT_CFLAGS += $(shell pkg-config --cflags luajit alsa)
PROJECT_LDFLAGS += $(shell pkg-config --libs luajit alsa) -pthread
PROJECT_OPTIMIZATION_CFLAGS_RELEASE = -O2
PROJECT_DEFINES += EYESY_API_VERSION=1
ifeq ($(PLATFORM_ARCH),armv6l)
# The stock device/runtime combination exhibited a C++ runtime incompatibility
# with the Debian armhf build image. Package the matching pair beside the
# executable; never replace system libraries.
PROJECT_LDFLAGS += -lEGL -lGLESv2
endif

# OF's Linux platform makefile adds cwd-relative RUNPATH entries. The project
# Makefile filters those after OF loads its platform flags, preserving all
# other flags. Bundled libraries live in $ORIGIN/libs; $ORIGIN covers desktop
# libraries beside the executable.
EYESY_COMMA := ,
EYESY_ORIGIN_RPATH = -Wl$(EYESY_COMMA)-rpath,'$$ORIGIN/libs:$$ORIGIN'
