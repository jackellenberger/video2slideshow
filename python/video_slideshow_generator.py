import argparse
import ffmpeg
import webvtt
import os
import tempfile
import shutil
from multiprocessing import Pool
import subprocess

def main():
    parser = argparse.ArgumentParser(description='Create a video slideshow from a video and its corresponding subtitle file.')
    parser.add_argument('input_file', help='Path to the input MKV file.')
    parser.add_argument('-o', '--output_file', default='slideshow.mp4', help='Path to the output video file.')
    parser.add_argument('--min_frame_length', type=float, default=0.1, help='Minimum duration for a frame.')
    parser.add_argument('--max_frame_length', type=float, default=10.0, help='Maximum duration for a frame.')
    parser.add_argument('--dialogue_offset', type=float, default=0.0, help='Offset for frame extraction time relative to subtitle activation.')
    parser.add_argument('--fade_duration', type=float, default=0.0, help='Duration of the fade-in and fade-out effect in seconds.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable ffmpeg output.')
    parser.add_argument('--hwaccel', choices=['nvenc', 'none'], default='none', help='Hardware acceleration method.')
    parser.add_argument('--keep-original-video', action='store_true', help='Keep the original video stream in the output MKV.')

    args = parser.parse_args()

    if not args.input_file.lower().endswith('.mkv'):
        print("Error: Input file must be an MKV file.")
        return

    # Create a temporary directory to store the extracted frames
    tmp_dir = tempfile.mkdtemp()
    print(f"Temporary directory: {tmp_dir}")

    try:
        print("Probing video file...")
        # Get video duration
        probe = ffmpeg.probe(args.input_file)
        video_duration = float(probe['format']['duration'])

        # Find and extract subtitle streams
        subtitle_streams = [s for s in probe['streams'] if s['codec_type'] == 'subtitle']
        if not subtitle_streams:
            print("Error: No subtitle streams found in the input file.")
            return

        print(f"Found {len(subtitle_streams)} subtitle streams.")

        subtitle_files = []
        for i, stream in enumerate(subtitle_streams):
            print(f"Extracting subtitle stream {i}...")
            subtitle_file = os.path.join(tmp_dir, f"subtitle_{i}.vtt")
            try:
                command = ['ffmpeg', '-i', args.input_file, '-map', f'0:s:{i}', subtitle_file, '-y']
                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])
                subprocess.run(command, check=True)
                subtitle_files.append(subtitle_file)
            except (ffmpeg.Error, subprocess.CalledProcessError) as e:
                print(f"Error extracting subtitle stream {i}: {e.stderr.decode('utf-8') if hasattr(e, 'stderr') and e.stderr else e}")
                continue

        if not subtitle_files:
            print("Error: Failed to extract any subtitle streams.")
            return

        slideshow_files = []
        for subtitle_index, subtitle_file in enumerate(subtitle_files):
            print(f"Generating slideshow for subtitle track {subtitle_index}...")
            # Parse the subtitle file
            try:
                captions = webvtt.read(subtitle_file)
            except Exception as e:
                print(f"Error parsing subtitle file {subtitle_file}: {e}")
                continue
            # Create a list of timestamps
            timestamps = [0]  # Always start from the beginning
            timestamps.extend([caption.start_in_seconds for caption in captions])
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
            frame_paths = pool.starmap(extract_frame, [(args.input_file, frame['start_time'], os.path.join(tmp_dir, f"frame_{subtitle_index}_{i:04d}.png"), args.verbose) for i, frame in enumerate(frames_to_extract)])
            pool.close()
            pool.join()

            # Create a concat list file
            concat_list_file = os.path.join(tmp_dir, f'concat_list_{subtitle_index}.txt')
            with open(concat_list_file, 'w') as f:
                for i, frame in enumerate(frames_to_extract):
                    f.write(f"file 'frame_{subtitle_index}_{i:04d}.png'\n")
                    f.write(f"duration {frame['duration']}\n")

            # Create the video slideshow
            video_only_file = os.path.join(tmp_dir, f'video_only_{subtitle_index}.mp4')
            if args.fade_duration > 0 and len(frame_paths) > 1:
                # Use xfade filter for transitions
                fade_duration = args.fade_duration

                # Create a list of video parts
                video_parts = []
                for i, frame_path in enumerate(frame_paths):
                    video_parts.append(ffmpeg.input(frame_path).video)

                # Chain the xfade filters
                processed_video = video_parts[0]
                for i in range(1, len(video_parts)):
                    processed_video = ffmpeg.filter([processed_video, video_parts[i]], 'xfade', transition='fade', duration=fade_duration, offset=sum(f['duration'] for f in frames_to_extract[:i]) - fade_duration)

                command = [
                    'ffmpeg',
                    '-hwaccel', 'auto',
                    '-i', processed_video,
                ]
                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
                else:
                    command.extend(['-c:v', 'libx264'])
                command.extend([
                    '-r', '24',
                    '-pix_fmt', 'yuv420p',
                    video_only_file,
                    '-y'
                ])
                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])
                subprocess.run(command, check=True)
            else:
                # Use concat for no transitions
                command = [
                    'ffmpeg',
                    '-hwaccel', 'auto',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_list_file,
                ]
                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
                else:
                    command.extend(['-c:v', 'libx264'])
                command.extend([
                    '-r', '24',
                    '-pix_fmt', 'yuv420p',
                    video_only_file,
                    '-y'
                ])
                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])
                subprocess.run(command, check=True)
            slideshow_files.append(video_only_file)

        # Merge slideshows and audio into a single MKV file
        if slideshow_files:
            print("Merging slideshows into a single MKV file...")
            command = [
                'ffmpeg'
            ]
            for f in slideshow_files:
                command.extend(['-i', f])
            command.extend(['-i', args.input_file])

            video_maps = 0
            if args.keep_original_video:
                command.extend(['-map', f'{len(slideshow_files)}:v'])
                video_maps += 1

            for i in range(len(slideshow_files)):
                command.extend(['-map', f'{i}:v'])
                video_maps += 1
            command.extend(['-map', f'{len(slideshow_files)}:a?']) # Optional audio
            command.extend(['-map', f'{len(slideshow_files)}:s?']) # Optional subtitles

            for i, stream in enumerate(subtitle_streams):
                lang = stream.get('tags', {}).get('language', 'und')
                command.extend([f'-metadata:s:v:{i+video_maps-1}', f"language={lang}"])
            command.extend([
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-c:s', 'copy',
                args.output_file,
                '-y'
            ])
            if not args.verbose:
                command.extend(['-loglevel', 'quiet'])
            subprocess.run(command, check=True)

        print(f"Slideshow created successfully: {args.output_file}")

    finally:
        # Clean up the temporary directory
        shutil.rmtree(tmp_dir)


def extract_frame(input_file, start_time, output_file, verbose):
    command = [
        'ffmpeg',
        '-hwaccel', 'auto',
        '-ss', str(start_time),
        '-i', input_file,
        '-vframes', '1',
        '-q', '2',
        output_file,
        '-y'
    ]
    if not verbose:
        command.extend(['-loglevel', 'quiet'])
    subprocess.run(command, check=True)
    return output_file


if __name__ == '__main__':
    main()
