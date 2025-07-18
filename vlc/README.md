# video2slideshow

A VLC video filter plugin that transforms video playback into a slideshow.

## Building

To build the plugin, you will need:

* A C++ compiler
* Meson
* Ninja
* The VLC development libraries

Once you have the dependencies installed, you can build the plugin with the following commands:

```bash
meson build
ninja -C build
```

## Installing

To install the plugin, copy the compiled library to the VLC plugins directory.

On Windows, this is typically `C:\Program Files\VLC\plugins\video_filter`.

On Linux, this is typically `/usr/lib/vlc/plugins/video_filter`.

## Usage

Once the plugin is installed, you can enable it in the VLC preferences.

Go to Tools -> Preferences -> Video -> Filters -> video2slideshow.

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for more information.
