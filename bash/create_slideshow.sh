#!/bin/bash

# This script creates a video slideshow from a video and its corresponding subtitle file.
# The output video will have the same audio as the original, but the video frames will
# be static, changing only at the start of each subtitle line.

set -e

# --- Configuration ---
# You can change the output filename here
DEFAULT_OUTPUT_FILE="slideshow.mp4"

# --- Functions ---
function print_usage() {
    echo "Usage: $0 <input_file> [options]"
    echo "This script is a wrapper around the python script video_slideshow_generator.py"
    echo "For more detailed usage, run: python3 python/video_slideshow_generator.py --help"
}

function check_dependencies() {
    for cmd in ffmpeg awk grep sed paste tail; do
        if ! command -v $cmd &> /dev/null; then
            echo "Error: Required command '$cmd' not found. Please install it."
            exit 1
        fi
    done
}

# --- Main Script ---
check_dependencies

# Pass all arguments to the python script.
python3 python/video_slideshow_generator.py "$@"
