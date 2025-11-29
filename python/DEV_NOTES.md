# Development Notes: Video Slideshow Generator

This document summarizes the development history, implemented features, encountered bugs, and attempted fixes for the `video_slideshow_generator.py` script.

## Implemented Features

1.  **Subtitle Track Selection**:
    *   Added `--subtitle_track` argument to select specific subtitle tracks by index.
    *   Implemented filtering logic to only process selected tracks.
    *   Added `--list-subtitles` argument to list available tracks and their indices.

2.  **Subtitle Preservation**:
    *   Implemented logic to preserve original subtitles in the output file.
    *   Ensures that if the input has subtitles, they are mapped to the output.
    *   Attempts to handle codec compatibility (e.g., originally tried `mov_text` for MP4, `srt` for MKV, but settled on unconditional `copy` based on user request).

3.  **Slideshow Generation**:
    *   The core logic generates a static video frame for each subtitle line.
    *   Supports transitions (fade) or simple concatenation.

## Known Bugs & Issues

### 1. Audio/Video Disconnect on Scrubbing
*   **Symptom**: When scrubbing (seeking) forward in the generated video, the audio continues playing, but the video stops or desynchronizes.
*   **Status**: Partially addressed, but scrubbing issues persist.

### 2. Frozen Video on Scrubbing
*   **Symptom**: When scrubbing, the audio plays fine, but the video remains frozen at the frame where the scrub started.
*   **Status**: **Unresolved**.

### 3. Missing Subtitles (Solved)
*   **Symptom**: Output video initially lacked subtitles.
*   **Status**: Solved by explicitly mapping subtitles from the input file in the final merge step.

## Attempted Fixes & Outcomes

### Fix 1: Re-encoding Video in Final Merge
*   **Approach**: Changed the final merge step to re-encode the video (`-c:v libx264`) instead of copying (`-c:v copy`).
*   **Theory**: Re-encoding would ensure consistent timestamps and a compliant container structure.
*   **Outcome**: Did not solve the scrubbing issue. User requested to simplify and remove conditionals.

### Fix 2: Intermediate Audio Integration
*   **Approach**: Modified the *intermediate* slideshow generation step (where `video_only_X.mp4` is created) to include the audio stream from the original input file (`-map 1:a? -c:a copy`).
*   **Theory**: Muxing audio with the video *during generation* (before final merge) would ensure tighter synchronization.
*   **Outcome**: Solved the "no audio" issue, but led to the "frozen video" issue.

### Fix 3: Unconditional Stream Copy ("Final Muxing")
*   **Approach**: Adopted a specific "Final Muxing" strategy from a previous branch (`refactor-video-slideshow-ffmpeg`).
*   **Details**:
    *   Merged intermediate files using `-c copy` for all streams (video, audio, subtitles).
    *   Removed conditional logic for codecs (e.g., checking for MP4 vs MKV).
    *   Used `shutil.move` optimization for single-track outputs (disabled later to ensure subtitle preservation).
*   **Outcome**: Simplified the code, but the frozen video issue persisted.

### Fix 4: Enforcing GOP Size (Keyframes)
*   **Approach**: Added `-g 24` (GOP size of 1 second) to the intermediate video encoding command.
*   **Theory**: The "frozen video" on scrub is often caused by sparse keyframes (e.g., if a slide is 20 seconds long, there might be no I-frame for 20 seconds). Forcing frequent keyframes allows the player to seek to any second and resume decoding.
*   **Outcome**: **Failed**. The user reported the issue persists.

## Future Recommendations

*   **Investigate Container/Muxing**: The issue might be related to how `ffmpeg` concatenates static image videos.
*   **Timebase Issues**: Static images often have weird timebases. Explicitly setting `-r 24` and `tbn` might help.
*   **Re-evaluating "Copy"**: While `-c copy` is fast, if the input streams (intermediate files) have issues (like sparse keyframes or bad timestamps), copying preserves the garbage. A forced re-encode of the *final* output might be necessary despite the performance cost, potentially with specific `-tune stillimage` or similar settings.
*   **Player Specifics**: The issue might be specific to VLC or the player being used. Testing with `mpv` or other players could isolate the cause.
