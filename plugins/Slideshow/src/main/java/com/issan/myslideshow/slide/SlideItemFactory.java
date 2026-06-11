package com.issan.myslideshow.slide;

import com.issan.myslideshow.MySlideshowPlugin;
import com.issan.myslideshow.mediaplayer.MediaPlayerBridge;
import org.bukkit.ChatColor;
import org.bukkit.Material;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataContainer;
import org.bukkit.persistence.PersistentDataType;

import java.util.ArrayList;
import java.util.List;

public final class SlideItemFactory {
    private final MySlideshowPlugin plugin;
    private final MediaPlayerBridge bridge;

    public SlideItemFactory(MySlideshowPlugin plugin, MediaPlayerBridge bridge) {
        this.plugin = plugin;
        this.bridge = bridge;
    }

    public ItemStack createControlWand() {
        ItemStack item = new ItemStack(Material.STICK);
        ItemMeta meta = item.getItemMeta();
        if (meta != null) {
            meta.setDisplayName(ChatColor.GOLD + "Slideshow Controller");
            List<String> lore = new ArrayList<>();
            lore.add(ChatColor.YELLOW + "Right-click a screen: next slide");
            lore.add(ChatColor.YELLOW + "Left-click a screen: previous slide");
            meta.setLore(lore);
            meta.getPersistentDataContainer().set(plugin.controlWandKey(), PersistentDataType.BYTE, (byte) 1);
            meta.setEnchantmentGlintOverride(true);
            item.setItemMeta(meta);
        }
        return item;
    }

    public ItemStack createMenuItem() {
        ItemStack item = new ItemStack(Material.MUSIC_DISC_CAT);
        ItemMeta meta = item.getItemMeta();
        if (meta != null) {
            meta.setDisplayName(ChatColor.GOLD + "Slideshow Menu");
            List<String> lore = new ArrayList<>();
            lore.add(ChatColor.YELLOW + "Right-click to open the slideshow list.");
            meta.setLore(lore);
            meta.getPersistentDataContainer().set(plugin.menuItemKey(), PersistentDataType.BYTE, (byte) 1);
            meta.setEnchantmentGlintOverride(true);
            item.setItemMeta(meta);
        }
        return item;
    }

    public ItemStack createSlideShowItem(SlideShow slideShow) {
        List<Slide> slides = slideShow.slides();
        Slide thumbnail = slides.stream().filter(Slide::hasRenderedMaps).findFirst().orElse(null);
        ItemStack item = thumbnail != null
                ? bridge.mapItem(thumbnail.mapIds()[0])
                : new ItemStack(Material.FILLED_MAP);

        ItemMeta meta = item.getItemMeta();
        if (meta != null) {
            meta.setDisplayName(ChatColor.AQUA + slideShow.displayName());
            List<String> lore = new ArrayList<>();
            lore.add(ChatColor.GRAY + "Slides: " + (slides.isEmpty() ? "loading..." : String.valueOf(slides.size())));
            if (!slideShow.displayName().equals(slideShow.name())) {
                lore.add(ChatColor.DARK_GRAY + slideShow.name());
            }
            lore.add(ChatColor.GRAY + slideShow.config().endpointUrl());
            lore.add(ChatColor.YELLOW + "Right-click a screen to play this slideshow.");
            meta.setLore(lore);
            meta.getPersistentDataContainer().set(plugin.slideshowNameKey(), PersistentDataType.STRING, slideShow.name());
            meta.setEnchantmentGlintOverride(true);
            item.setItemMeta(meta);
        }
        return item;
    }

    public ItemStack createSlideItem(Slide slide) {
        ItemStack item = slide.hasRenderedMaps()
                ? bridge.mapItem(slide.mapIds()[0])
                : new ItemStack(Material.FILLED_MAP);

        ItemMeta meta = item.getItemMeta();
        if (meta != null) {
            meta.setDisplayName(ChatColor.AQUA + "Slide " + slide.index());
            List<String> lore = new ArrayList<>();
            lore.add(ChatColor.GRAY + slide.url());
            meta.setLore(lore);
            PersistentDataContainer pdc = meta.getPersistentDataContainer();
            pdc.set(plugin.slideUrlKey(), PersistentDataType.STRING, slide.url());
            pdc.set(plugin.slideIndexKey(), PersistentDataType.INTEGER, slide.index());
            meta.setEnchantmentGlintOverride(true);
            item.setItemMeta(meta);
        }
        return item;
    }
}
