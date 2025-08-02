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

            if not frames_to_extract:
                print(f"No frames to extract for subtitle track {subtitle_index}.")
                continue

            concat_list_file = os.path.join(tmp_dir, f'concat_list_{subtitle_index}.txt')
            with open(concat_list_file, 'w') as f:
                for frame in frames_to_extract:
                    f.write(f"file '{args.input_file}'\n")
                    f.write(f"inpoint {frame['start_time']}\n")
                    f.write(f"outpoint {frame['start_time'] + 0.001}\n")
                    f.write(f"duration {frame['duration']}\n")

            # The 'loop' and 'setpts' approach for holding frames
            probe = ffmpeg.probe(args.input_file)
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            if video_stream is None:
                print(f"Could not find video stream in {args.input_file}")
                continue

            avg_frame_rate = video_stream.get('avg_frame_rate', '24/1')
            if avg_frame_rate == '0/0':
                avg_frame_rate = '24/1'
            num, den = avg_frame_rate.split('/')
            framerate = float(num) / float(den) if float(den) > 0 else 24

            filter_parts = []
            for i, frame in enumerate(frames_to_extract):
                frame_num = int(frame['start_time'] * framerate)
                duration_in_frames = int(frame['duration'] * 24)
                if duration_in_frames == 0:
                    duration_in_frames = 1
                filter_parts.append(f"[0:v]trim=start_frame={frame_num}:end_frame={frame_num + 1},loop=loop={duration_in_frames - 1}:size=1:start=0,setpts=N/24/TB[v{i}]")

            if filter_parts:
                concat_inputs = "".join([f"[v{i}]" for i in range(len(frames_to_extract))])
                concat_filter = f"{concat_inputs}concat=n={len(frames_to_extract)}:v=1:a=0"
                filter_complex = ";".join(filter_parts) + ";" + concat_filter

                command = [
                    'ffmpeg',
                    '-i', args.input_file,
                    '-filter_complex', filter_complex,
                ]

                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
                else:
                    command.extend(['-c:v', 'libx264'])

                command.extend(['-r', '24', '-pix_fmt', 'yuv420p', video_only_file, '-y'])

                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])

                subprocess.run(command, check=True)
                slideshow_files.append(video_only_file)
            else:
                print(f"No frames to extract for subtitle track {subtitle_index}.")

        # Merge slideshows and audio into a single MKV file
        if slideshow_files:
            print("Merging slideshows into a single MKV file...")
            command = ['ffmpeg']

            valid_slideshows = [f for f in slideshow_files if f]
            if not valid_slideshows:
                print("No valid slideshows were generated.")
                return

            for f in valid_slideshows:
                command.extend(['-i', f])
            command.extend(['-i', args.input_file])

            video_maps = 0
            if args.keep_original_video:
                command.extend(['-map', f'{len(valid_slideshows)}:v'])
                video_maps += 1

            for i in range(len(valid_slideshows)):
                command.extend(['-map', f'{i}:v'])
                video_maps += 1
            if args.preview:
                command.extend(['-t', str(args.preview)])
            command.extend(['-map', f'{len(valid_slideshows)}:a?']) # Optional audio
            command.extend(['-map', f'{len(valid_slideshows)}:s?']) # Optional subtitles

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

if __name__ == '__main__':
    main()
