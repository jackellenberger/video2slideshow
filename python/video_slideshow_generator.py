import argparse
import ffmpeg
import webvtt
import os
import tempfile
import shutil
import subprocess

def main():
    parser = argparse.ArgumentParser(description='Create a video slideshow from a video and its corresponding subtitle file.')
    parser.add_argument('input_file', help='Path to the input video file.')
    parser.add_argument('-s', '--subtitle_file', help='Path to the external subtitle file.')
    parser.add_argument('-o', '--output_file', default='slideshow.mp4', help='Path to the output video file.')
    parser.add_argument('--min_frame_length', type=float, default=0.1, help='Minimum duration for a frame.')
    parser.add_argument('--max_frame_length', type=float, default=10.0, help='Maximum duration for a frame.')
    parser.add_argument('--dialogue_offset', type=float, default=0.0, help='Offset for frame extraction time relative to subtitle activation.')
    parser.add_argument('--fade_duration', type=float, default=0.0, help='Duration of the fade-in and fade-out effect in seconds.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable ffmpeg output.')
    parser.add_argument('--hwaccel', choices=['nvenc', 'none'], default='none', help='Hardware acceleration method.')
    parser.add_argument('--keep-original-video', action='store_true', help='Keep the original video stream in the output MKV.')
    parser.add_argument('--preview', type=float, help='Only process the first N seconds of the video.')

    args = parser.parse_args()

    # Create a temporary directory to store the extracted frames
    tmp_dir = tempfile.mkdtemp()
    print(f"Temporary directory: {tmp_dir}")

    try:
        print("Probing video file...")
        # Get video duration
        probe = ffmpeg.probe(args.input_file)
        video_duration = float(probe['format']['duration'])
        if args.preview and args.preview < video_duration:
            video_duration = args.preview

        subtitle_files = []
        subtitle_streams = []
        if args.subtitle_file:
            subtitle_files.append(args.subtitle_file)
            subtitle_streams.append({'tags': {'title': os.path.basename(args.subtitle_file)}})
        else:
            # Find and extract subtitle streams
            subtitle_streams = [s for s in probe['streams'] if s['codec_type'] == 'subtitle']
            if not subtitle_streams:
                print("Error: No subtitle streams found in the input file and no external subtitle file provided.")
                return

            print(f"Found {len(subtitle_streams)} subtitle streams.")

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
                if args.preview:
                    captions = [c for c in captions if c.start_in_seconds < args.preview]
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

            video_only_file = os.path.join(tmp_dir, f'video_only_{subtitle_index}.mp4')

            # Get frame rate
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            if not video_stream:
                print(f"No video stream found in {args.input_file}")
                continue
            frame_rate_str = video_stream.get('r_frame_rate', '25/1')
            num, den = map(int, frame_rate_str.split('/'))
            frame_rate = num / den

            clips = []
            for i, frame in enumerate(frames_to_extract):
                clip_file = os.path.join(tmp_dir, f"clip_{subtitle_index}_{i:04d}.mp4")
                frame_number = int(frame['start_time'] * frame_rate)
                select_expr = f"select='eq(n,{frame_number})'"
                tpad_expr = f"tpad=stop_mode=clone:stop_duration={frame['duration']}"
                command = [
                    'ffmpeg',
                    '-i', args.input_file,
                    '-vf', f"{select_expr},{tpad_expr}",
                    '-an',
                    '-vframes', '1',
                    clip_file,
                    '-y'
                ]
                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])

                try:
                    subprocess.run(command, check=True)
                    clips.append(clip_file)
                except (ffmpeg.Error, subprocess.CalledProcessError) as e:
                    print(f"Error generating clip for subtitle track {subtitle_index}: {e.stderr.decode('utf-8') if hasattr(e, 'stderr') and e.stderr else e}")
                    continue

            # Concatenate the clips
            concat_list_file = os.path.join(tmp_dir, f'concat_list_{subtitle_index}.txt')
            with open(concat_list_file, 'w') as f:
                for clip in clips:
                    f.write(f"file '{clip}'\n")

            command = [
                'ffmpeg',
                '-f', 'concat',
                '-safe', '0',
                '-i', concat_list_file,
                '-c', 'copy',
                video_only_file,
                '-y'
            ]
            if not args.verbose:
                command.extend(['-loglevel', 'quiet'])

            try:
                subprocess.run(command, check=True)
                slideshow_files.append(video_only_file)
            except (ffmpeg.Error, subprocess.CalledProcessError) as e:
                print(f"Error generating slideshow for subtitle track {subtitle_index}: {e.stderr.decode('utf-8') if hasattr(e, 'stderr') and e.stderr else e}")
                continue

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
            if args.preview:
                command.extend(['-t', str(args.preview)])
            command.extend(['-map', f'{len(slideshow_files)}:a?']) # Optional audio

            video_stream_index = 0
            if args.keep_original_video:
                command.extend(['-metadata:s:v:0', 'title=Original Video'])
                video_stream_index += 1

            for i, stream in enumerate(subtitle_streams):
                lang = stream.get('tags', {}).get('language', 'und')
                title = stream.get('tags', {}).get('title', f'Slideshow from subtitle {i}')
                command.extend([f'-metadata:s:v:{video_stream_index}', f"language={lang}", f'-metadata:s:v:{video_stream_index}', f"title={title}"])
                video_stream_index += 1
            command.extend([
                '-c:v', 'copy',
                '-c:a', 'copy',
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


if __name__ == '__main__':
    main()
