package com.issan.slideshow.listener;

import com.issan.slideshow.SlideShowPlugin;
import com.issan.slideshow.gui.SlideBrowser;
import com.issan.slideshow.gui.SlideBrowserHolder;
import com.issan.slideshow.slide.SlideShow;
import com.issan.slideshow.slide.SlideShowManager;
import fr.xxathyx.mediaplayer.screen.Screen;
import org.bukkit.ChatColor;
import org.bukkit.NamespacedKey;
import org.bukkit.entity.Entity;
import org.bukkit.entity.ItemFrame;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;

import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

public final class SlideShowListener implements Listener {
    private static final long WAND_COOLDOWN_MILLIS = 200;
    private static final int WAND_RANGE = 16;

    private final SlideShowPlugin plugin;
    private final SlideShowManager manager;
    private final SlideBrowser browser;
    private final Map<UUID, Long> wandLastUse = new HashMap<>();

    public SlideShowListener(SlideShowPlugin plugin, SlideShowManager manager) {
        this.plugin = plugin;
        this.manager = manager;
        this.browser = new SlideBrowser(plugin, manager);
    }

    @EventHandler
    public void onInventoryClick(InventoryClickEvent event) {
        Inventory top = event.getView().getTopInventory();
        if (!(top.getHolder() instanceof SlideBrowserHolder holder)) {
            return;
        }
        event.setCancelled(true);
        if (!(event.getWhoClicked() instanceof Player player)) {
            return;
        }

        int slot = event.getRawSlot();
        if (slot < 0 || slot >= top.getSize()) {
            return;
        }
        if (slot == SlideBrowserHolder.CLOSE_SLOT) {
            player.closeInventory();
            return;
        }
        if (slot == SlideBrowserHolder.PREV_SLOT) {
            browser.open(player, holder.page() - 1);
            return;
        }
        if (slot == SlideBrowserHolder.NEXT_SLOT) {
            browser.open(player, holder.page() + 1);
            return;
        }
        if (slot == SlideBrowserHolder.WAND_SLOT) {
            player.getInventory().addItem(browser.itemFactory().createControlWand());
            player.sendMessage(ChatColor.GREEN + "Received slideshow controller. Right-click a screen for next, left-click for previous.");
            return;
        }
        if (slot == SlideBrowserHolder.RELOAD_SLOT) {
            manager.reload(player);
            browser.openWithDiscovery(player);
            return;
        }
        ItemStack clicked = event.getCurrentItem();
        if (pdcString(clicked, plugin.slideshowNameKey()).isEmpty()) {
            return;
        }
        player.getInventory().addItem(clicked.clone());
        player.closeInventory();
        player.sendMessage(ChatColor.GREEN + "Received slideshow item. Right-click a screen to play it there.");
    }

    @EventHandler
    public void onPlayerInteractEntity(PlayerInteractEntityEvent event) {
        if (!(event.getRightClicked() instanceof ItemFrame itemFrame)) {
            return;
        }
        ItemStack item = event.getPlayer().getInventory().getItem(event.getHand());
        Player player = event.getPlayer();

        if (isMenuItem(item)) {
            // Right-clicking an entity (e.g. an item frame) with the disc also opens the browser.
            event.setCancelled(true);
            browser.openWithDiscovery(player);
            return;
        }
        if (isWand(item)) {
            event.setCancelled(true);
            controlScreen(player, itemFrame, true);
            return;
        }

        String slideshowName = pdcString(item, plugin.slideshowNameKey()).orElse(null);
        if (slideshowName != null) {
            event.setCancelled(true);
            startSlideshowOnFrame(slideshowName, itemFrame, player);
            return;
        }

        // Legacy single-slide items keep their old projection behavior.
        String url = pdcString(item, plugin.slideUrlKey()).orElse(null);
        if (url == null) {
            return;
        }
        event.setCancelled(true);

        Optional<SlideShow> target = manager.findByFrame(itemFrame);
        if (target.isPresent()) {
            target.get().renderUrlToScreen(url, player);
            player.sendMessage(ChatColor.GREEN + "Projected slide to " + target.get().name() + ".");
            return;
        }
        manager.bridge().renderUrlToSingleFrame(url, itemFrame, player);
    }

