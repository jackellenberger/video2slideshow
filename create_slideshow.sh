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
    echo "Usage: $0 <video_file> <subtitle_file> [output_file]"
    echo "  <video_file>: Path to the input video file."
    echo "  <subtitle_file>: Path to the input subtitle file (VTT or SRT format)."
    echo "  [output_file]: (Optional) Path to the output video file. Defaults to '$DEFAULT_OUTPUT_FILE'."
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

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    print_usage
    exit 1
fi

VIDEO_FILE="$1"
SUBTITLE_FILE="$2"
OUTPUT_FILE="${3:-$DEFAULT_OUTPUT_FILE}"
TMP_DIR=$(mktemp -d)

# Ensure the temporary directory is cleaned up on exit
trap 'rm -rf -- "$TMP_DIR"' EXIT

echo "Input Video: $VIDEO_FILE"
echo "Subtitle File: $SUBTITLE_FILE"
echo "Output File: $OUTPUT_FILE"
echo "Temporary directory: $TMP_DIR"
echo

# --- Subtitle Parsing ---
echo "Parsing subtitle file..."
# Extract start times from VTT or SRT subtitle file
# This command extracts lines that contain '-->', then uses sed to keep only the start time.
cat "$SUBTITLE_FILE" | grep -- '-->' | sed 's/ -->.*//' > "$TMP_DIR/start_times.txt"

if [ ! -s "$TMP_DIR/start_times.txt" ]; then
    echo "Error: Could not extract any timestamps from the subtitle file."
    echo "Please ensure the file is a valid VTT or SRT file."
    exit 1
fi

# --- Frame Extraction ---
echo "Extracting frames from video..."
# Get video duration
VIDEO_DURATION=$(ffmpeg -i "$VIDEO_FILE" 2>&1 | grep "Duration" | cut -d ' ' -f 4 | sed 's/,//' | head -n1)

# Create a file to store the list of frames and their durations for ffmpeg's concat demuxer
CONCAT_LIST_FILE="$TMP_DIR/concat_list.txt"

# Create a shell script to run all the ffmpeg commands for frame extraction
EXTRACT_FRAMES_SCRIPT="$TMP_DIR/extract_frames.sh"
touch "$EXTRACT_FRAMES_SCRIPT"
chmod +x "$EXTRACT_FRAMES_SCRIPT"

# Process the start times to generate the frame list and the extraction commands
paste -d, "$TMP_DIR/start_times.txt" <(tail -n +2 "$TMP_DIR/start_times.txt"; echo "$VIDEO_DURATION") | \
awk -F, -v video_file="$VIDEO_FILE" -v tmp_dir="$TMP_DIR" -v extract_script="$EXTRACT_FRAMES_SCRIPT" '
function time_to_seconds(time_str) {
    # Split time into seconds and milliseconds
    split(time_str, time_parts, ".");
    seconds_part = time_parts[1];
    milliseconds = time_parts[2];

    # Split seconds part into h, m, s
    split(seconds_part, parts, ":");
    hours = 0;
    minutes = 0;
    seconds = 0;
    if (length(parts) == 3) {
        hours = parts[1];
        minutes = parts[2];
        seconds = parts[3];
    } else {
        minutes = parts[1];
        seconds = parts[2];
    }
    return hours * 3600 + minutes * 60 + seconds + (milliseconds / 1000);
}

{
    start_sec = time_to_seconds($1);
    end_sec = time_to_seconds($2);
    duration = end_sec - start_sec;

    # Handle cases where duration is negative or zero
    if (duration <= 0) {
        duration = 0.1; # Assign a small default duration
    }

    frame_filename = sprintf("frame_%04d.png", NR);
    printf "file '\''%s'\''\nduration %f\n", frame_filename, duration;

    # Add the ffmpeg command to the extraction script
    print "ffmpeg -y -ss " $1 " -i \"" video_file "\" -vframes 1 -q:v 2 \"" tmp_dir "/" frame_filename "\" &" >> extract_script;
}' > "$CONCAT_LIST_FILE"

# Add a "wait" command to the end of the script to run extractions in parallel
echo "wait" >> "$EXTRACT_FRAMES_SCRIPT"

# Execute the frame extraction script
bash "$EXTRACT_FRAMES_SCRIPT"

# --- Video Creation ---
echo
echo "Creating video slideshow..."
VIDEO_ONLY_FILE="$TMP_DIR/video_only.mp4"
ffmpeg -f concat -safe 0 -i "$CONCAT_LIST_FILE" -c:v libx264 -r 24 -pix_fmt yuv420p -y "$VIDEO_ONLY_FILE"

# --- Audio Merging ---
echo "Merging video with original audio..."
ffmpeg -i "$VIDEO_ONLY_FILE" -i "$VIDEO_FILE" -c copy -map 0:v:0 -map 1:a:0 -shortest -y "$OUTPUT_FILE"

echo
echo "Slideshow created successfully: $OUTPUT_FILE"
