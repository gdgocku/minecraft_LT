package com.issan.myslideshow.gui;

import org.bukkit.inventory.Inventory;
import org.bukkit.inventory.InventoryHolder;

public final class SlideBrowserHolder implements InventoryHolder {
    public static final int PAGE_SIZE = 45;
    public static final int PREV_SLOT = 45;
    public static final int CLOSE_SLOT = 49;
    public static final int WAND_SLOT = 51;
    public static final int RELOAD_SLOT = 52;
    public static final int NEXT_SLOT = 53;

    private final int page;

    public SlideBrowserHolder(int page) {
        this.page = page;
    }

    public int page() {
        return page;
    }

    @Override
    public Inventory getInventory() {
        return null;
    }
}
