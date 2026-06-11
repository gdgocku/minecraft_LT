package com.issan.myslideshow.slide;

import com.issan.myslideshow.MySlideshowPlugin;
import com.issan.myslideshow.mediaplayer.MediaPlayerBridge;
import fr.xxathyx.mediaplayer.screen.Screen;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.World;
import org.bukkit.entity.ItemFrame;
import org.bukkit.entity.Player;

import java.awt.image.BufferedImage;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.logging.Level;

public final class SlideShow {
    private final MySlideshowPlugin plugin;
    private final MediaPlayerBridge bridge;
    private final SlideEndpointClient endpointClient;
    private SlideShowConfig config;
    private final List<Slide> slides = new ArrayList<>();
    private Screen screen;
    private int currentIndex;
    private int pollingTaskId = -1;

    public SlideShow(MySlideshowPlugin plugin, MediaPlayerBridge bridge, SlideEndpointClient endpointClient, SlideShowConfig config) {
        this.plugin = plugin;
        this.bridge = bridge;
        this.endpointClient = endpointClient;
        this.config = config;
    }

    public String name() {
        return config.name();
    }

    public String displayName() {
        return config.displayName();
    }

    public SlideShowConfig config() {
        return config;
    }

    public void updateConfig(SlideShowConfig newConfig) {
        this.config = newConfig;
    }

    public List<Slide> slides() {
        return List.copyOf(slides);
    }

    public Optional<Screen> screen() {
        return Optional.ofNullable(screen);
    }

    /**
     * Switch the projection target to the given screen at runtime and redraw the
     * current slide there. Used by /slideshow screen so the target can be picked
     * in-game instead of editing config.yml.
     */
    public void useScreen(Screen target) {
        this.screen = target;
        renderCurrent();
    }

    /**
     * Bind this slideshow to the given screen and start playing on it. Used when a
     * player right-clicks a screen with a slideshow item from /slideshow browse.
     */
    public void startOnScreen(Screen target, Player initiator) {
        this.screen = target;
        begin(initiator);
    }

    public void start(Player initiator) {
        if (screen == null) {
            screen = bridge.findScreen(config.screenUuid(), config.screenName()).orElse(null);
        }
        if (screen == null) {
            String message = "Slideshow " + config.name() + " is not bound to a screen yet. "
                    + "Take its item from /slideshow browse and right-click a screen.";
            plugin.getLogger().warning(message);
            if (initiator != null) {
                initiator.sendMessage(ChatColor.RED + message);
            }
            return;
        }
        begin(initiator);
    }

    private void begin(Player initiator) {
        refreshNow(true, initiator);
        stopPolling();
        long intervalTicks = Math.max(1, config.pollingIntervalSeconds()) * 20L;
        pollingTaskId = Bukkit.getScheduler().runTaskTimerAsynchronously(plugin, () -> refreshNow(false, null), intervalTicks, intervalTicks).getTaskId();
    }

    public void stop() {
        stopPolling();
    }

    /** Stop playback and release the screen so another slideshow can take it over. */
    public void detachScreen() {
        stop();
        screen = null;
    }

    public boolean isOnScreen(Screen other) {
        return screen != null && other != null && screen.getUUID().equals(other.getUUID());
    }

