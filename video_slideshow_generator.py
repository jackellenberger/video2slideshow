import argparse
import ffmpeg
import webvtt
import os
import tempfile
import shutil
from multiprocessing import Pool

def main():
    parser = argparse.ArgumentParser(description='Create a video slideshow from a video and its corresponding subtitle file.')
    parser.add_argument('video_file', help='Path to the input video file.')
    parser.add_argument('subtitle_file', help='Path to the input subtitle file (VTT format).')
    parser.add_argument('-o', '--output_file', default='slideshow.mp4', help='Path to the output video file.')
    parser.add_argument('--min_frame_length', type=float, default=0.1, help='Minimum duration for a frame.')
    parser.add_argument('--max_frame_length', type=float, default=10.0, help='Maximum duration for a frame.')
    parser.add_argument('--dialogue_offset', type=float, default=0.0, help='Offset for frame extraction time relative to subtitle activation.')

    args = parser.parse_args()

    # Create a temporary directory to store the extracted frames
    tmp_dir = tempfile.mkdtemp()
    print(f"Temporary directory: {tmp_dir}")

    try:
        # Parse the subtitle file
        captions = webvtt.read(args.subtitle_file)

        # Get video duration
        probe = ffmpeg.probe(args.video_file)
        video_duration = float(probe['format']['duration'])

        # Create a list of timestamps
        timestamps = [caption.start_in_seconds for caption in captions]
        timestamps.append(video_duration)

        # Create a list of frames to extract
        frames_to_extract = []
        for i in range(len(timestamps) - 1):
            start_time = timestamps[i] + args.dialogue_offset
            end_time = timestamps[i+1] + args.dialogue_offset
            duration = end_time - start_time

            # Apply min and max frame length
            if duration < args.min_frame_length:
                duration = args.min_frame_length

            # Split long frames
            while duration > args.max_frame_length:
                frames_to_extract.append({'start_time': start_time, 'duration': args.max_frame_length})
                start_time += args.max_frame_length
                duration -= args.max_frame_length

            frames_to_extract.append({'start_time': start_time, 'duration': duration})

        # Extract frames in parallel
        pool = Pool()
        frame_paths = pool.starmap(extract_frame, [(args.video_file, frame['start_time'], os.path.join(tmp_dir, f"frame_{i:04d}.png")) for i, frame in enumerate(frames_to_extract)])
        pool.close()
        pool.join()

        # Create a concat list file
        concat_list_file = os.path.join(tmp_dir, 'concat_list.txt')
        with open(concat_list_file, 'w') as f:
            for i, frame in enumerate(frames_to_extract):
                f.write(f"file 'frame_{i:04d}.png'\n")
                f.write(f"duration {frame['duration']}\n")

        # Create the video slideshow
        video_only_file = os.path.join(tmp_dir, 'video_only.mp4')
        (
            ffmpeg
            .input(concat_list_file, format='concat', safe=0)
            .output(video_only_file, c='libx264', r=24, pix_fmt='yuv420p')
            .run()
        )

        # Merge video with original audio
        input_video = ffmpeg.input(video_only_file)
        input_audio = ffmpeg.input(args.video_file)
        (
            ffmpeg
            .output(input_video.video, input_audio.audio, args.output_file, c='copy', shortest=None)
            .run(overwrite_output=True)
        )

        print(f"Slideshow created successfully: {args.output_file}")

    finally:
        # Clean up the temporary directory
        shutil.rmtree(tmp_dir)


def extract_frame(video_file, start_time, output_file):
    (
        ffmpeg
        .input(video_file, ss=start_time)
        .output(output_file, vframes=1, q='2')
        .run()
    )
    return output_file


if __name__ == '__main__':
    main()
