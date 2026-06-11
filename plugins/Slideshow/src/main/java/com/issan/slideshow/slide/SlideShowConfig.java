package com.issan.slideshow.slide;

import java.util.UUID;

public record SlideShowConfig(
        String name,
        String title,
        UUID screenUuid,
        String screenName,
        String endpointUrl,
        int pollingIntervalSeconds,
        boolean loop
) {
    public String displayName() {
        return (title != null && !title.isBlank()) ? title : name;
    }
}
