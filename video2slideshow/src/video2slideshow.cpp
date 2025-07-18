#include "video2slideshow.h"
#include <vlc_common.h>
#include <vlc_plugin.h>
#include <vlc_filter.h>

extern "C"
{
    static int Open(vlc_object_t *);
    static void Close(vlc_object_t *);
    static picture_t *Filter(filter_t *, picture_t *);
}

vlc_module_begin()
    set_shortname("video2slideshow")
    set_description("Video to slideshow filter")
    set_capability("video filter", 0)
    set_callbacks(Open, Close)
    add_shortcut("video2slideshow")
vlc_module_end()

static int Open(vlc_object_t *p_this)
{
    filter_t *p_filter = (filter_t *)p_this;
    p_filter->p_sys = malloc(sizeof(filter_sys_t));
    if (!p_filter->p_sys)
        return VLC_ENOMEM;

    filter_sys_t *p_sys = (filter_sys_t *)p_filter->p_sys;
    p_sys->p_held_pic = NULL;

    return VLC_SUCCESS;
}

static void Close(vlc_object_t *p_this)
{
    filter_t *p_filter = (filter_t *)p_this;
    filter_sys_t *p_sys = (filter_sys_t *)p_filter->p_sys;

    if (p_sys->p_held_pic)
        picture_Release(p_sys->p_held_pic);

    free(p_sys);
}

static picture_t *Filter(filter_t *p_filter, picture_t *p_pic)
{
    if (!p_pic)
        return NULL;

    filter_sys_t *p_sys = (filter_sys_t *)p_filter->p_sys;

    // Check for new subtitles
    vlc_value_t val;
    int i_spu_count = var_Get(p_filter, "spu-count", &val);
    if (i_spu_count > 0)
    {
        // New subtitle detected, hold the current frame
        if (p_sys->p_held_pic)
            picture_Release(p_sys->p_held_pic);
        p_sys->p_held_pic = picture_Clone(p_pic);
    }

    if (p_sys->p_held_pic)
    {
        // Return the held frame
        return picture_Clone(p_sys->p_held_pic);
    }
    else
    {
        // No subtitle, pass through the current frame
        return p_pic;
    }
}
