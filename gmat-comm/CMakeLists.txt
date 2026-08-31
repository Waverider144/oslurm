cmake_minimum_required(VERSION 3.20)
project(gmat_comm LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(gmat_comm_core
  core/src/communication_payload.cpp
  core/src/file_envelope_provider.cpp
  core/src/routing.cpp
)
target_include_directories(gmat_comm_core PUBLIC core/include)
target_compile_options(gmat_comm_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(gmat_comm_unit_tests tests/unit/core_tests.cpp)
target_link_libraries(gmat_comm_unit_tests PRIVATE gmat_comm_core)

add_executable(gmat_comm_demo examples/relay_demo/demo.cpp)
target_link_libraries(gmat_comm_demo PRIVATE gmat_comm_core)

enable_testing()
add_test(NAME core_tests COMMAND gmat_comm_unit_tests)
set_tests_properties(core_tests PROPERTIES WORKING_DIRECTORY ${CMAKE_SOURCE_DIR})
