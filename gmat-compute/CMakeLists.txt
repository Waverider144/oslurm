cmake_minimum_required(VERSION 3.20)
project(gmat_compute LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(gmat_compute_core
  core/src/curves.cpp
  core/src/models.cpp
  core/src/compute_payload.cpp
  core/src/file_envelope_provider.cpp
)
target_include_directories(gmat_compute_core PUBLIC core/include)
target_compile_options(gmat_compute_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(gmat_compute_unit_tests tests/unit/core_tests.cpp)
target_link_libraries(gmat_compute_unit_tests PRIVATE gmat_compute_core)

add_executable(gmat_compute_demo examples/compute_satellite/demo.cpp)
target_link_libraries(gmat_compute_demo PRIVATE gmat_compute_core)

enable_testing()
add_test(NAME core_tests COMMAND gmat_compute_unit_tests)
set_tests_properties(core_tests PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
