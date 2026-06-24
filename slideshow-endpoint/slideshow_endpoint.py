#!/usr/bin/env python3
"""
Small HTTP endpoint for SlideShow.

It serves:
- /slides.json as [{"url": "...", "index": 0}, ...] (default deck = files directly in slides/)
- /images/<filename> for PNG/JPG/GIF/BMP image files in the slides directory
- /decks.json listing every deck and its endpoint URL
- /decks/<deck>/slides.json and /decks/<deck>/images/<filename> for each
  subdirectory of the slides directory, so every configured slideshow in the
  plugin can point at its own deck.

The generated image URLs include ?v=<mtime> because SlideShow detects updates by
comparing URL strings.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote, urlparse

try:
    from PIL import Image
except ImportError:
    Image = None


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
DEFAULT_SLIDES_DIR = Path("slides")
DEFAULT_PORT = 8765
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_IMPORT_JSON_BYTES = 16 * 1024
MAX_RESIZE_DIMENSION = 8192
META_FILENAME = "meta.json"
MAX_TITLE_LEN = 128
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
DECK_NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
DECK_PATH_RE = re.compile(r"^/decks/([^/]+)(/.*)?$")
GOOGLE_SLIDES_ID_RE = re.compile(r"/presentation/d/([A-Za-z0-9_-]+)")
PDFTOPPM = shutil.which("pdftoppm")
UI_PAGE_PATH = Path(__file__).resolve().parent / "static" / "index.html"


@dataclass(frozen=True)
class SlideFile:
    path: Path
    index: int


def discover_slides(deck_dir: Path) -> list[SlideFile]:
    if not deck_dir.is_dir():
        return []
    files = [
        path
        for path in deck_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    files.sort(key=slide_sort_key)
    return [SlideFile(path=path, index=i) for i, path in enumerate(files)]


def read_deck_meta(deck_dir: Path) -> dict[str, str]:
    meta_path = deck_dir / META_FILENAME
    try:
        raw = json.loads(meta_path.read_text("utf-8"))
        if isinstance(raw, dict):
            return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_deck_meta(deck_dir: Path, meta: dict[str, str]) -> None:
    (deck_dir / META_FILENAME).write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def discover_decks(slides_dir: Path) -> list[Path]:
    return sorted(
        (path for path in slides_dir.iterdir() if path.is_dir() and DECK_NAME_RE.fullmatch(path.name)),
        key=lambda path: path.name.lower(),
    )


def slide_sort_key(path: Path) -> tuple[int, int | str, str]:
    match = re.match(r"^(\d+)", path.stem)
    if match:
        return (0, int(match.group(1)), path.name.lower())
    return (1, path.name.lower(), path.name.lower())


def build_slide_json(
    handler: BaseHTTPRequestHandler,
    deck_dir: Path,
    base_url: str | None,
    url_prefix: str,
) -> list[dict[str, object]]:
    origin = base_url.rstrip("/") if base_url else request_origin(handler)
    slides = []
    for slide in discover_slides(deck_dir):
        stat = slide.path.stat()
        filename = quote(slide.path.name)
        slides.append(
            {
                "url": f"{origin}{url_prefix}/images/{filename}?v={int(stat.st_mtime)}",
                "index": slide.index,
            }
        )
    return slides


def request_origin(handler: BaseHTTPRequestHandler) -> str:
    scheme = handler.headers.get("X-Forwarded-Proto", "http")
    host = handler.headers.get("Host")
    if host:
        return f"{scheme}://{host}"
    server = handler.server
    host_name = server.server_address[0]
    if host_name in {"", "0.0.0.0", "::"}:
        host_name = "127.0.0.1"
    return f"http://{host_name}:{server.server_address[1]}"


def split_deck_path(request_path: str) -> tuple[str | None, str]:
    """Split /decks/<deck>/... into (deck, remainder). Returns (None, path) otherwise."""
    match = DECK_PATH_RE.match(request_path)
    if match is None:
        return None, request_path
    return unquote(match.group(1)), match.group(2) or "/"


def safe_image_path(deck_dir: Path, request_path: str) -> Path | None:
    prefix = "/images/"
    if not request_path.startswith(prefix):
        return None
    name = unquote(request_path[len(prefix) :])
    if "/" in name or "\\" in name:
        return None
    path = (deck_dir / name).resolve()
    root = deck_dir.resolve()
    if root != path.parent or path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return path


def safe_upload_name(raw: str) -> str | None:
    name = unquote(raw).strip().replace("\\", "/")
    name = posixpath.basename(name)
    if not name or name in {".", ".."}:
        return None
    if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    cleaned = SAFE_NAME_RE.sub("_", name)
    return cleaned or None


def pdf_stem(raw: str) -> str | None:
    name = posixpath.basename(unquote(raw).strip().replace("\\", "/"))
    if not name or Path(name).suffix.lower() != ".pdf":
        return None
    stem = SAFE_NAME_RE.sub("_", Path(name).stem)
    return stem or None


def google_slides_export_url(raw_url: str) -> tuple[str, str] | None:
    parsed = urlparse(raw_url.strip())
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com":
        return None
    match = GOOGLE_SLIDES_ID_RE.search(parsed.path)
    if match is None:
        return None
    slide_id = match.group(1)
    return f"https://docs.google.com/presentation/d/{slide_id}/export/pdf", slide_id


def download_google_slides_pdf(raw_url: str) -> tuple[bytes, str, str]:
    export = google_slides_export_url(raw_url)
    if export is None:
        raise ValueError("Google Slides URL must be https://docs.google.com/presentation/d/...")
    export_url, slide_id = export
    request = urllib.request.Request(
        export_url,
        headers={"User-Agent": "SlideShowEndpoint/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        data = response.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("Downloaded PDF is too large")
    if not data.startswith(b"%PDF") and "pdf" not in content_type:
        raise ValueError("Google Slides did not return a PDF. Make sure anyone with the link can view it.")
    return data, slide_id, export_url


def google_slides_stem(slide_id: str) -> str:
    return "google-slides-" + SAFE_NAME_RE.sub("_", slide_id[:16])


def resize_deck_images(deck_dir: Path, width: int, height: int) -> list[str]:
    """Resize every image in the deck to exactly width x height (aspect kept,
    black letterbox), saving as PNG. Returns the resized file names."""
    resized_names = []
    for slide in discover_slides(deck_dir):
        with Image.open(slide.path) as source:
            rgb = source.convert("RGB")
        if rgb.size == (width, height) and slide.path.suffix.lower() == ".png":
            continue
        scale = min(width / rgb.width, height / rgb.height)
        new_size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        fitted = rgb.resize(new_size, Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(fitted, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
        target = slide.path.with_suffix(".png")
        canvas.save(target, "PNG")
        if target != slide.path:
            slide.path.unlink()
        resized_names.append(target.name)
    return resized_names


def convert_pdf(data: bytes, stem: str, deck_dir: Path, dpi: int) -> list[str]:
    """Render each PDF page to deck_dir/<stem>-NNN.png. Returns saved names."""
    # Remove any previous pages from the same PDF so re-uploads don't duplicate.
    for old in deck_dir.glob(f"{stem}-*.png"):
        if re.fullmatch(rf"{re.escape(stem)}-\d+\.png", old.name):
            old.unlink()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_pdf = Path(tmp) / "in.pdf"
        tmp_pdf.write_bytes(data)
        out_prefix = Path(tmp) / "page"
        subprocess.run(
            [PDFTOPPM, "-png", "-r", str(dpi), str(tmp_pdf), str(out_prefix)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        pages = sorted(Path(tmp).glob("page-*.png"))
        saved = []
        for i, page in enumerate(pages, start=1):
            name = f"{stem}-{i:03d}.png"
            shutil.copyfile(page, deck_dir / name)
            saved.append(name)
        return saved


class SlideRequestHandler(BaseHTTPRequestHandler):
    slides_dir: Path
    base_url: str | None
    pdf_dpi: int = 96

    def resolve_deck_dir(self, raw_deck: str, create: bool = False) -> Path | None:
        """Map a deck name to its directory. Empty name means the default deck (slides_dir)."""
        deck = unquote(raw_deck or "").strip()
        if not deck:
            return self.slides_dir
        if not DECK_NAME_RE.fullmatch(deck):
            return None
        path = self.slides_dir / deck
        if path.resolve().parent != self.slides_dir.resolve():
            return None
        if create:
            path.mkdir(parents=True, exist_ok=True)
        elif not path.is_dir():
            return None
        return path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        clean_path = posixpath.normpath(parsed.path)
        if parsed.path.endswith("/") and clean_path != "/":
            clean_path += "/"

        if clean_path in {"/", "/ui", "/index.html"}:
            self.send_ui()
            return

        if clean_path in {"/decks", "/decks.json"}:
            self.send_decks_json()
            return

        if clean_path in {"/slides", "/slides.json"}:
            self.send_slides_json(self.slides_dir, "")
            return

        deck, sub_path = split_deck_path(clean_path)
        if deck is not None:
            deck_dir = self.resolve_deck_dir(deck)
            if deck_dir is None or deck_dir == self.slides_dir:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown deck")
                return
            if sub_path in {"/slides", "/slides.json"}:
                self.send_slides_json(deck_dir, f"/decks/{quote(deck_dir.name)}")
                return
            image_path = safe_image_path(deck_dir, sub_path)
            if image_path is not None:
                self.send_image(image_path)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        image_path = safe_image_path(self.slides_dir, clean_path)
        if image_path is not None:
            self.send_image(image_path)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        clean_path = posixpath.normpath(parsed.path)
        if clean_path == "/upload":
            self.handle_upload()
            return
        if clean_path == "/import-google-slides":
            self.handle_google_slides_import()
            return
        if clean_path == "/delete":
            self.handle_delete()
            return
        if clean_path == "/resize-deck":
            self.handle_resize_deck()
            return
        if clean_path == "/delete-deck":
            self.handle_delete_deck()
            return
        if clean_path == "/set-deck-meta":
            self.handle_set_deck_meta()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_IMPORT_JSON_BYTES:
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return body if isinstance(body, dict) else None

    def handle_resize_deck(self) -> None:
        if Image is None:
            self.send_json_error(HTTPStatus.NOT_IMPLEMENTED, "Pillow is not installed on the server")
            return
        body = self.read_json_body()
        if body is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Resize request must be JSON")
            return
        deck_dir = self.resolve_deck_dir(body.get("deck") if isinstance(body.get("deck"), str) else "")
        if deck_dir is None:
            self.send_json_error(HTTPStatus.NOT_FOUND, "Unknown deck")
            return
        width = body.get("width")
        height = body.get("height")
        if (
            not isinstance(width, int) or not isinstance(height, int)
            or not 1 <= width <= MAX_RESIZE_DIMENSION or not 1 <= height <= MAX_RESIZE_DIMENSION
        ):
            self.send_json_error(HTTPStatus.BAD_REQUEST, f"width/height must be 1..{MAX_RESIZE_DIMENSION}")
            return
        try:
            resized = resize_deck_images(deck_dir, width, height)
        except OSError as exc:
            self.send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, f"Resize failed: {exc}")
            return
        self.send_json({"resized": resized, "width": width, "height": height})

    def handle_delete_deck(self) -> None:
        body = self.read_json_body()
        if body is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Delete request must be JSON")
            return
        deck_dir = self.resolve_deck_dir(body.get("deck") if isinstance(body.get("deck"), str) else "")
        if deck_dir is None:
            self.send_json_error(HTTPStatus.NOT_FOUND, "Unknown deck")
            return
        if deck_dir == self.slides_dir:
            # The default deck is the slides root: only clear its images, keep subdecks.
            for slide in discover_slides(deck_dir):
                slide.path.unlink()
            self.send_json({"deleted": "", "cleared": True})
            return
        shutil.rmtree(deck_dir)
        self.send_json({"deleted": deck_dir.name})

    def handle_set_deck_meta(self) -> None:
        body = self.read_json_body()
        if body is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Request must be JSON")
            return
        deck_dir = self.resolve_deck_dir(body.get("deck") if isinstance(body.get("deck"), str) else "", create=True)
        if deck_dir is None:
            self.send_json_error(HTTPStatus.NOT_FOUND, "Unknown deck")
            return
        title = body.get("title", "")
        if not isinstance(title, str) or len(title) > MAX_TITLE_LEN:
            self.send_json_error(HTTPStatus.BAD_REQUEST, f"title must be a string of at most {MAX_TITLE_LEN} chars")
            return
        meta = read_deck_meta(deck_dir)
        meta["title"] = title.strip()
        for size_key in ("screen_width", "screen_height"):
            val = body.get(size_key)
            if isinstance(val, int) and 1 <= val <= MAX_RESIZE_DIMENSION:
                meta[size_key] = str(val)
        write_deck_meta(deck_dir, meta)
        self.send_json({"deck": body.get("deck", ""), "title": meta["title"]})

    def handle_upload(self) -> None:
        deck_dir = self.resolve_deck_dir(self.headers.get("X-Deck", ""), create=True)
        if deck_dir is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid deck name")
            return
        raw_name = self.headers.get("X-Filename", "")
        length = int(self.headers.get("Content-Length", "0") or "0")
        is_pdf = unquote(raw_name).strip().lower().endswith(".pdf")
        limit = MAX_PDF_BYTES if is_pdf else MAX_UPLOAD_BYTES
        if length <= 0 or length > limit:
            self.send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Bad upload size")
            return

        if is_pdf:
            self.handle_pdf_upload(raw_name, length, deck_dir)
            return

        name = safe_upload_name(raw_name)
        if name is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid or unsupported filename")
            return
        data = self.rfile.read(length)
        target = (deck_dir / name).resolve()
        if target.parent != deck_dir.resolve():
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid path")
            return
        target.write_bytes(data)
        skip_resize = self.headers.get("X-No-Resize", "0") == "1"
        if not skip_resize and Image is not None:
            w, h = self._deck_screen_size(deck_dir)
            target = self._resize_to_png(target, w, h)
        self.send_json({"saved": target.name})

    def handle_pdf_upload(self, raw_name: str, length: int, deck_dir: Path) -> None:
        if PDFTOPPM is None:
            self.send_json_error(HTTPStatus.NOT_IMPLEMENTED, "pdftoppm not installed on server")
            return
        stem = pdf_stem(raw_name)
        if stem is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid PDF filename")
            return
        data = self.rfile.read(length)
        try:
            saved = convert_pdf(data, stem, deck_dir, self.pdf_dpi)
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", "replace")[:200] if exc.stderr else "conversion failed"
            self.send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, f"PDF conversion failed: {detail}")
            return
        except subprocess.TimeoutExpired:
            self.send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, "PDF conversion timed out")
            return
        skip_resize = self.headers.get("X-No-Resize", "0") == "1"
        if not skip_resize and Image is not None:
            w, h = self._deck_screen_size(deck_dir)
            resized = []
            for name in saved:
                resized.append(self._resize_to_png(deck_dir / name, w, h).name)
            saved = resized
        self.send_json({"saved": saved, "pages": len(saved)})

    def handle_google_slides_import(self) -> None:
        if PDFTOPPM is None:
            self.send_json_error(HTTPStatus.NOT_IMPLEMENTED, "pdftoppm not installed on server")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > MAX_IMPORT_JSON_BYTES:
            self.send_json_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Bad import request size")
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Import request must be JSON")
            return
        raw_url = body.get("url") if isinstance(body, dict) else None
        if not isinstance(raw_url, str) or not raw_url.strip():
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Google Slides URL is required")
            return
        raw_deck = body.get("deck") if isinstance(body, dict) else ""
        deck_dir = self.resolve_deck_dir(raw_deck if isinstance(raw_deck, str) else "", create=True)
        if deck_dir is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid deck name")
            return
        skip_resize = body.get("no_resize") is True
        try:
            data, slide_id, export_url = download_google_slides_pdf(raw_url)
            saved = convert_pdf(data, google_slides_stem(slide_id), deck_dir, self.pdf_dpi)
        except ValueError as exc:
            self.send_json_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except urllib.error.HTTPError as exc:
            self.send_json_error(HTTPStatus.BAD_GATEWAY, f"Google Slides returned HTTP {exc.code}")
            return
        except urllib.error.URLError as exc:
            self.send_json_error(HTTPStatus.BAD_GATEWAY, f"Failed to download Google Slides: {exc.reason}")
            return
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", "replace")[:200] if exc.stderr else "conversion failed"
            self.send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, f"PDF conversion failed: {detail}")
            return
        except subprocess.TimeoutExpired:
            self.send_json_error(HTTPStatus.UNPROCESSABLE_ENTITY, "PDF conversion timed out")
            return
        if not skip_resize and Image is not None:
            w, h = self._deck_screen_size(deck_dir)
            saved = [self._resize_to_png(deck_dir / name, w, h).name for name in saved]
        self.send_json({"saved": saved, "pages": len(saved), "source": export_url})

    def _deck_screen_size(self, deck_dir: Path) -> tuple[int, int]:
        """Return the target pixel size for this deck from meta.json, falling back to 16×9 blocks."""
        meta = read_deck_meta(deck_dir)
        w = meta.get("screen_width")
        h = meta.get("screen_height")
        try:
            return int(w), int(h)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 16 * 128, 9 * 128

    def _resize_to_png(self, path: Path, width: int, height: int) -> Path:
        """Resize path to width×height with black letterbox, save as PNG. Removes original if renamed."""
        with Image.open(path) as src:
            rgb = src.convert("RGB")
        if rgb.size == (width, height) and path.suffix.lower() == ".png":
            return path
        scale = min(width / rgb.width, height / rgb.height)
        new_size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        fitted = rgb.resize(new_size, Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(fitted, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
        target = path.with_suffix(".png")
        canvas.save(target, "PNG")
        if target != path:
            path.unlink()
        return target

    def handle_delete(self) -> None:
        deck_dir = self.resolve_deck_dir(self.headers.get("X-Deck", ""))
        if deck_dir is None:
            self.send_json_error(HTTPStatus.NOT_FOUND, "Unknown deck")
            return
        name = safe_upload_name(self.headers.get("X-Filename", ""))
        if name is None:
            self.send_json_error(HTTPStatus.BAD_REQUEST, "Invalid filename")
            return
        target = (deck_dir / name).resolve()
        if target.parent != deck_dir.resolve() or not target.is_file():
            self.send_json_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        target.unlink()
        self.send_json({"deleted": name})

    def send_ui(self) -> None:
        try:
            payload = UI_PAGE_PATH.read_bytes()
        except OSError:
            self.send_json_error(HTTPStatus.INTERNAL_SERVER_ERROR, "UI page not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, obj: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_json_error(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        clean_path = posixpath.normpath(parsed.path)
        deck, sub_path = split_deck_path(clean_path)
        deck_dir = self.slides_dir
        if deck is not None:
            resolved = self.resolve_deck_dir(deck)
            if resolved is None or resolved == self.slides_dir:
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown deck")
                return
            deck_dir = resolved
            clean_path = sub_path

        if clean_path in {"/slides", "/slides.json", "/decks", "/decks.json"}:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        image_path = safe_image_path(deck_dir, clean_path)
        if image_path is not None and image_path.exists():
            self.send_image_headers(image_path)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def send_slides_json(self, deck_dir: Path, url_prefix: str) -> None:
        payload = json.dumps(
            build_slide_json(self, deck_dir, self.base_url, url_prefix),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_decks_json(self) -> None:
        origin = self.base_url.rstrip("/") if self.base_url else request_origin(self)
        default_meta = read_deck_meta(self.slides_dir)
        decks: list[dict[str, object]] = [
            {
                "name": "",
                "title": default_meta.get("title", ""),
                "endpoint": f"{origin}/slides.json",
                "slides": len(discover_slides(self.slides_dir)),
            }
        ]
        for deck_dir in discover_decks(self.slides_dir):
            meta = read_deck_meta(deck_dir)
            decks.append(
                {
                    "name": deck_dir.name,
                    "title": meta.get("title", ""),
                    "endpoint": f"{origin}/decks/{quote(deck_dir.name)}/slides.json",
                    "slides": len(discover_slides(deck_dir)),
                }
            )
        self.send_json(decks)

    def send_image(self, image_path: Path) -> None:
        if not image_path.exists() or not image_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Image not found")
            return
        self.send_image_headers(image_path)
        with image_path.open("rb") as image:
            self.wfile.write(image.read())

    def send_image_headers(self, image_path: Path) -> None:
        stat = image_path.stat()
        content_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(stat.st_size))
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {self.address_string()} {fmt % args}\n")


def make_handler(slides_dir: Path, base_url: str | None, pdf_dpi: int) -> type[SlideRequestHandler]:
    class ConfiguredSlideRequestHandler(SlideRequestHandler):
        pass

    ConfiguredSlideRequestHandler.slides_dir = slides_dir
    ConfiguredSlideRequestHandler.base_url = base_url
    ConfiguredSlideRequestHandler.pdf_dpi = pdf_dpi
    return ConfiguredSlideRequestHandler


def ensure_sample_slides(slides_dir: Path, force: bool) -> None:
    slides_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        ("00-redstone.png", (194, 54, 43), (44, 62, 80)),
        ("01-lantern.png", (243, 156, 18), (33, 97, 140)),
        ("02-emerald.png", (39, 174, 96), (52, 73, 94)),
    ]
    for name, left, right in samples:
        path = slides_dir / name
        if path.exists() and not force:
            continue
        path.write_bytes(make_png(512, 256, left, right))


def make_png(width: int, height: int, left: tuple[int, int, int], right: tuple[int, int, int]) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            ratio = x / max(1, width - 1)
            shade = 0.85 + 0.15 * ((x // 32 + y // 32) % 2)
            color = tuple(int((left[i] * (1 - ratio) + right[i] * ratio) * shade) for i in range(3))
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        png_chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    ).join([b"\x89PNG\r\n\x1a\n", b""])


def png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(data, checksum)
    return len(data).to_bytes(4, "big") + kind + data + checksum.to_bytes(4, "big")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve SlideShow JSON and image files.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address. Default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Bind port. Default: {DEFAULT_PORT}")
    parser.add_argument("--slides-dir", type=Path, default=DEFAULT_SLIDES_DIR, help="Directory containing slide images.")
    parser.add_argument("--base-url", default=os.environ.get("SLIDESHOW_BASE_URL"), help="Public URL prefix, e.g. http://192.168.1.10:8765")
    parser.add_argument("--pdf-dpi", type=int, default=96, help="Render DPI for PDF uploads. Default: 96")
    parser.add_argument("--init-samples", action="store_true", help="Create sample PNG slides if missing.")
    parser.add_argument("--force-samples", action="store_true", help="Overwrite sample PNG slides.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    slides_dir = args.slides_dir.resolve()
    slides_dir.mkdir(parents=True, exist_ok=True)
    if args.init_samples or args.force_samples:
        ensure_sample_slides(slides_dir, args.force_samples)

    handler = make_handler(slides_dir, args.base_url, args.pdf_dpi)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)

    def shutdown(_signum: int, _frame: object) -> None:
        # shutdown() blocks until serve_forever() exits, so it must not run on
        # the main thread (where signal handlers execute) or it deadlocks.
        threading.Thread(target=httpd.shutdown).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    endpoint = args.base_url.rstrip("/") if args.base_url else f"http://{args.host}:{args.port}"
    print(f"Serving {slides_dir} at {endpoint}/slides.json (decks: {endpoint}/decks.json)", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
