#ifndef VIDEO2SLIDESHOW_H
#define VIDEO2SLIDESHOW_H

#include <vlc_common.h>
#include <vlc_plugin.h>
#include <vlc_filter.h>

typedef struct filter_sys_t
{
    picture_t *p_held_pic;
} filter_sys_t;

#endif // VIDEO2SLIDESHOW_H
