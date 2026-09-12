include config.make
include $(OF_ROOT)/libs/openFrameworksCompiled/project/makefileCommon/compile.project.mk

# Keep OF's platform linker flags (stdc++fs, atomic, as-needed, etc.) while
# replacing only its cwd-relative rpath entries for relocatable deployment.
PLATFORM_LDFLAGS := $(filter-out -Wl$(EYESY_COMMA)-rpath=./libs:./bin/libs:./,$(PLATFORM_LDFLAGS))
PLATFORM_LDFLAGS += $(EYESY_ORIGIN_RPATH)
