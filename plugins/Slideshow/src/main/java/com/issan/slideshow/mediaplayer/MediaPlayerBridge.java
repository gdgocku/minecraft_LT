package com.issan.slideshow.mediaplayer;

import com.issan.slideshow.SlideShowPlugin;
import fr.xxathyx.mediaplayer.Main;
import fr.xxathyx.mediaplayer.api.MediaPlayerAPI;
import fr.xxathyx.mediaplayer.image.renderer.ImageRenderer;
import fr.xxathyx.mediaplayer.items.ItemStacks;
import fr.xxathyx.mediaplayer.screen.Screen;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.World;
import org.bukkit.entity.ItemFrame;
import org.bukkit.entity.Player;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.Plugin;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.net.URI;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import java.util.logging.Level;

public final class MediaPlayerBridge {
    private final SlideShowPlugin plugin;
    private final ItemStacks itemStacks = new ItemStacks();

    public MediaPlayerBridge(SlideShowPlugin plugin) {
        this.plugin = plugin;
    }

    public Optional<Screen> findScreen(UUID uuid, String name) {
        Main mediaPlayer = mediaPlayerPlugin().orElse(null);
        if (mediaPlayer == null) {
            return Optional.empty();
        }

        for (Screen screen : mediaPlayer.getRegisteredScreens()) {
            if ((uuid != null && uuid.equals(screen.getUUID())) || (name != null && name.equalsIgnoreCase(screen.getName()))) {
                return Optional.of(screen);
            }
        }
        return Optional.empty();
    }

    public Optional<Screen> findScreenByFrame(ItemFrame frame) {
        Main mediaPlayer = mediaPlayerPlugin().orElse(null);
        if (mediaPlayer == null) {
            return Optional.empty();
        }
        for (Screen screen : mediaPlayer.getRegisteredScreens()) {
            if (screen.getFrames().contains(frame)) {
                return Optional.of(screen);
            }
        }
        return Optional.empty();
    }

    public int[] createMapIds(World world, BufferedImage image) {
        ImageRenderer renderer = new ImageRenderer(image);
        renderer.createMaps(world);
        return toIntArray(renderer.getIds());
    }

    public ItemStack mapItem(int mapId) {
        return itemStacks.getMap(mapId);
    }

    public void displayOnScreen(Screen screen, int[] mapIds) {
        List<ItemFrame> frames = screen.getFrames();
        int count = Math.min(frames.size(), mapIds.length);
        for (int i = 0; i < count; i++) {
            frames.get(i).setItem(mapItem(mapIds[i]));
        }
    }

    public boolean screenContainsFrame(Screen screen, ItemFrame frame) {
        return screen.getFrames().contains(frame);
    }

    public Optional<World> screenWorld(Screen screen) {
        List<ItemFrame> frames = screen.getFrames();
        if (frames.isEmpty()) {
            return Optional.empty();
        }
        return Optional.of(frames.get(0).getWorld());
    }

    public void renderUrlToSingleFrame(String url, ItemFrame itemFrame, Player requester) {
        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                BufferedImage image = ImageIO.read(URI.create(url).toURL());
                if (image == null) {
                    throw new IllegalStateException("Unsupported image: " + url);
                }
                Bukkit.getScheduler().runTask(plugin, () -> {
                    int[] ids = createMapIds(itemFrame.getWorld(), image);
                    if (ids.length > 0) {
                        itemFrame.setItem(mapItem(ids[0]));
                        requester.sendMessage(ChatColor.GREEN + "Projected slide to item frame.");
                    }
                });
            } catch (Exception exception) {
                plugin.getLogger().log(Level.WARNING, "Failed to render slide to item frame", exception);
                Bukkit.getScheduler().runTask(plugin, () -> requester.sendMessage(ChatColor.RED + "Failed to project slide: " + exception.getMessage()));
            }
        });
    }

    private Optional<Main> mediaPlayerPlugin() {
        try {
            Main apiPlugin = MediaPlayerAPI.getPlugin();
            if (apiPlugin != null) {
                return Optional.of(apiPlugin);
            }
        } catch (RuntimeException ignored) {
        }

        Plugin plugin = Bukkit.getPluginManager().getPlugin("MediaPlayer");
        if (plugin instanceof Main main) {
            return Optional.of(main);
        }
        return Optional.empty();
    }

    private int[] toIntArray(ArrayList<Object> values) {
        int[] ids = new int[values.size()];
        for (int i = 0; i < values.size(); i++) {
            Object value = values.get(i);
            if (value instanceof Number number) {
                ids[i] = number.intValue();
            } else {
                ids[i] = Integer.parseInt(String.valueOf(value));
            }
        }
        return ids;
    }
}
