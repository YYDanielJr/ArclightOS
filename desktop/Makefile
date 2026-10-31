CXX ?= g++
VERSION := $(shell dpkg-parsechangelog -S Version)
CPPFLAGS += -DARCLIGHT_DESKTOP_VERSION=\"$(VERSION)\"
CPPFLAGS += $(shell pkg-config --cflags wayland-client)  $(shell pkg-config --cflags gtk+-3.0 libxml-2.0 gio-unix-2.0)
CXXFLAGS += -std=c++17 -Wall -Wextra -Wformat=2 -pthread
LDLIBS += $(shell pkg-config --libs gtk+-3.0 libxml-2.0 gio-unix-2.0) -ldl -lcrypt -pthread
COMMON = native/common.o native/display.o native/policy.o native/input.o native/upgrade.o
PROGRAMS = arclight-settings arclight-session arclight-system-policy arclight-file-tools arclight-screenshot arclight-archive arclight-resume-session
.PHONY: all clean check
all: $(PROGRAMS)
arclight-settings: native/app.o native/page_apply.o native/layout.o native/pages_devices.o native/pages_system.o native/pages_bluetooth.o native/pages_input.o native/pages_upgrade.o $(COMMON)
	$(CXX) $(LDFLAGS) -Wl,--export-dynamic -o $@ $^ $(LDLIBS)
arclight-session: native/session_main.o $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
arclight-system-policy: native/policy_main.o $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
arclight-file-tools: native/file_tools.o $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
PROTOCOLS = ext-foreign-toplevel-list ext-image-capture-source ext-image-copy-capture
PROTOCOL_OBJECTS = $(addprefix generated/,$(addsuffix .o,$(PROTOCOLS)))
generated/%.h:
	mkdir -p generated
	wayland-scanner client-header /usr/share/wayland-protocols/staging/$*/$*-v1.xml $@
generated/%.c: generated/%.h
	wayland-scanner private-code /usr/share/wayland-protocols/staging/$*/$*-v1.xml $@
generated/%.o: generated/%.c
	$(CC) -c $(shell pkg-config --cflags wayland-client) $< -o $@
native/screenshot_windows.o: $(addprefix generated/,$(addsuffix .h,$(PROTOCOLS)))
arclight-screenshot: native/screenshot.o native/screenshot_windows.o $(PROTOCOL_OBJECTS) $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS) -lwayland-client -lX11
arclight-archive: native/archive_app.o native/archive_progress_view.o native/archive.o $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS) -larchive
native-tests: native/tests.o native/archive.o $(COMMON)
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS) -larchive
native/archive.o native/archive_app.o native/archive_progress_view.o native/tests.o: native/archive.hpp
native/archive_app.o native/archive_progress_view.o: native/archive_progress_view.hpp
native/%.o: native/%.cpp native/common.hpp native/app.hpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@
arclight-resume-session: native/resume_session.o
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
check: native-tests arclight-resume-session
	./native-tests
	./arclight-resume-session --self-test
clean:
	rm -f native/*.o generated/*.o generated/*.c generated/*.h $(PROGRAMS) native-tests
