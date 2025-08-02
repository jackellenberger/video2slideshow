import argparse
import ffmpeg
import webvtt
import os
import tempfile
import shutil
import subprocess
import math
import multiprocessing
from functools import partial

def run_ffmpeg_command(command, verbose):
    """Helper function to run a single ffmpeg command for multiprocessing."""
    if not verbose:
        # Hide ffmpeg's output unless verbose is on
        command.extend(['-loglevel', 'error'])
    try:
        # Using capture_output to prevent interleaved printing from parallel processes
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # Print errors if a command fails
        print(f"FFmpeg failed for command: {' '.join(command)}")
        print(f"FFmpeg stderr:\n{e.stderr.decode('utf-8')}")


def main():
    # --- Argument Parsing ---
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
    parser.add_argument('--image-format', choices=['jpg', 'png'], default='jpg', help='Intermediate image format. JPG is much smaller, PNG is lossless.')
    # --- NEW: Added argument to control extraction method ---
    parser.add_argument('--extraction-method', choices=['fast', 'accurate'], default='fast', help='Frame extraction method. "fast" is quicker but less frame-precise. "accurate" is slow but exact.')


    args = parser.parse_args()

    if args.fade_duration > 0:
        print("Note: Fade transitions are complex with this approach and are currently disabled.")

    # Create a temporary directory
    tmp_dir = tempfile.mkdtemp()
    print(f"Temporary directory: {tmp_dir}")

    try:
        # --- Probing and Subtitle Extraction ---
        print("Probing video file...")
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
            subtitle_streams = [s for s in probe['streams'] if s['codec_type'] == 'subtitle']
            if not subtitle_streams:
                print("Error: No subtitle streams found in the input file.")
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
                    print(f"Error extracting subtitle stream {i}: {e}")
                    continue

            if not subtitle_files:
                print("Error: Failed to extract any subtitle streams.")
                return

        slideshow_files = []
        for subtitle_index, subtitle_file in enumerate(subtitle_files):
            print(f"Generating slideshow for subtitle track {subtitle_index}...")
            
            try:
                captions = webvtt.read(subtitle_file)
                if args.preview:
                    captions = [c for c in captions if c.start_in_seconds < args.preview]
            except Exception as e:
                print(f"Error parsing subtitle file {subtitle_file}: {e}")
                continue
            
            timestamps = [0]
            timestamps.extend([caption.start_in_seconds for caption in captions])
            timestamps.append(video_duration)

            # --- Create a list of frames to extract ---
            frames_to_extract = []
            for i in range(len(timestamps) - 1):
                start_time = timestamps[i] + args.dialogue_offset
                start_time = max(0, start_time) # Ensure non-negative

                duration = timestamps[i+1] - timestamps[i]

                if duration < args.min_frame_length:
                    duration = args.min_frame_length

                current_time = start_time
                while duration > args.max_frame_length:
                    frames_to_extract.append({'start_time': current_time, 'duration': args.max_frame_length})
                    current_time += args.max_frame_length
                    duration -= args.max_frame_length

                if duration > 0:
                   frames_to_extract.append({'start_time': current_time, 'duration': duration})

            video_only_file = os.path.join(tmp_dir, f'video_only_{subtitle_index}.mp4')

            if not frames_to_extract:
                print("No frames to extract for this subtitle track.")
                continue

            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            if video_stream is None:
                print("Error: No video stream found in the input file.")
                continue

            avg_frame_rate = video_stream.get('avg_frame_rate', '24/1')
            if avg_frame_rate == '0/0':
                avg_frame_rate = '24/1'
            num, den = avg_frame_rate.split('/')
            framerate = float(num) / float(den) if float(den) > 0 else 24

            # --- REVISED IMPLEMENTATION START (Method Selection) ---

            # 1. Identify unique frames needed by their timestamps
            unique_timestamps = sorted(list(set([round(f['start_time'], 3) for f in frames_to_extract])))
            if not unique_timestamps:
                print("No unique timestamps to extract for this track.")
                continue

            image_format = args.image_format
            image_quality_param = '2' if image_format == 'jpg' else '1'
            extracted_frame_map = {}

            if args.extraction_method == 'fast':
                # --- FAST (PARALLEL) METHOD ---
                print(f"Using fast extraction method for {len(unique_timestamps)} unique frames.")
                commands_to_run = []
                for i, ts in enumerate(unique_timestamps):
                    image_filename = f"frame_{subtitle_index}_{i+1:05d}.{image_format}"
                    image_path = os.path.join(tmp_dir, image_filename)
                    extracted_frame_map[ts] = image_filename
                    
                    # Command uses input seeking (-ss before -i) for speed
                    command = ['ffmpeg', '-ss', str(ts), '-i', args.input_file, '-vframes', '1', '-q:v', image_quality_param, image_path, '-y']
                    commands_to_run.append(command)

                cpu_count = multiprocessing.cpu_count()
                print(f"Extracting frames in parallel using up to {cpu_count} cores...")
                
                # Use a partial function to pass the 'verbose' argument to the worker
                worker_func = partial(run_ffmpeg_command, verbose=args.verbose)
                
                with multiprocessing.Pool(processes=cpu_count) as pool:
                    pool.map(worker_func, commands_to_run)
                print("Frame extraction complete.")

            else:
                # --- ACCURATE (SELECT FILTER) METHOD ---
                print(f"Using accurate extraction method for {len(unique_timestamps)} unique frames (this may be slow).")
                frame_numbers = [int(round(ts * framerate)) for ts in unique_timestamps]

                select_filter_str = "select='" + "+".join([f"eq(n,{fn})" for fn in frame_numbers]) + "',setpts=N/FR/TB"
                filter_script_path = os.path.join(tmp_dir, f"select_script_{subtitle_index}.txt")
                with open(filter_script_path, 'w') as f:
                    f.write(select_filter_str)

                image_pattern = os.path.join(tmp_dir, f"frame_{subtitle_index}_%05d.{image_format}")

                command = [
                    'ffmpeg', '-i', args.input_file,
                    '-filter_script', filter_script_path,
                    '-vsync', 'vfr', '-q:v', image_quality_param,
                    image_pattern, '-y'
                ]
                if not args.verbose:
                    command.extend(['-loglevel', 'quiet'])
                subprocess.run(command, check=True)

                for i, ts in enumerate(unique_timestamps):
                    image_filename = f"frame_{subtitle_index}_{i+1:05d}.{image_format}"
                    extracted_frame_map[ts] = image_filename

            # --- Generate the OUTPUT concat file (for assembling the slideshow) ---
            print("Generating slideshow instructions...")
            output_concat_path = os.path.join(tmp_dir, f"output_slideshow_{subtitle_index}.txt")
            with open(output_concat_path, 'w') as concat_file:
                concat_file.write("ffconcat version 1.0\n")
                last_image_path = None
                
                for frame in frames_to_extract:
                    timestamp = round(frame['start_time'], 3)
                    image_filename = extracted_frame_map.get(timestamp)

                    if image_filename:
                        image_path = os.path.join(tmp_dir, image_filename)
                        abs_image_path = os.path.abspath(image_path)

                        if not os.path.exists(abs_image_path):
                            print(f"Warning: Missing expected frame {abs_image_path} for timestamp {timestamp}. Skipping.")
                            continue

                        escaped_image_path = abs_image_path.replace("'", r"\'")

                        concat_file.write(f"file '{escaped_image_path}'\n")
                        concat_file.write(f"duration {frame['duration']:.6f}\n")
                        last_image_path = escaped_image_path

                if last_image_path:
                    concat_file.write(f"file '{last_image_path}'\n")

            # --- Combine images into the final video ---
            print("Rendering slideshow video...")
            command = ['ffmpeg', '-f', 'concat', '-safe', '0', '-i', output_concat_path]
            
            if args.hwaccel == 'nvenc':
                command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
            else:
                command.extend(['-c:v', 'libx264'])

            command.extend(['-r', '24', '-pix_fmt', 'yuv420p', video_only_file, '-y'])

            if not args.verbose:
                command.extend(['-loglevel', 'quiet'])

            subprocess.run(command, check=True)
            slideshow_files.append(video_only_file)

        # --- Merge slideshows and audio ---
        if slideshow_files:
            print("Merging slideshows, audio, and subtitles into a single MKV file...")
            command = ['ffmpeg']

            valid_slideshows = [f for f in slideshow_files if f]
            if not valid_slideshows:
                print("No valid slideshows were generated.")
                return

            for f in valid_slideshows:
                command.extend(['-i', f])
            command.extend(['-i', args.input_file])

            # Map video streams
            video_maps = 0
            if args.keep_original_video:
                command.extend(['-map', f'{len(valid_slideshows)}:v'])
                video_maps += 1

            for i in range(len(valid_slideshows)):
                command.extend(['-map', f'{i}:v'])
                video_maps += 1
            
            if args.preview:
                command.extend(['-t', str(args.preview)])

            # Map audio and subtitle streams
            command.extend(['-map', f'{len(valid_slideshows)}:a?'])
            command.extend(['-map', f'{len(valid_slideshows)}:s?'])

            # Set metadata for video streams
            video_stream_index = 0
            if args.keep_original_video:
                command.extend(['-metadata:s:v:0', 'title=Original Video'])
                video_stream_index += 1
            
            valid_stream_metadata = []
            for i in range(len(subtitle_streams)):
                if os.path.join(tmp_dir, f'video_only_{i}.mp4') in valid_slideshows:
                    valid_stream_metadata.append(subtitle_streams[i])

            for i, stream in enumerate(valid_stream_metadata):
                lang = stream.get('tags', {}).get('language', 'und')
                title = stream.get('tags', {}).get('title', f'Slideshow from subtitle {i}')
                command.extend([f'-metadata:s:v:{video_stream_index}', f"language={lang}", f'-metadata:s:v:{video_stream_index}', f"title={title}"])
                video_stream_index += 1
            
            # Final output command
            command.extend(['-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy', args.output_file, '-y'])
            if not args.verbose:
                command.extend(['-loglevel', 'quiet'])
            subprocess.run(command, check=True)

            print(f"Slideshow created successfully: {args.output_file}")

    except subprocess.CalledProcessError as e:
        print(f"\nAn FFmpeg error occurred (Exit Status {e.returncode}).")
        if not args.verbose:
            print("Rerun with -v (verbose) to see FFmpeg's detailed error output.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        # Clean up the temporary directory
        print(f"Cleaning up temporary directory: {tmp_dir}")
        shutil.rmtree(tmp_dir)

if __name__ == '__main__':
    main()
