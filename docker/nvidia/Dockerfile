# Base image
FROM nvidia/cuda:11.8.0-base-ubuntu22.04

# Install dependencies for building ffmpeg
RUN apt-get update && apt-get install -y \
    build-essential \
    yasm \
    cmake \
    libtool \
    libc6 \
    libc6-dev \
    unzip \
    wget \
    python3 \
    python3-pip \
    git \
    nasm \
    libx264-dev \
    libx265-dev \
    libnuma-dev \
    libvpx-dev \
    libfdk-aac-dev \
    libmp3lame-dev \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# Build and install ffmpeg from source with NVIDIA support
RUN git clone https://git.ffmpeg.org/ffmpeg.git ffmpeg && \
    cd ffmpeg && \
    ./configure \
        --enable-gpl \
        --enable-version3 \
        --enable-nonfree \
        --enable-nvenc \
        --enable-cuvid \
        --enable-libnpp \
        --extra-cflags="-I/usr/local/cuda/include" \
        --extra-ldflags="-L/usr/local/cuda/lib64" \
        --enable-libx264 \
        --enable-libx265 \
        --enable-libvpx \
        --enable-libfdk-aac \
        --enable-libmp3lame \
        --enable-libopus && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    rm -rf ffmpeg

# Install Python dependencies
COPY ../../python/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Set up the working directory
WORKDIR /app

# Copy the python script
COPY ../../python/video_slideshow_generator.py /app/

# Set the entrypoint
ENTRYPOINT ["python3", "/app/video_slideshow_generator.py"]
