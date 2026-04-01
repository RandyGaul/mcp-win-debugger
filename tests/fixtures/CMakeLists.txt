cmake_minimum_required(VERSION 3.15)
project(windbg_mcp_test_fixtures C)

# Build test fixtures with debug symbols for cdb debugging tests.
# Usage:
#   cmake -B build -DCMAKE_BUILD_TYPE=Debug
#   cmake --build build

add_executable(crashme crashme.c)

# Ensure full debug info and no optimization
target_compile_options(crashme PRIVATE
    $<$<C_COMPILER_ID:MSVC>:/Zi /Od>
    $<$<NOT:$<C_COMPILER_ID:MSVC>>:-g -O0>
)

# MSVC: generate PDB alongside the exe
if(MSVC)
    set_target_properties(crashme PROPERTIES
        COMPILE_PDB_NAME crashme
        COMPILE_PDB_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    )
    target_link_options(crashme PRIVATE /DEBUG /PDB:${CMAKE_CURRENT_BINARY_DIR}/crashme.pdb)
endif()
