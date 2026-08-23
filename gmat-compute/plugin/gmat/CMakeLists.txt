cmake_minimum_required(VERSION 3.20)
project(gmat_compute_gmat_plugin LANGUAGES CXX)

# Placeholder for the real GMAT plugin target. This intentionally does not
# guess the local GMAT ABI. See docs/gmat-plugin.md and docs/environment.md.
add_library(gmat_compute_gmat_plugin_stub INTERFACE)
target_include_directories(gmat_compute_gmat_plugin_stub INTERFACE include)
