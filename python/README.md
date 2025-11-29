# Video Slideshow Generator

This Python script generates a video slideshow from a video file and its subtitles. It extracts frames based on subtitle timestamps and creates a new video where each subtitle line corresponds to a static frame from the video.

## Features

- **Automatic Slideshow Generation**: Creates a slideshow synced to subtitles.
- **Subtitle Track Selection**: Choose specific subtitle tracks from the input file.
- **Transition Effects**: Optional cross-fade transitions between frames.
- **Subtitle Preservation**: Preserves original subtitles in the output video (supports MKV and MP4).
- **Hardware Acceleration**: Supports NVENC for faster encoding.

## Prerequisites

- **Python 3.6+**
- **FFmpeg**: Must be installed and available in your system's PATH.
- **Python Packages**:
  ```bash
  pip install ffmpeg-python webvtt-py
  ```

## Usage

### Basic Usage

Generate a slideshow from the first available subtitle track:

```bash
python video_slideshow_generator.py input_video.mkv -o output_slideshow.mp4
```

### Finding Subtitle Tracks

To determine which subtitle tracks are available in your video file and their corresponding indices:

```bash
python video_slideshow_generator.py input_video.mkv --list-subtitles
```

Output example:
```
Available subtitle tracks:
Index 0: Language: eng, Title: English
Index 1: Language: spa, Title: Spanish
```

### Selecting Specific Subtitle Tracks

Use the `--subtitle_track` argument to select one or more tracks by their index (found using `--list-subtitles`).

To generate a slideshow for the track at index 1:

```bash
python video_slideshow_generator.py input_video.mkv --subtitle_track=1 -o output_track1.mp4
```

To generate slideshows for both index 0 and index 1:

```bash
python video_slideshow_generator.py input_video.mkv --subtitle_track=0 --subtitle_track=1 -o output_both.mkv
```

### Other Arguments

- `-s`, `--subtitle_file`: Path to an external subtitle file (overrides internal subtitles).
- `--min_frame_length`: Minimum duration for a frame (default: 0.1s).
- `--max_frame_length`: Maximum duration for a frame (default: 10.0s).
- `--dialogue_offset`: Offset for frame extraction time relative to subtitle start.
- `--fade_duration`: Duration of fade-in/out effect in seconds.
- `--hwaccel`: Hardware acceleration method (`nvenc` or `none`).
- `--keep-original-video`: Keep the original video stream in the output MKV.
- `--preview`: Only process the first N seconds of the video.
- `-v`, `--verbose`: Enable verbose output from FFmpeg.

## Output

The script generates a new video file containing the slideshow video track(s) and copies the original audio and subtitles.

- If the output file is `.mp4`, subtitles are converted to `mov_text`.
- If the output file is `.mkv`, subtitles are copied as-is (e.g., `webvtt`, `ass`).
