package com.issan.myslideshow.gui;

import com.issan.myslideshow.MySlideshowPlugin;
import com.issan.myslideshow.slide.SlideItemFactory;
import com.issan.myslideshow.slide.SlideShow;
import com.issan.myslideshow.slide.SlideShowManager;
import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.Material;
import org.bukkit.entity.Player;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;

import java.util.List;

public final class SlideBrowser {
    private final SlideShowManager manager;
    private final SlideItemFactory itemFactory;

    public SlideBrowser(MySlideshowPlugin plugin, SlideShowManager manager) {
        this.manager = manager;
        this.itemFactory = new SlideItemFactory(plugin, manager.bridge());
    }

    /**
     * Re-discover decks from the endpoint server, refresh empty slideshows, then
     * open the browser. Used by /slideshow browse and the menu item so both always
     * show the latest deck list.
     */
    public void openWithDiscovery(Player player) {
        manager.discoverDecks(player, () -> {
            if (manager.all().isEmpty()) {
                player.sendMessage(ChatColor.RED + "No configured slideshow found.");
                return;
            }
            for (SlideShow slideShow : manager.all()) {
                if (slideShow.slides().isEmpty()) {
                    slideShow.refreshNow(false, null);
                }
            }
            open(player, 0);
        });
    }

    public void open(Player player, int page) {
        List<SlideShow> slideshows = List.copyOf(manager.all());
        int maxPage = Math.max(0, (slideshows.size() - 1) / SlideBrowserHolder.PAGE_SIZE);
        int boundedPage = Math.max(0, Math.min(page, maxPage));

        SlideBrowserHolder holder = new SlideBrowserHolder(boundedPage);
        Inventory inventory = Bukkit.createInventory(holder, 54, "Slideshows (" + (boundedPage + 1) + "/" + (maxPage + 1) + ")");
        int offset = boundedPage * SlideBrowserHolder.PAGE_SIZE;
        for (int slot = 0; slot < SlideBrowserHolder.PAGE_SIZE && offset + slot < slideshows.size(); slot++) {
            inventory.setItem(slot, itemFactory.createSlideShowItem(slideshows.get(offset + slot)));
        }

        if (boundedPage > 0) {
            inventory.setItem(SlideBrowserHolder.PREV_SLOT, navItem(Material.ARROW, ChatColor.YELLOW + "Previous Page"));
        }
        inventory.setItem(SlideBrowserHolder.CLOSE_SLOT, navItem(Material.BARRIER, ChatColor.RED + "Close"));
        inventory.setItem(SlideBrowserHolder.WAND_SLOT, navItem(Material.STICK, ChatColor.GOLD + "Get Controller Wand"));
        inventory.setItem(SlideBrowserHolder.RELOAD_SLOT, navItem(Material.CLOCK, ChatColor.GREEN + "Reload Slideshows"));
        if (boundedPage < maxPage) {
            inventory.setItem(SlideBrowserHolder.NEXT_SLOT, navItem(Material.ARROW, ChatColor.YELLOW + "Next Page"));
        }
        player.openInventory(inventory);
    }

    public SlideItemFactory itemFactory() {
        return itemFactory;
    }

    private ItemStack navItem(Material material, String name) {
        ItemStack item = new ItemStack(material);
        ItemMeta meta = item.getItemMeta();
        if (meta != null) {
            meta.setDisplayName(name);
            item.setItemMeta(meta);
        }
        return item;
    }
}
