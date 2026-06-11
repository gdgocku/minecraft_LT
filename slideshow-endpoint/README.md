# MySlideshow endpoint server

This small Python server provides the endpoint expected by the MySlideshow plugin:

```json
[{"url":"http://127.0.0.1:8765/images/00-redstone.png?v=123","index":0}]
```

## Run

```bash
python3 slideshow_endpoint.py --host 0.0.0.0 --port 8765 --slides-dir slides --init-samples
```

Then set the plugin config:

```yaml
endpoint-base-url: "http://127.0.0.1:8765"
```

If Minecraft connects from another machine, use that machine's reachable IP address instead of `127.0.0.1`.

## Decks (multiple slideshows)

Each subdirectory of `slides/` is served as its own deck, so every slideshow in
the plugin config can point at a different one:

```text
slides/            -> http://127.0.0.1:8765/slides.json            (default deck)
slides/lt-2026/    -> http://127.0.0.1:8765/decks/lt-2026/slides.json
slides/opening/    -> http://127.0.0.1:8765/decks/opening/slides.json
```

`GET /decks.json` lists all decks with their endpoint URLs and slide counts.

The plugin discovers decks automatically: with `endpoint-base-url` set in the
plugin config, `/slideshow browse` fetches `<base>/decks.json` and shows every
deck (the deck of files directly in `slides/` appears as `default`). No
per-slideshow config entry is needed.

```yaml
endpoint-base-url: "http://127.0.0.1:8765"
slideshows: {}
```

In the uploader UI (`http://127.0.0.1:8765/`), pick or create a deck at the
top; uploads, deletes, and Google Slides imports apply to the selected deck,
and the matching `endpoint-url` is shown for copy-paste. Deck names may use
letters, digits, `.`, `_`, `-`. A new deck's directory is created on its first
upload.

The toolbar can also resize every image in the selected deck to the screen's
exact pixel size (blocks × 128, e.g. a 16×7 screen needs 2048×896px — the
plugin rejects size mismatches). Images keep their aspect ratio and are
letterboxed in black. The deck delete button removes the whole deck; on the
default deck it clears the images in `slides/` but keeps the subdecks.

## Temporary ngrok tunnel

Install your ngrok authtoken once:

```bash
./runtime/ngrok config add-authtoken YOUR_NGROK_TOKEN
```

Then run:

```bash
./start-ngrok-slides.sh
```

Use the shown `https://...ngrok...` URL plus `/slides.json` as the plugin `endpoint-url`.

## Google Slides import

Open the uploader UI at `http://127.0.0.1:8765/`, paste a Google Slides URL, and click import. The server converts URLs like:

```text
https://docs.google.com/presentation/d/<SLIDE_ID>/edit
```

to:

```text
https://docs.google.com/presentation/d/<SLIDE_ID>/export/pdf
```

Then it downloads the PDF and renders each page into `slides/google-slides-<id>-NNN.png`. The deck must be shared so anyone with the link can view it, otherwise Google returns a login/error page instead of a PDF.

## Slides

Put PNG/JPG/GIF/BMP files in `slides/`.

Files are ordered by leading number first, then by filename:

```text
slides/
  00-title.png
  01-rules.png
  02-map.png
```

The JSON response uses sequential indexes starting at `0`. Image URLs include `?v=<mtime>`, so replacing an image file changes the URL and lets the plugin detect updates by URL list difference.
