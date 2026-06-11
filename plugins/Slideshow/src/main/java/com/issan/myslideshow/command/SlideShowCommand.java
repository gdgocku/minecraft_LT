package com.issan.myslideshow.command;

import com.issan.myslideshow.MySlideshowPlugin;
import com.issan.myslideshow.gui.SlideBrowser;
import com.issan.myslideshow.slide.SlideShow;
import com.issan.myslideshow.slide.SlideShowManager;
import fr.xxathyx.mediaplayer.screen.Screen;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabCompleter;
import org.bukkit.entity.Entity;
import org.bukkit.entity.ItemFrame;
import org.bukkit.entity.Player;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

public final class SlideShowCommand implements CommandExecutor, TabCompleter {
    private static final List<String> SUBCOMMANDS = List.of("browse", "menu", "wand", "start", "stop", "next", "prev", "goto", "screen", "reload");

    private final MySlideshowPlugin plugin;
    private final SlideShowManager manager;
    private final SlideBrowser browser;

    public SlideShowCommand(MySlideshowPlugin plugin, SlideShowManager manager) {
        this.plugin = plugin;
        this.manager = manager;
        this.browser = new SlideBrowser(plugin, manager);
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0) {
            sendUsage(sender);
            return true;
        }

        String subcommand = args[0].toLowerCase(Locale.ROOT);
        switch (subcommand) {
            case "browse" -> browse(sender);
            case "menu" -> menu(sender);
            case "wand" -> wand(sender);
            case "start" -> withSlideShow(sender, args, SlideShow::start);
            case "stop" -> withSlideShow(sender, args, (slideShow, player) -> {
                slideShow.stop();
                sender.sendMessage(ChatColor.GREEN + "Stopped slideshow " + slideShow.name() + ".");
            });
            case "next" -> withSlideShow(sender, args, (slideShow, player) -> slideShow.next());
            case "prev" -> withSlideShow(sender, args, (slideShow, player) -> slideShow.prev());
            case "goto" -> gotoSlide(sender, args);
            case "screen" -> screen(sender, args);
            case "reload" -> reload(sender);
            default -> sendUsage(sender);
        }
        return true;
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        if (args.length == 1) {
            return filter(SUBCOMMANDS, args[0]);
        }
        if (args.length == 2 && List.of("start", "stop", "next", "prev", "goto", "screen").contains(args[0].toLowerCase(Locale.ROOT))) {
            return filter(manager.names(), args[1]);
        }
        return List.of();
    }

    private void browse(CommandSender sender) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "Only players can browse slideshows.");
            return;
        }
        browser.openWithDiscovery(player);
    }

    private void menu(CommandSender sender) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "Only players can receive the menu item.");
            return;
        }
        player.getInventory().addItem(browser.itemFactory().createMenuItem());
        player.sendMessage(ChatColor.GREEN + "Received slideshow menu disc. Right-click with it to open the list.");
    }

    private void wand(CommandSender sender) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "Only players can receive the controller.");
            return;
        }
        player.getInventory().addItem(browser.itemFactory().createControlWand());
        player.sendMessage(ChatColor.GREEN + "Received slideshow controller. Right-click a screen for next, left-click for previous.");
    }

    private void gotoSlide(CommandSender sender, String[] args) {
        if (args.length < 3) {
            sender.sendMessage(ChatColor.RED + "Usage: /slideshow goto <slideshow> <index>");
            return;
        }
        Optional<SlideShow> slideShow = manager.find(args[1]);
        if (slideShow.isEmpty()) {
            sender.sendMessage(ChatColor.RED + "Unknown slideshow: " + args[1]);
            return;
        }
        try {
            slideShow.get().gotoSlide(Integer.parseInt(args[2]));
        } catch (NumberFormatException exception) {
            sender.sendMessage(ChatColor.RED + "Index must be a number.");
        }
    }

    private void screen(CommandSender sender, String[] args) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "Only players can pick a screen.");
            return;
        }
        Optional<SlideShow> optional = args.length >= 2 ? manager.find(args[1]) : manager.first();
        if (optional.isEmpty()) {
            sender.sendMessage(ChatColor.RED + "No configured slideshow found.");
            return;
        }
        SlideShow slideShow = optional.get();

        ItemFrame frame = lookingAtFrame(player);
        if (frame == null) {
            player.sendMessage(ChatColor.RED + "Look at an item frame on the target screen, then run this command.");
            return;
        }
        Optional<Screen> screen = manager.bridge().findScreenByFrame(frame);
        if (screen.isEmpty()) {
            player.sendMessage(ChatColor.RED + "That item frame is not part of a MediaPlayer screen.");
            return;
        }
        slideShow.useScreen(screen.get());
        player.sendMessage(ChatColor.GREEN + "Slideshow " + slideShow.name() + " now targets screen "
                + screen.get().getName() + " (" + screen.get().getUUID() + ").");
    }

    private ItemFrame lookingAtFrame(Player player) {
        Entity target = player.getTargetEntity(8);
        if (target instanceof ItemFrame frame) {
            return frame;
        }
        return null;
    }

    private void reload(CommandSender sender) {
        manager.reload(sender instanceof Player player ? player : null);
        sender.sendMessage(ChatColor.GREEN + "Loaded " + manager.names().size() + " configured slideshow(s).");
    }

    private void withSlideShow(CommandSender sender, String[] args, SlideShowAction action) {
        if (args.length < 2) {
            sender.sendMessage(ChatColor.RED + "Usage: /slideshow " + args[0] + " <slideshow>");
            return;
        }
        Optional<SlideShow> slideShow = manager.find(args[1]);
        if (slideShow.isEmpty()) {
            sender.sendMessage(ChatColor.RED + "Unknown slideshow: " + args[1]);
            return;
        }
        action.run(slideShow.get(), sender instanceof Player player ? player : null);
    }

    private void sendUsage(CommandSender sender) {
        sender.sendMessage(ChatColor.YELLOW + "/slideshow browse " + ChatColor.GRAY + "(pick a slideshow item, then right-click a screen)");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow menu " + ChatColor.GRAY + "(get a menu disc: right-click to open the browser)");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow wand " + ChatColor.GRAY + "(controller stick: right-click=next, left-click=prev)");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow start <slideshow>");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow stop <slideshow>");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow next|prev <slideshow>");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow goto <slideshow> <index>");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow screen [slideshow] " + ChatColor.GRAY + "(look at the target screen's item frame)");
        sender.sendMessage(ChatColor.YELLOW + "/slideshow reload");
    }

    private List<String> filter(List<String> values, String prefix) {
        String normalized = prefix.toLowerCase(Locale.ROOT);
        List<String> result = new ArrayList<>();
        for (String value : values) {
            if (value.toLowerCase(Locale.ROOT).startsWith(normalized)) {
                result.add(value);
            }
        }
        return result;
    }

    @FunctionalInterface
    private interface SlideShowAction {
        void run(SlideShow slideShow, Player player);
    }
}