    public void refreshNow(boolean renderAfterRefresh, Player requester) {
        Bukkit.getScheduler().runTask(plugin, () -> {
            List<Slide> previousSlides = List.copyOf(slides);
            Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
                try {
                    List<SlideDefinition> definitions = endpointClient.fetchSlides(config.endpointUrl());
                    Map<String, BufferedImage> changedImages = fetchChangedImages(definitions, previousSlides);
                    Bukkit.getScheduler().runTask(plugin, () -> applyDefinitions(definitions, changedImages, renderAfterRefresh, requester));
                } catch (Exception exception) {
                    plugin.getLogger().log(Level.WARNING, "Failed to refresh slideshow " + config.name(), exception);
                    if (requester != null) {
                        Bukkit.getScheduler().runTask(plugin, () -> requester.sendMessage(ChatColor.RED + "Failed to refresh slideshow: " + exception.getMessage()));
                    }
                }
            });
        });
    }

    public void next() {
        if (slides.isEmpty()) {
            return;
        }
        if (currentIndex + 1 >= slides.size() && !config.loop()) {
            return;
        }
        currentIndex = (currentIndex + 1) % slides.size();
        renderCurrent();
    }

    public void prev() {
        if (slides.isEmpty()) {
            return;
        }
        if (currentIndex == 0 && !config.loop()) {
            return;
        }
        currentIndex = (currentIndex - 1 + slides.size()) % slides.size();
        renderCurrent();
    }

    public void gotoSlide(int slideIndex) {
        for (int i = 0; i < slides.size(); i++) {
            if (slides.get(i).index() == slideIndex) {
                currentIndex = i;
                renderCurrent();
                return;
            }
        }
    }

    public boolean containsFrame(ItemFrame frame) {
        return screen != null && bridge.screenContainsFrame(screen, frame);
    }

    public void renderUrlToScreen(String url, Player requester) {
        Screen target = screen;
        if (target == null) {
            if (requester != null) {
                requester.sendMessage(ChatColor.RED + "Slideshow screen is not started.");
            }
            return;
        }
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                BufferedImage image = endpointClient.fetchImage(url);
                Bukkit.getScheduler().runTask(plugin, () -> {
                    int[] mapIds = bridge.createMapIds(worldForScreen(target), image);
                    bridge.displayOnScreen(target, mapIds);
                });
            } catch (Exception exception) {
                plugin.getLogger().log(Level.WARNING, "Failed to render slide " + url, exception);
                if (requester != null) {
                    Bukkit.getScheduler().runTask(plugin, () -> requester.sendMessage(ChatColor.RED + "Failed to render slide: " + exception.getMessage()));
                }
            }
        });
    }

    /**
     * Returns whether the slides in this show are compatible with the given screen.
     * Requires at least one slide to have been rendered; returns true if none have
     * loaded yet (size unknown).
     */
    public boolean isCompatibleWithScreen(Screen target) {
        Slide first = slides.stream().filter(Slide::hasRenderedMaps).findFirst().orElse(null);
        if (first == null) {
            return true;
        }
        int required = target.getWidth() * 128;
        int requiredH = target.getHeight() * 128;
        return first.imageWidth() == required && first.imageHeight() == requiredH;
    }

    public String screenSizeString(Screen target) {
        return target.getWidth() + "×" + target.getHeight()
                + " (" + (target.getWidth() * 128) + "×" + (target.getHeight() * 128) + "px)";
    }

    public String slideSizeString() {
        Slide first = slides.stream().filter(Slide::hasRenderedMaps).findFirst().orElse(null);
        if (first == null) {
            return "unknown";
        }
        return first.imageWidth() + "×" + first.imageHeight() + "px";
    }

    private Map<String, BufferedImage> fetchChangedImages(List<SlideDefinition> definitions, List<Slide> previousSlides) throws Exception {
        Map<Integer, Slide> previousByIndex = new HashMap<>();
        for (Slide slide : previousSlides) {
            previousByIndex.put(slide.index(), slide);
        }

        Map<String, BufferedImage> images = new HashMap<>();
        for (SlideDefinition definition : definitions) {
            Slide previous = previousByIndex.get(definition.index());
            if (previous == null || !previous.url().equals(definition.url()) || !previous.hasRenderedMaps()) {
                images.put(definition.url(), endpointClient.fetchImage(definition.url()));
            }
        }
        return images;
    }

    private void applyDefinitions(List<SlideDefinition> definitions, Map<String, BufferedImage> changedImages, boolean renderAfterRefresh, Player requester) {
        Map<Integer, Slide> previousByIndex = new HashMap<>();
        for (Slide slide : slides) {
            previousByIndex.put(slide.index(), slide);
        }

        List<Slide> nextSlides = new ArrayList<>();
        World world = screen == null ? Bukkit.getWorlds().get(0) : worldForScreen(screen);
        for (SlideDefinition definition : definitions) {
            Slide slide = previousByIndex.get(definition.index());
            if (slide == null || !slide.url().equals(definition.url())) {
                slide = new Slide(definition.index(), definition.url());
            }
            BufferedImage image = changedImages.get(definition.url());
            if (image != null) {
                slide.setMapIds(bridge.createMapIds(world, image), image.getWidth(), image.getHeight());
            }
            nextSlides.add(slide);
        }

        slides.clear();
        slides.addAll(nextSlides);
        if (currentIndex >= slides.size()) {
            currentIndex = Math.max(0, slides.size() - 1);
        }
        if (renderAfterRefresh) {
            renderCurrent();
        }
        if (requester != null) {
            requester.sendMessage(ChatColor.GREEN + "Loaded " + slides.size() + " slides for " + config.name() + ".");
        }
    }

    private void renderCurrent() {
        if (screen == null || slides.isEmpty()) {
            return;
        }
        Slide slide = slides.get(currentIndex);
        if (!slide.hasRenderedMaps()) {
            return;
        }
        bridge.displayOnScreen(screen, slide.mapIds());
    }

    private World worldForScreen(Screen targetScreen) {
        return bridge.screenWorld(targetScreen).orElseGet(() -> Bukkit.getWorlds().get(0));
    }

    private void stopPolling() {
        if (pollingTaskId != -1) {
            Bukkit.getScheduler().cancelTask(pollingTaskId);
            pollingTaskId = -1;
        }
    }
}
