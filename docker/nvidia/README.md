# Python with NVIDIA GPU Support

This directory contains the necessary files to build a Docker container that can run the Python implementation with NVIDIA GPU support.

## Prerequisites

- Docker installed
- NVIDIA GPU drivers installed on the host machine
- NVIDIA Container Toolkit installed

## Building the Docker Image

To build the Docker image, run the following command from the root of the repository:

```bash
docker build -t video-slideshow-nvidia -f docker/nvidia/Dockerfile .
```

## Running the Python Script

To run the `video_slideshow_generator.py` script inside the container, you need to mount the directory containing your input video file and the directory where you want to save the output file.

Here's an example command:

```bash
docker run --gpus all \
    -v /path/to/your/input:/input \
    -v /path/to/your/output:/output \
    video-slideshow-nvidia \
    /input/your_video.mkv \
    -o /output/slideshow.mp4
```

or if you're me,

```bash
docker run --gpus all -v "/mnt/c/Users/jacka/Downloads":/input   -v "/mnt/c/Users/jacka/Documents/github/video2slideshow":/output   video-slideshow-nvidia   "/input/Porco Rosso (1992) 1080p AAC.mkv"   -o "/output/porco_rosso_nvidia_500.mkv"   --max_frame_length 5   --hwaccel nvenc   --preview 500
```

**Explanation:**

- `docker run --gpus all`: This flag enables the container to access the host's NVIDIA GPU.
- `-v /path/to/your/input:/input`: This mounts the directory containing your input video file to the `/input` directory inside the container.
- `-v /path/to/your/output:/output`: This mounts the directory where you want to save the output file to the `/output` directory inside the container.
- `video-slideshow-nvidia`: This is the name of the Docker image you built.
- `/input/your_video.mkv`: This is the path to your input video file inside the container.
- `-o /output/slideshow.mp4`: This is the path where the output slideshow will be saved inside the container.

### Verifying the Setup

To verify that the NVIDIA GPU is being used, you can check the output of the script. When `ffmpeg` is using the GPU, you should see lines in the output that mention `h264_nvenc`. You can also run the `nvidia-smi` command inside the container to check the GPU status.

To get a shell inside the container, you can run:

```bash
docker run --gpus all -it video-slideshow-nvidia /bin/bash
```

Then, from inside the container, you can run `nvidia-smi` to see the GPU information. You can also run the python script manually from within the container.
