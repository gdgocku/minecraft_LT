# Minecraft server setup

This directory is prepared as a Paper 26.1.2 server.

## Files

- `paper.jar`: Paper 26.1.2 build 69
- `runtime/jdk-25.0.3+9/`: local Java 25 runtime used by `start.sh`
- `plugins/MediaPlayer.jar`
- `plugins/MySlideshow-0.1.0-dev.jar`
- `start.sh`: starts the Minecraft server
- `start-slides.sh`: starts the MySlideshow endpoint server

## First launch

Minecraft requires accepting the EULA before the server can fully start.

Run once:

```bash
./start.sh
```

Then open `eula.txt`, read the linked EULA, and set:

```text
eula=true
```

After that:

```bash
./start.sh
```

## Slide endpoint

Run this in another terminal:

```bash
./start-slides.sh
```

Use this in `plugins/MySlideshow/config.yml` after the plugin creates it:

```yaml
endpoint-url: "http://127.0.0.1:8765/slides.json"
```

If the Paper server and endpoint are on different machines, replace `127.0.0.1` with the endpoint machine's LAN IP.
