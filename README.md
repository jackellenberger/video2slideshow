# Video2Slideshow

This project allows users to input a full motion video file and receive in return a video file that "samples and holds" the original, reducing for example a 24 frames-per-second video into a 4 seconds-per-frame video. The special sauce is that when subtitles are present, it won't give you one frame every 4 seconds, it will give you one frame each time a character speaks, (plus frames every 4 seconds when no one is speaking) so that you can read the facial expressions of characters as they express themselves. Pretty neat.

I made this project because my partner got slonked silly style and can't watch full motion video, but we want to watch boyslove content. I hope it proves useful to others. 

### Usage

See python/README.md or docker/nvidia/README.md

Despite that path it'll proooobably work without an nvidia graphics card.

## This is slop

One of the reasons this project exists is because I saw jules.google.com at Google I/O and I thought "that's cool let's make it do something for me" and I told it to make this project. It's not "vibe coded", it is "project managed". I made it a challenge for myself to never open an editor or understand the code.

I hated this process and hope to never do it again.

## Performance

Just anecdotally, the project as of 2025-11-29 takes a 1.06GB, 49 minute episode of television, and with one subtitle stream exports a slideshow in about 5-6 minutes. the total time is going to be very dependent on 1) how talkative your content is, 2) how long your min and max frame lengths are, 3) your CPU, and especially 4) how many video tracks you are trying to output. If you do not limit your subtitle\_tracks and slideshowify a video with N subtitle streams, you're going to essentially run the whole encode flow N times.

## Cul-de-sacs

* I originally wanted this project to not reencode video, and instead just operate as a VLC plugin. I think this is still possible as a solution, but the development environment proved too arduous for the tooling I wanted to use, so that path is currently a stub.

* On my first pass at creating the ffmpeg version, i just wrote a bash script. So there's the carcass of that floating around.

* I tried to speed up encoding by using my graphics card, and updated the project to support hardware acceleration. Uhh that didn't seem to work, my render times actually went up, so something is obviously incorrectly configured there.

* The method this project currently uses is to save off png or jpg frames at each new slideshow keyframe then stitch them back together. Probably there is an ffmpeg filter graph that will do this in one step, but I haven't found the way to do it.