    /** Left-clicking an item frame counts as damaging it; with the wand it means "previous slide". */
    @EventHandler
    public void onEntityDamageByEntity(EntityDamageByEntityEvent event) {
        if (!(event.getDamager() instanceof Player player)) {
            return;
        }
        if (isMenuItem(player.getInventory().getItemInMainHand())) {
            // Left-clicking an entity with the disc just cancels the hit; right-click opens the browser.
            event.setCancelled(true);
            return;
        }
        if (!(event.getEntity() instanceof ItemFrame itemFrame)) {
            return;
        }
        if (!isWand(player.getInventory().getItemInMainHand())) {
            return;
        }
        event.setCancelled(true);
        controlScreen(player, itemFrame, false);
    }

    /** Allows controlling a screen from a distance by clicking air/blocks while looking at it. */
    @EventHandler
    public void onPlayerInteract(PlayerInteractEvent event) {
        if (isMenuItem(event.getItem())) {
            // Cancel both clicks so the disc can't end up in a jukebox; right-click opens the browser.
            event.setCancelled(true);
            Action menuAction = event.getAction();
            if (menuAction == Action.RIGHT_CLICK_AIR || menuAction == Action.RIGHT_CLICK_BLOCK) {
                browser.openWithDiscovery(event.getPlayer());
            }
            return;
        }
        if (!isWand(event.getItem())) {
            return;
        }
        Action action = event.getAction();
        boolean forward = action == Action.RIGHT_CLICK_AIR || action == Action.RIGHT_CLICK_BLOCK;
        boolean backward = action == Action.LEFT_CLICK_AIR || action == Action.LEFT_CLICK_BLOCK;
        if (!forward && !backward) {
            return;
        }
        Entity target = event.getPlayer().getTargetEntity(WAND_RANGE);
        if (!(target instanceof ItemFrame itemFrame)) {
            return;
        }
        event.setCancelled(true);
        controlScreen(event.getPlayer(), itemFrame, forward);
    }

    private void controlScreen(Player player, ItemFrame itemFrame, boolean forward) {
        long now = System.currentTimeMillis();
        Long last = wandLastUse.get(player.getUniqueId());
        if (last != null && now - last < WAND_COOLDOWN_MILLIS) {
            return;
        }
        wandLastUse.put(player.getUniqueId(), now);

        Optional<SlideShow> slideShow = manager.findByFrame(itemFrame);
        if (slideShow.isEmpty()) {
            player.sendMessage(ChatColor.RED + "No slideshow is bound to this screen.");
            return;
        }
        if (forward) {
            slideShow.get().next();
        } else {
            slideShow.get().prev();
        }
    }

    private boolean isMenuItem(ItemStack item) {
        if (item == null || !item.hasItemMeta()) {
            return false;
        }
        ItemMeta meta = item.getItemMeta();
        return meta != null && meta.getPersistentDataContainer().has(plugin.menuItemKey(), PersistentDataType.BYTE);
    }

    private boolean isWand(ItemStack item) {
        if (item == null || !item.hasItemMeta()) {
            return false;
        }
        ItemMeta meta = item.getItemMeta();
        return meta != null && meta.getPersistentDataContainer().has(plugin.controlWandKey(), PersistentDataType.BYTE);
    }

    private void startSlideshowOnFrame(String slideshowName, ItemFrame itemFrame, Player player) {
        Optional<SlideShow> slideShow = manager.find(slideshowName);
        if (slideShow.isEmpty()) {
            player.sendMessage(ChatColor.RED + "Unknown slideshow: " + slideshowName + ". Run /slideshow reload or grab a new item.");
            return;
        }
        Optional<Screen> screen = manager.bridge().findScreenByFrame(itemFrame);
        if (screen.isEmpty()) {
            player.sendMessage(ChatColor.RED + "That item frame is not part of a MediaPlayer screen.");
            return;
        }
        SlideShow show = slideShow.get();
        if (!show.isCompatibleWithScreen(screen.get())) {
            player.sendMessage(ChatColor.RED + "Size mismatch: slideshow is "
                    + show.slideSizeString() + " but screen requires "
                    + show.screenSizeString(screen.get()) + ".");
            return;
        }
        manager.startOnScreen(show, screen.get(), player);
        player.sendMessage(ChatColor.GREEN + "Started slideshow " + show.name()
                + " on screen " + screen.get().getName() + ".");
    }

    private Optional<String> pdcString(ItemStack item, NamespacedKey key) {
        if (item == null || !item.hasItemMeta()) {
            return Optional.empty();
        }
        ItemMeta meta = item.getItemMeta();
        if (meta == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(meta.getPersistentDataContainer().get(key, PersistentDataType.STRING));
    }
}
