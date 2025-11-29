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
    parser.add_argument('--subtitle_track', type=int, action='append', help='Select specific subtitle tracks to generate slideshows for (0-based index). Can be used multiple times.')
    parser.add_argument('--list-subtitles', action='store_true', help='List available subtitle tracks and exit.')

    args = parser.parse_args()

    # Create a temporary directory to store the extracted frames
    if args.list_subtitles:
        try:
             probe = ffmpeg.probe(args.input_file)
             subtitle_streams = [s for s in probe['streams'] if s['codec_type'] == 'subtitle']
             if not subtitle_streams:
                 print("No subtitle streams found.")
             else:
                 print("Available subtitle tracks:")
                 for i, stream in enumerate(subtitle_streams):
                     tags = stream.get('tags', {})
                     lang = tags.get('language', 'unknown')
                     title = tags.get('title', 'N/A')
                     print(f"Index {i}: Language: {lang}, Title: {title}")
        except ffmpeg.Error as e:
            print(f"Error probing file: {e.stderr.decode('utf-8') if hasattr(e, 'stderr') and e.stderr else e}")
        return

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
        used_subtitle_streams = []
        if args.subtitle_file:
            subtitle_files.append(args.subtitle_file)
            subtitle_streams.append({'tags': {'title': os.path.basename(args.subtitle_file)}})
            used_subtitle_streams.append({'stream': subtitle_streams[0], 'index': 0})
        else:
            # Find and extract subtitle streams
            subtitle_streams = [s for s in probe['streams'] if s['codec_type'] == 'subtitle']
            if not subtitle_streams:
                print("Error: No subtitle streams found in the input file and no external subtitle file provided.")
                return

            print(f"Found {len(subtitle_streams)} subtitle streams.")

            for i, stream in enumerate(subtitle_streams):
                if args.subtitle_track and i not in args.subtitle_track:
                    continue

                print(f"Extracting subtitle stream {i}...")
                subtitle_file = os.path.join(tmp_dir, f"subtitle_{i}.vtt")
                try:
                    command = ['ffmpeg', '-i', args.input_file, '-map', f'0:s:{i}', subtitle_file, '-y']
                    if not args.verbose:
                        command.extend(['-loglevel', 'quiet'])
                    subprocess.run(command, check=True)
                    subtitle_files.append(subtitle_file)
                    used_subtitle_streams.append({'stream': stream, 'index': i})
                except (ffmpeg.Error, subprocess.CalledProcessError) as e:
                    print(f"Error extracting subtitle stream {i}: {e.stderr.decode('utf-8') if hasattr(e, 'stderr') and e.stderr else e}")
                    continue

            if not subtitle_files:
                print("Error: Failed to extract any subtitle streams.")
                return

        slideshow_files = []
        for loop_index, subtitle_file in enumerate(subtitle_files):
            original_index = used_subtitle_streams[loop_index]['index']
            print(f"Generating slideshow for subtitle track {original_index}...")
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

            # Extract frames in parallel
            pool = Pool()
            frame_paths = pool.starmap(extract_frame, [(args.input_file, frame['start_time'], os.path.join(tmp_dir, f"frame_{original_index}_{i:04d}.png"), args.verbose) for i, frame in enumerate(frames_to_extract)])
            pool.close()
            pool.join()

            # Create a concat list file
            concat_list_file = os.path.join(tmp_dir, f'concat_list_{original_index}.txt')
            with open(concat_list_file, 'w') as f:
                for i, frame in enumerate(frames_to_extract):
                    f.write(f"file 'frame_{original_index}_{i:04d}.png'\n")
                    f.write(f"duration {frame['duration']}\n")

            # Create the video slideshow
            video_only_file = os.path.join(tmp_dir, f'video_only_{original_index}.mp4')
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

                # Audio input
                audio_input = ffmpeg.input(args.input_file).audio

                command = [
                    'ffmpeg',
                    '-hwaccel', 'auto',
                    '-i', processed_video,
                    '-i', args.input_file, # Add original file for audio
                    '-map', '0:v',
                    '-map', '1:a?',
                    '-c:a', 'copy'
                ]
                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-g', '24'])
                else:
                    command.extend(['-c:v', 'libx264', '-g', '24'])
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
                    '-i', args.input_file, # Add original file for audio
                    '-map', '0:v',
                    '-map', '1:a?',
                    '-c:a', 'copy'
                ]
                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-g', '24'])
                else:
                    command.extend(['-c:v', 'libx264', '-g', '24'])
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
            # Check if we can just move the file (only if 1 slideshow, no original video, and no subtitles to carry over)
            # However, we typically want to carry over subtitles from the original file.
            # So we only use the optimization if there are NO subtitle streams in the original file.
            can_optimize = len(slideshow_files) == 1 and not args.keep_original_video and not subtitle_streams

            if can_optimize:
                print(f"Finalizing output file...")
                shutil.move(slideshow_files[0], args.output_file)
            else:
                print("Muxing final slideshows and streams into a single MKV file...")
                command = ['ffmpeg']

                for f in slideshow_files:
                    command.extend(['-i', f])

                # Always add original file as input to get subtitles
                command.extend(['-i', args.input_file])
                input_file_index = len(slideshow_files)

                for i in range(len(slideshow_files)):
                    command.extend(['-map', f'{i}:v', '-map', f'{i}:a?'])

                if args.keep_original_video:
                    command.extend(['-map', f'{input_file_index}:v'])

                # Map subtitles from the original file
                command.extend(['-map', f'{input_file_index}:s?'])

                video_stream_index = 0
                for item in used_subtitle_streams:
                    stream = item['stream']
                    original_index = item['index']
                    lang = stream.get('tags', {}).get('language', 'und')
                    title = stream.get('tags', {}).get('title', f'Slideshow from subtitle {original_index}')
                    command.extend([f'-metadata:s:v:{video_stream_index}', f"language={lang}", f'-metadata:s:v:{video_stream_index}', f"title={title}"])
                    video_stream_index += 1

                if args.keep_original_video:
                    command.extend([f'-metadata:s:v:{video_stream_index}', 'title=Original Video'])

                # Re-encode video and audio to ensure robust keyframe structure and timestamps,
                # fixing scrubbing (frozen video) and sync issues.
                if args.hwaccel == 'nvenc':
                    command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-g', '30'])
                else:
                    command.extend(['-c:v', 'libx264', '-g', '30'])

                command.extend(['-c:a', 'aac'])

                # Handle subtitles: convert to srt/mov_text to ensure timestamps are rewritten correctly
                if args.output_file.lower().endswith('.mp4'):
                     command.extend(['-c:s', 'mov_text'])
                elif args.output_file.lower().endswith('.mkv'):
                     command.extend(['-c:s', 'srt'])
                else:
                     command.extend(['-c:s', 'copy'])

                command.extend([args.output_file, '-y'])

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
