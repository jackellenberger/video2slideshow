# Base image
FROM jrottenberg/ffmpeg:5.1-nvidia

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ../../python/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# Set up the working directory
WORKDIR /app

# Copy the python script
COPY ../../python/video_slideshow_generator.py /app/

# Set the entrypoint
ENTRYPOINT ["python3", "-u", "/app/video_slideshow_generator.py"]
