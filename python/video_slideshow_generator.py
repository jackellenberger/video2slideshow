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
from tqdm import tqdm

def run_ffmpeg_command(command, verbose):
    """
    Helper function to run a single ffmpeg command. This is used by the
    multiprocessing pool.
    """
    if not verbose:
        command.extend(['-loglevel', 'error'])

    stdout_dest = subprocess.DEVNULL if not verbose else None
    stderr_dest = subprocess.DEVNULL if not verbose else None
    
    try:
        subprocess.run(command, check=True, 
                       stdin=subprocess.DEVNULL, 
                       stdout=stdout_dest,
                       stderr=stderr_dest)
    except subprocess.CalledProcessError as e:
        if not verbose:
            print(f"\nFFmpeg worker failed for command: {' '.join(command)}")


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

    args = parser.parse_args()

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

            if not frames_to_extract:
                print("No frames to extract for this subtitle track.")
                continue

            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            if video_stream is None:
                print("Error: No video stream found in the input file.")
                continue
            
            audio_stream_exists = any(s['codec_type'] == 'audio' for s in probe['streams'])

            avg_frame_rate = video_stream.get('avg_frame_rate', '24/1')
            if avg_frame_rate == '0/0':
                avg_frame_rate = '24/1'
            num, den = avg_frame_rate.split('/')
            framerate = float(num) / float(den) if float(den) > 0 else 24

            # --- Frame Extraction (Timed Parallel Batch Method) ---
            unique_timestamps = sorted(list(set([round(f['start_time'], 3) for f in frames_to_extract])))
            if not unique_timestamps:
                print("No unique timestamps to extract for this track.")
                continue

            print(f"Preparing to extract {len(unique_timestamps)} unique frames...")
            image_format = args.image_format
            image_quality_param = '2' if image_format == 'jpg' else '1'
            extracted_frame_map = {}

            BATCH_SIZE = 50
            timestamp_batches = [unique_timestamps[i:i + BATCH_SIZE] for i in range(0, len(unique_timestamps), BATCH_SIZE)]
            
            commands_to_run = []
            for i, batch_timestamps in enumerate(timestamp_batches):
                start_time = batch_timestamps[0]
                # --- MODIFIED: Calculate a duration to prevent reading too far ---
                end_time = batch_timestamps[-1]
                duration = end_time - start_time + 1.0 # Add a 1-second buffer

                relative_frame_numbers = sorted(list(set([max(0, int(round((ts - start_time) * framerate))) for ts in batch_timestamps])))
                select_filter_str = "select='" + "+".join([f"eq(n,{fn})" for fn in relative_frame_numbers]) + "'"
                output_pattern = os.path.join(tmp_dir, f"batch_{i}_frame_%05d.{image_format}")
                
                # --- MODIFIED: Add -t duration flag to the command ---
                command = ['ffmpeg', '-nostdin', '-ss', str(start_time), '-t', str(duration), '-i', args.input_file,
                           '-vf', select_filter_str, '-vsync', 'vfr', '-q:v', image_quality_param,
                           output_pattern, '-y']
                commands_to_run.append(command)

            cpu_count = multiprocessing.cpu_count()
            pool_size = max(1, cpu_count // 2)
            worker_func = partial(run_ffmpeg_command, verbose=args.verbose)
            
            print(f"Extracting frames in {len(commands_to_run)} batches using a pool of {pool_size} workers...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                for _ in tqdm(pool.imap_unordered(worker_func, commands_to_run), total=len(commands_to_run), desc="Extracting Frames"):
                    pass
            print("Frame extraction complete.")

            # --- Map extracted images back to their timestamps ---
            for i, batch_timestamps in enumerate(timestamp_batches):
                start_time = batch_timestamps[0]
                relative_frame_numbers = sorted(list(set([max(0, int(round((ts - start_time) * framerate))) for ts in batch_timestamps])))
                
                for j, rel_fn in enumerate(relative_frame_numbers):
                    corresponding_timestamps = [ts for ts in batch_timestamps if max(0, int(round((ts - start_time) * framerate))) == rel_fn]
                    image_filename = f"batch_{i}_frame_{j+1:05d}.{image_format}"
                    image_path = os.path.join(tmp_dir, image_filename)
                    
                    if os.path.exists(image_path):
                        for ts in corresponding_timestamps:
                            extracted_frame_map[ts] = image_path
                    else:
                        print(f"Warning: Expected image {image_path} not found. It might have been skipped by ffmpeg.")

            # --- Video and Audio Assembly in a Single Step ---
            print("Rendering slideshow video with audio...")
            
            slideshow_with_audio_file = os.path.join(tmp_dir, f'slideshow_audio_{subtitle_index}.mkv')

            inputs = []
            filter_chains = []
            concat_streams = []
            
            image_sequence = []
            for frame in frames_to_extract:
                timestamp = round(frame['start_time'], 3)
                image_path = extracted_frame_map.get(timestamp)
                if image_path and os.path.exists(image_path):
                    image_sequence.append({'path': image_path, 'duration': frame['duration']})

            if not image_sequence:
                print("No images found to create slideshow. Skipping track.")
                continue

            inputs.extend(['-i', args.input_file])
            audio_input_index = 0

            for i, image_info in enumerate(image_sequence):
                inputs.extend(['-loop', '1', '-t', str(image_info['duration']), '-i', image_info['path']])
                stream_label = f"v{i}"
                
                if args.fade_duration > 0:
                    fade_duration = min(args.fade_duration, image_info['duration'] / 2)
                    fade_out_start = image_info['duration'] - fade_duration
                    fade_filter = f"fade=t=in:st=0:d={fade_duration},fade=t=out:st={fade_out_start}:d={fade_duration}"
                    filter_chains.append(f"[{i+1}:v]{fade_filter}[{stream_label}]")
                else:
                    filter_chains.append(f"[{i+1}:v]null[{stream_label}]")
                concat_streams.append(f"[{stream_label}]")

            filter_complex = ";".join(filter_chains) + ";" + "".join(concat_streams) + f"concat=n={len(image_sequence)}:v=1:a=0[outv]"
            
            command = ['ffmpeg'] + inputs + ['-filter_complex', filter_complex]
            
            command.extend(['-map', '[outv]'])
            if audio_stream_exists:
                command.extend(['-map', f'{audio_input_index}:a:0?'])

            if args.hwaccel == 'nvenc':
                command.extend(['-c:v', 'h264_nvenc', '-preset', 'p4'])
            else:
                command.extend(['-c:v', 'libx264'])
            
            if audio_stream_exists:
                command.extend(['-c:a', 'aac', '-b:a', '192k'])

            command.extend(['-r', '24', '-pix_fmt', 'yuv420p', '-shortest', slideshow_with_audio_file, '-y'])

            if not args.verbose:
                command.extend(['-loglevel', 'quiet'])
            
            subprocess.run(command, check=True)
            slideshow_files.append(slideshow_with_audio_file)

        # --- Final Muxing (if necessary) ---
        if slideshow_files:
            if len(slideshow_files) == 1 and not args.keep_original_video:
                print(f"Finalizing output file...")
                shutil.move(slideshow_files[0], args.output_file)
            else:
                print("Muxing final slideshows and streams into a single MKV file...")
                command = ['ffmpeg']
                
                for f in slideshow_files:
                    command.extend(['-i', f])
                
                if args.keep_original_video:
                    command.extend(['-i', args.input_file])

                for i in range(len(slideshow_files)):
                    command.extend(['-map', f'{i}:v', '-map', f'{i}:a?'])

                if args.keep_original_video:
                    original_video_input_index = len(slideshow_files)
                    command.extend(['-map', f'{original_video_input_index}:v', '-map', f'{original_video_input_index}:s?'])

                video_stream_index = 0
                for i, stream in enumerate(subtitle_streams):
                    lang = stream.get('tags', {}).get('language', 'und')
                    title = stream.get('tags', {}).get('title', f'Slideshow from subtitle {i}')
                    command.extend([f'-metadata:s:v:{video_stream_index}', f"language={lang}", f'-metadata:s:v:{video_stream_index}', f"title={title}"])
                    video_stream_index += 1
                
                if args.keep_original_video:
                    command.extend([f'-metadata:s:v:{video_stream_index}', 'title=Original Video'])
                
                command.extend(['-c', 'copy', args.output_file, '-y'])
                
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
