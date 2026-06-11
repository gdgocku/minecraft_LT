package com.issan.myslideshow.slide;

public record DeckDefinition(String name, String title, String endpoint) {
    public String displayName() {
        return (title != null && !title.isBlank()) ? title : (name.isBlank() ? "default" : name);
    }
}
