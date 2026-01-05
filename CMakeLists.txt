cmake_minimum_required(VERSION 3.12)
project(StarlinkBeamHunter LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CUDA_STANDARD 17)

# Find Dependencies
find_package(CUDA REQUIRED)
find_package(UHD REQUIRED)
find_package(ZeroMQ REQUIRED)
find_package(nlohmann_json REQUIRED)

# Includes
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${UHD_INCLUDE_DIRS}
    ${ZeroMQ_INCLUDE_DIRS}
)

# Source Files
# We compile main.cu with nvcc because it includes cuda code directly
set(SOURCES
    src/main.cu
    # kernels/beam_detector.cu # Included directly in main.cu for this prototype
)

# Executable
add_executable(starlink_hunter ${SOURCES})

# Hardware architecture flags (Ampere, etc.) - Adjust for user's GPU
set_property(TARGET starlink_hunter PROPERTY CUDA_ARCHITECTURES 86) 

# Link Libraries
target_link_libraries(starlink_hunter
    ${UHD_LIBRARIES}
    cuda
    cudart
    cufft
    libzmq
    nlohmann_json::nlohmann_json
)

# Compiler options
if(MSVC)
    target_compile_options(starlink_hunter PRIVATE /W4)
else()
    target_compile_options(starlink_hunter PRIVATE -Wall -Wextra)
endif()
