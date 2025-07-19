import subprocess

try:
    subprocess.run([
        'ffmpeg',
        '-i', 'sample.mp4',
        '-i', 'sample.vtt',
        '-i', 'dummy.vtt',
        '-c', 'copy',
        '-map', '0',
        '-map', '1',
        '-map', '2',
        '-metadata:s:s:0', 'language=eng',
        '-metadata:s:s:1', 'language=spa',
        'test.mkv',
        '-y' # Overwrite output file if it exists
    ], check=True)
    print("Test MKV created successfully.")
except subprocess.CalledProcessError as e:
    print(f"Error creating test MKV: {e}")
