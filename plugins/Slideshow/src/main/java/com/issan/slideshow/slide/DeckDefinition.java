package com.issan.slideshow.slide;

public record DeckDefinition(String name, String title, String endpoint) {
    public String displayName() {
        return (title != null && !title.isBlank()) ? title : (name.isBlank() ? "default" : name);
    }
}
