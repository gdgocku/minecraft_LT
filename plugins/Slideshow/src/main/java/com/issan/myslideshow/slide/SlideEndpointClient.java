package com.issan.myslideshow.slide;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

public final class SlideEndpointClient {
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();
    public List<SlideDefinition> fetchSlides(String endpointUrl) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(endpointUrl))
                .timeout(Duration.ofSeconds(20))
                .GET()
                .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Slide endpoint returned HTTP " + response.statusCode());
        }

        JsonElement root = JsonParser.parseString(response.body());
        if (!root.isJsonArray()) {
            throw new IOException("Slide endpoint must return a JSON array");
        }

        List<SlideDefinition> definitions = new ArrayList<>();
        JsonArray array = root.getAsJsonArray();
        for (JsonElement element : array) {
            if (!element.isJsonObject()) {
                continue;
            }
            JsonObject object = element.getAsJsonObject();
            if (!object.has("url") || !object.has("index")) {
                continue;
            }
            String url = object.get("url").getAsString();
            int index = object.get("index").getAsInt();
            definitions.add(new SlideDefinition(index, url));
        }
        definitions.sort(Comparator.comparingInt(SlideDefinition::index));
        return definitions;
    }

    /**
     * Fetch the deck list from the endpoint server's /decks.json:
     * [{"name": "yorushika", "endpoint": "http://.../decks/yorushika/slides.json", ...}, ...]
     * An empty name means the server's default deck.
     */
    public List<DeckDefinition> fetchDecks(String decksUrl) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(decksUrl))
                .timeout(Duration.ofSeconds(20))
                .GET()
                .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IOException("Deck endpoint returned HTTP " + response.statusCode());
        }

        JsonElement root = JsonParser.parseString(response.body());
        if (!root.isJsonArray()) {
            throw new IOException("Deck endpoint must return a JSON array");
        }

        List<DeckDefinition> decks = new ArrayList<>();
        for (JsonElement element : root.getAsJsonArray()) {
            if (!element.isJsonObject()) {
                continue;
            }
            JsonObject object = element.getAsJsonObject();
            if (!object.has("name") || !object.has("endpoint")) {
                continue;
            }
            String title = object.has("title") ? object.get("title").getAsString() : "";
            decks.add(new DeckDefinition(object.get("name").getAsString(), title, object.get("endpoint").getAsString()));
        }
        return decks;
    }

    public BufferedImage fetchImage(String imageUrl) throws IOException {
        BufferedImage image = ImageIO.read(URI.create(imageUrl).toURL());
        if (image == null) {
            throw new IOException("Unsupported image: " + imageUrl);
        }
        return image;
    }
}
