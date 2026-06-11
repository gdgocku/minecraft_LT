package com.issan.myslideshow.slide;

import java.util.Arrays;

public final class Slide {
    private final int index;
    private final String url;
    private int[] mapIds;
    private int imageWidth;
    private int imageHeight;

    public Slide(int index, String url) {
        this.index = index;
        this.url = url;
    }

    public int index() {
        return index;
    }

    public String url() {
        return url;
    }

    public int[] mapIds() {
        return mapIds == null ? null : Arrays.copyOf(mapIds, mapIds.length);
    }

    public void setMapIds(int[] mapIds, int imageWidth, int imageHeight) {
        this.mapIds = mapIds == null ? null : Arrays.copyOf(mapIds, mapIds.length);
        this.imageWidth = imageWidth;
        this.imageHeight = imageHeight;
    }

    public int imageWidth() {
        return imageWidth;
    }

    public int imageHeight() {
        return imageHeight;
    }

    public boolean hasRenderedMaps() {
        return mapIds != null && mapIds.length > 0;
    }
}
