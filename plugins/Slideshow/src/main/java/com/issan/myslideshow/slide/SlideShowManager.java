package com.issan.myslideshow.slide;

import com.issan.myslideshow.MySlideshowPlugin;
import com.issan.myslideshow.mediaplayer.MediaPlayerBridge;
import fr.xxathyx.mediaplayer.screen.Screen;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.entity.ItemFrame;
import org.bukkit.entity.Player;

import java.util.ArrayList;
import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.logging.Level;

public final class SlideShowManager {
    private final MySlideshowPlugin plugin;
    private final MediaPlayerBridge bridge;
    private final SlideEndpointClient endpointClient = new SlideEndpointClient();
    private final Map<String, SlideShow> slideshows = new LinkedHashMap<>();
    private final Set<String> discoveredDecks = new HashSet<>();
    private String decksUrl;

    public SlideShowManager(MySlideshowPlugin plugin, MediaPlayerBridge bridge) {
        this.plugin = plugin;
        this.bridge = bridge;
    }

    public void loadConfiguredSlideshows() {
        shutdown();
        slideshows.clear();
        discoveredDecks.clear();

        String baseUrl = plugin.getConfig().getString("endpoint-base-url", "").trim();
        decksUrl = baseUrl.isBlank() ? null : baseUrl.replaceAll("/+$", "") + "/decks.json";

        ConfigurationSection root = plugin.getConfig().getConfigurationSection("slideshows");
        if (root == null) {
            return;
        }
        for (String name : root.getKeys(false)) {
            ConfigurationSection section = root.getConfigurationSection(name);
            if (section == null) {
                continue;
            }
            String uuidText = section.getString("screen-uuid", "");
            String screenName = section.getString("screen-name", "");
            String endpointUrl = section.getString("endpoint-url", "");
            if (endpointUrl.isBlank()) {
                plugin.getLogger().warning("Skipping slideshow " + name + ": endpoint-url is required.");
                continue;
            }
            try {
                UUID screenUuid = uuidText.isBlank() ? null : UUID.fromString(uuidText);
                SlideShowConfig config = new SlideShowConfig(
                        name,
                        section.getString("title", ""),
                        screenUuid,
                        screenName.isBlank() ? null : screenName,
                        endpointUrl,
                        section.getInt("polling-interval-seconds", 30),
                        section.getBoolean("loop", true)
                );
                slideshows.put(name.toLowerCase(), new SlideShow(plugin, bridge, endpointClient, config));
            } catch (IllegalArgumentException exception) {
                plugin.getLogger().warning("Skipping slideshow " + name + ": invalid screen UUID " + uuidText);
            }
        }
    }

    /**
     * Fetch the deck list from the endpoint server and merge each deck in as a
     * slideshow, so decks created in the uploader UI show up in /slideshow browse
     * without editing config.yml. Runs the HTTP request async and calls
     * onComplete on the main thread (also on failure, with the current list).
     */
    public void discoverDecks(Player requester, Runnable onComplete) {
        if (decksUrl == null) {
            onComplete.run();
            return;
        }
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                List<DeckDefinition> decks = endpointClient.fetchDecks(decksUrl);
                Bukkit.getScheduler().runTask(plugin, () -> {
                    applyDecks(decks);
                    onComplete.run();
                });
            } catch (Exception exception) {
                plugin.getLogger().log(Level.WARNING, "Failed to fetch deck list from " + decksUrl, exception);
                Bukkit.getScheduler().runTask(plugin, () -> {
                    if (requester != null) {
                        requester.sendMessage(ChatColor.RED + "Failed to fetch deck list: " + exception.getMessage());
                    }
                    onComplete.run();
                });
            }
        });
    }

    private void applyDecks(List<DeckDefinition> decks) {
        Set<String> seen = new HashSet<>();
        for (DeckDefinition deck : decks) {
            String name = deck.name().isBlank() ? "default" : deck.name();
            String key = name.toLowerCase(Locale.ROOT);
            seen.add(key);
            SlideShow existing = slideshows.get(key);
            if (existing != null && discoveredDecks.contains(key)) {
                boolean endpointChanged = !existing.config().endpointUrl().equals(deck.endpoint());
                boolean titleChanged = !existing.config().displayName().equals(deck.displayName());
                if (endpointChanged) {
                    existing.detachScreen();
                    slideshows.remove(key);
                    existing = null;
                } else if (titleChanged) {
                    // Recreate config in-place with updated title, keeping the screen binding.
                    SlideShowConfig updated = new SlideShowConfig(name, deck.title(), existing.config().screenUuid(), existing.config().screenName(), deck.endpoint(), existing.config().pollingIntervalSeconds(), existing.config().loop());
                    existing.updateConfig(updated);
                }
            }
            if (existing == null && !slideshows.containsKey(key)) {
                SlideShowConfig config = new SlideShowConfig(name, deck.title(), null, null, deck.endpoint(), 30, true);
                slideshows.put(key, new SlideShow(plugin, bridge, endpointClient, config));
                discoveredDecks.add(key);
            }
        }
        for (String key : new ArrayList<>(discoveredDecks)) {
            if (!seen.contains(key)) {
                SlideShow removed = slideshows.remove(key);
                if (removed != null) {
                    removed.detachScreen();
                }
                discoveredDecks.remove(key);
            }
        }
    }

    public Optional<SlideShow> find(String name) {
        return Optional.ofNullable(slideshows.get(name.toLowerCase()));
    }

    public Optional<SlideShow> first() {
        return slideshows.values().stream().findFirst();
    }

    public Collection<SlideShow> all() {
        return slideshows.values();
    }

    public List<String> names() {
        return slideshows.values().stream().map(SlideShow::name).toList();
    }

    public MediaPlayerBridge bridge() {
        return bridge;
    }

    public void reload(Player requester) {
        plugin.reloadConfig();
        loadConfiguredSlideshows();
        if (requester != null) {
            requester.sendMessage(ChatColor.GREEN + "Reloaded slideshow config.");
        }
    }

    public void shutdown() {
        for (SlideShow slideShow : slideshows.values()) {
            slideShow.stop();
        }
    }

    public Optional<SlideShow> findByFrame(ItemFrame frame) {
        return slideshows.values().stream()
                .filter(slideShow -> slideShow.containsFrame(frame))
                .findFirst();
    }

    /**
     * Bind the slideshow to the screen and start it there. Any other slideshow
     * currently playing on that screen is stopped first, so a screen only ever
     * shows one slideshow.
     */
    public void startOnScreen(SlideShow slideShow, Screen screen, Player initiator) {
        for (SlideShow other : slideshows.values()) {
            if (other != slideShow && other.isOnScreen(screen)) {
                other.detachScreen();
            }
        }
        slideShow.startOnScreen(screen, initiator);
    }
}
