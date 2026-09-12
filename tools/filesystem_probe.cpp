// Small ARM-native diagnostic for the filesystem operations used by EngineApp.
#include <filesystem>
#include <iostream>
#include <string>

namespace fs = std::filesystem;
int main(int argc, char **argv) {
  if (argc != 2) { std::cerr << "usage: filesystem-probe PATH\n"; return 2; }
  try {
    fs::path root = fs::path(argv[1]);
    std::cout << "{\"stage\":\"start\",\"path\":\"" << root.string() << "\"}\n";
    size_t dirs = 0, files = 0;
    for (const auto &entry : fs::directory_iterator(root)) {
      ++dirs;
      std::cout << "{\"stage\":\"directory\",\"path\":\"" << entry.path().string() << "\"}\n";
      if (entry.is_directory() && fs::exists(entry.path() / "main.lua")) ++files;
    }
    std::cout << "{\"stage\":\"catalog\",\"entries\":" << dirs << ",\"modes\":" << files << "}\n";
    size_t watched = 0;
    for (const auto &entry : fs::recursive_directory_iterator(root)) {
      if (entry.is_regular_file()) {
        auto stamp = entry.last_write_time();
        (void)stamp;
        ++watched;
      }
    }
    std::cout << "{\"stage\":\"watch\",\"files\":" << watched << "}\n";
  } catch (const std::exception &e) {
    std::cerr << "filesystem-probe: " << e.what() << '\n'; return 1;
  }
  return 0;
}
