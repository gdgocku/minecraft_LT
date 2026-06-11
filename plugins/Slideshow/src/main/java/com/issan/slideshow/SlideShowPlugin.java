package com.issan.slideshow;

import com.issan.slideshow.command.SlideShowCommand;
import com.issan.slideshow.listener.SlideShowListener;
import com.issan.slideshow.mediaplayer.MediaPlayerBridge;
import com.issan.slideshow.slide.SlideShowManager;
import org.bukkit.NamespacedKey;
import org.bukkit.command.PluginCommand;
import org.bukkit.plugin.java.JavaPlugin;

public final class SlideShowPlugin extends JavaPlugin {
    private NamespacedKey slideUrlKey;
    private NamespacedKey slideIndexKey;
    private NamespacedKey slideshowNameKey;
    private NamespacedKey controlWandKey;
    private NamespacedKey menuItemKey;
    private SlideShowManager slideShowManager;
    private MediaPlayerBridge mediaPlayerBridge;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        slideUrlKey = new NamespacedKey(this, "slide_url");
        slideIndexKey = new NamespacedKey(this, "slide_index");
        slideshowNameKey = new NamespacedKey(this, "slideshow_name");
        controlWandKey = new NamespacedKey(this, "control_wand");
        menuItemKey = new NamespacedKey(this, "menu_item");
        mediaPlayerBridge = new MediaPlayerBridge(this);
        slideShowManager = new SlideShowManager(this, mediaPlayerBridge);
        slideShowManager.loadConfiguredSlideshows();

        SlideShowCommand command = new SlideShowCommand(this, slideShowManager);
        PluginCommand slideshowCommand = getCommand("slideshow");
        if (slideshowCommand != null) {
            slideshowCommand.setExecutor(command);
            slideshowCommand.setTabCompleter(command);
        }

        getServer().getPluginManager().registerEvents(new SlideShowListener(this, slideShowManager), this);
    }

    @Override
    public void onDisable() {
        if (slideShowManager != null) {
            slideShowManager.shutdown();
        }
    }

    public NamespacedKey slideUrlKey() {
        return slideUrlKey;
    }

    public NamespacedKey slideIndexKey() {
        return slideIndexKey;
    }

    public NamespacedKey slideshowNameKey() {
        return slideshowNameKey;
    }

    public NamespacedKey controlWandKey() {
        return controlWandKey;
    }

    public NamespacedKey menuItemKey() {
        return menuItemKey;
    }
}
