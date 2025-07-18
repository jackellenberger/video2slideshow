project('video2slideshow', 'cpp',
        version: '0.1.0',
        meson_version: '>=0.50.0',
        default_options: ['cpp_std=c++17'])

vlc_dep = dependency('vlc')

shared_module('video2slideshow',
              'src/video2slideshow.cpp',
              dependencies: [vlc_dep],
              install: true,
              install_dir: get_option('libdir') / 'vlc/plugins/video_filter')
