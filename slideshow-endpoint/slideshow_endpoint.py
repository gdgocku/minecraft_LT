#!/usr/bin/env python3
"""
Small HTTP endpoint for MySlideshow.

It serves:
- /slides.json as [{"url": "...", "index": 0}, ...] (default deck = files directly in slides/)
- /images/<filename> for PNG/JPG/GIF/BMP image files in the slides directory
- /decks.json listing every deck and its endpoint URL
- /decks/<deck>/slides.json and /decks/<deck>/images/<filename> for each
  subdirectory of the slides directory, so every configured slideshow in the
  plugin can point at its own deck.

The generated image URLs include ?v=<mtime> because MySlideshow detects updates by
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


UI_PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MySlideshow Uploader</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #2c3e50; color: #ecf0f1; }
  header { padding: 16px 24px; background: #1b2735; font-size: 18px; }
  main { padding: 24px; max-width: 900px; margin: 0 auto; }
  #deckbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  #deckbar select, #deckbar input { border: 0; border-radius: 6px; padding: 8px 10px; font: inherit; }
  #deckbar button { background: #2980b9; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
  #titlebar { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; }
  #titlebar input { flex: 1; max-width: 360px; border: 0; border-radius: 6px; padding: 7px 10px; font: inherit; font-size: 15px; }
  #titlebar button { background: #27ae60; color: #fff; border: 0; border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 14px; }
  #titlebar label { color: #95a5a6; font-size: 13px; white-space: nowrap; }
  #toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; font-size: 14px; }
  #toolbar input { width: 56px; border: 0; border-radius: 6px; padding: 6px 8px; font: inherit; }
  #toolbar button { background: #8e44ad; color: #fff; border: 0; border-radius: 6px; padding: 8px 14px; cursor: pointer; }
  #toolbar button:disabled { opacity: .55; cursor: wait; }
  #toolbar button.danger { background: #c0392b; }
  #endpoint { display: block; margin-bottom: 16px; font-size: 13px; color: #95a5a6; word-break: break-all; }
  #endpoint code { color: #ecf0f1; background: #1b2735; padding: 2px 6px; border-radius: 4px; cursor: pointer; }
  #drop { border: 2px dashed #7f8c8d; border-radius: 12px; padding: 40px; text-align: center;
          color: #bdc3c7; cursor: pointer; transition: .15s; }
  #drop.over { border-color: #27ae60; background: rgba(39,174,96,.12); color: #ecf0f1; }
  #google { display: flex; gap: 8px; margin-top: 16px; }
  #google input { flex: 1; min-width: 0; border: 0; border-radius: 6px; padding: 10px 12px; font: inherit; }
  #google button { background: #27ae60; color: #fff; border: 0; border-radius: 6px; padding: 0 16px; cursor: pointer; }
  #google button:disabled { opacity: .55; cursor: wait; }
  #grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin-top: 24px; }
  .card { background: #34495e; border-radius: 8px; overflow: hidden; }
  .card img { width: 100%; height: 110px; object-fit: cover; display: block; background: #222; }
  .card .meta { padding: 6px 8px; font-size: 12px; display: flex; justify-content: space-between; align-items: center; }
  .card button { background: #c0392b; color: #fff; border: 0; border-radius: 4px; padding: 3px 8px; cursor: pointer; }
  .idx { color: #95a5a6; }
  .hint { color: #95a5a6; font-size: 13px; margin-top: 8px; }
</style>
</head>
<body>
<header>MySlideshow Uploader</header>
<main>
  <div id="deckbar">
    <label for="deck">スライドショー:</label>
    <select id="deck"><option value="">(デフォルト)</option></select>
    <input id="new-title" placeholder="タイトルを入力して作成" style="min-width:180px">
    <button id="add-deck" type="button">作成</button>
  </div>
  <div id="titlebar">
    <label for="deck-title">タイトル変更:</label>
    <input id="deck-title" type="text" maxlength="128" placeholder="タイトルを編集">
    <button id="save-title" type="button">保存</button>
  </div>
  <span id="endpoint">endpoint-url: <code id="endpoint-url" title="クリックでコピー"></code></span>
  <div id="toolbar">
    <label>スクリーン 横<input id="blocks-w" type="number" min="1" max="64" value="16">×
    縦<input id="blocks-h" type="number" min="1" max="64" value="9">ブロック</label>
    <span id="pixels" class="hint"></span>
    <button id="resize-deck" type="button">全画像をこのサイズに変換</button>
    <button id="delete-deck" type="button" class="danger">デッキを削除</button>
  </div>
  <div id="drop">画像 / PDF をここにドラッグ＆ドロップ、またはクリックして選択<br>
    <span class="hint">PNG / JPG / GIF / BMP / PDF（複数可）。アップロード時にスクリーンサイズへ自動変換されます。</span>
  </div>
  <label style="display:inline-flex;align-items:center;gap:6px;margin-top:10px;font-size:13px;color:#95a5a6;cursor:pointer">
    <input id="no-resize" type="checkbox"> 自動リサイズしない（原寸で保存）
  </label>
  <form id="google">
    <input id="google-url" type="url" placeholder="Google スライドのURLを貼り付け">
    <button type="submit">取り込み</button>
  </form>
  <div id="status" class="hint"></div>
  <input id="file" type="file" accept="image/*,application/pdf" multiple hidden>
  <div id="grid"></div>
</main>
<script>
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const grid = document.getElementById('grid');
const googleForm = document.getElementById('google');
const googleUrl = document.getElementById('google-url');
const googleButton = googleForm.querySelector('button');
const deckSelect = document.getElementById('deck');
const newTitleInput = document.getElementById('new-title');
const addDeckButton = document.getElementById('add-deck');
const endpointUrl = document.getElementById('endpoint-url');
const statusEl = document.getElementById('status');
const deckTitleInput = document.getElementById('deck-title');
const saveTitleButton = document.getElementById('save-title');
const blocksW = document.getElementById('blocks-w');
const blocksH = document.getElementById('blocks-h');
const pixelsEl = document.getElementById('pixels');
const resizeButton = document.getElementById('resize-deck');
const deleteDeckButton = document.getElementById('delete-deck');
const noResizeCheck = document.getElementById('no-resize');

let deck = '';

function deckPrefix() {
  return deck ? `/decks/${encodeURIComponent(deck)}` : '';
}

function updateEndpoint() {
  endpointUrl.textContent = location.origin + deckPrefix() + '/slides.json';
}

let decksCache = [];

async function loadDecks() {
  decksCache = await (await fetch('/decks.json')).json();
  deckSelect.innerHTML = '';
  for (const d of decksCache) {
    const option = document.createElement('option');
    option.value = d.name;
    const label = d.title || (d.name || '(デフォルト)');
    option.textContent = `${label} (${d.slides}枚)`;
    if (d.title && d.name) option.textContent = `${d.title} [${d.name}] (${d.slides}枚)`;
    deckSelect.appendChild(option);
  }
  if (![...deckSelect.options].some(o => o.value === deck)) deck = '';
  deckSelect.value = deck;
  updateEndpoint();
  updateTitleField();
}

function updateTitleField() {
  const current = decksCache.find(d => d.name === deck);
  deckTitleInput.value = current ? (current.title || '') : '';
}

saveTitleButton.onclick = async () => {
  const title = deckTitleInput.value.trim();
  const res = await fetch('/set-deck-meta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck, title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    statusEl.textContent = `失敗: ${err.error || res.status}`;
    return;
  }
  statusEl.textContent = `タイトルを保存しました: ${title || '(なし)'}`;
  await loadDecks();
};

async function refresh() {
  const slides = await (await fetch(deckPrefix() + '/slides.json')).json();
  grid.innerHTML = '';
  for (const s of slides) {
    const name = decodeURIComponent(new URL(s.url, location.href).pathname.replace(/^.*\\/images\\//, ''));
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `<img src="${s.url}" alt="${name}">
      <div class="meta"><span><span class="idx">#${s.index}</span> ${name}</span>
      <button>削除</button></div>`;
    card.querySelector('button').onclick = () => remove(name);
    grid.appendChild(card);
  }
}

async function upload(files) {
  for (const f of files) {
    statusEl.textContent = `アップロード中: ${f.name}${f.name.toLowerCase().endsWith('.pdf') ? '（PDF変換中…）' : ''}`;
    const res = await fetch('/upload', {
      method: 'POST',
      headers: {
        'X-Filename': encodeURIComponent(f.name),
        'X-Deck': encodeURIComponent(deck),
        'X-No-Resize': noResizeCheck.checked ? '1' : '0',
      },
      body: f,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      statusEl.textContent = `失敗: ${f.name} — ${err.error || res.status}`;
      await new Promise(r => setTimeout(r, 2500));
    } else {
      const body = await res.json();
      if (body.pages) statusEl.textContent = `${f.name}: ${body.pages} ページを追加`;
    }
  }
  if (!statusEl.textContent.startsWith('失敗')) statusEl.textContent = '';
  loadDecks();
  refresh();
}

async function remove(name) {
  if (!confirm(name + ' を削除しますか？')) return;
  await fetch('/delete', {
    method: 'POST',
    headers: { 'X-Filename': encodeURIComponent(name), 'X-Deck': encodeURIComponent(deck) },
  });
  loadDecks();
  refresh();
}

googleForm.onsubmit = async e => {
  e.preventDefault();
  const url = googleUrl.value.trim();
  if (!url) return;
  googleButton.disabled = true;
  statusEl.textContent = 'Google スライドをPDFとして取得中…';
  const res = await fetch('/import-google-slides', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, deck }),
  });
  googleButton.disabled = false;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    statusEl.textContent = `失敗: ${err.error || res.status}`;
    return;
  }
  const body = await res.json();
  statusEl.textContent = `${body.pages || 0} ページを追加`;
  googleUrl.value = '';
  loadDecks();
  refresh();
};

function titleToId(title) {
  // Normalize Unicode, strip diacritics, collapse non-alphanum to hyphens.
  const ascii = title.normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const slug = ascii.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (slug) return slug;
  // Fallback: base36 hash of the raw title for fully CJK strings.
  let h = 0;
  for (let i = 0; i < title.length; i++) h = (Math.imul(31, h) + title.charCodeAt(i)) >>> 0;
  return 'deck-' + h.toString(36);
}

addDeckButton.onclick = async () => {
  const title = newTitleInput.value.trim();
  if (!title) return;
  const name = titleToId(title);
  // Save title immediately via set-deck-meta (also creates the dir on first upload).
  const res = await fetch('/set-deck-meta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck: name, title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    statusEl.textContent = `失敗: ${err.error || res.status}`;
    return;
  }
  deck = name;
  newTitleInput.value = '';
  statusEl.textContent = 'デッキはファイルを最初にアップロードしたときに作成されます。';
  await loadDecks();
  deckSelect.value = deck;
  updateEndpoint();
  updateTitleField();
  refresh();
};

function targetPixels() {
  const w = Math.max(1, parseInt(blocksW.value, 10) || 0) * 128;
  const h = Math.max(1, parseInt(blocksH.value, 10) || 0) * 128;
  return { w, h };
}

function updatePixels() {
  const { w, h } = targetPixels();
  pixelsEl.textContent = `= ${w}×${h}px`;
  try { localStorage.setItem('screenBlocks', JSON.stringify([blocksW.value, blocksH.value])); } catch {}
}

try {
  const saved = JSON.parse(localStorage.getItem('screenBlocks') || 'null');
  if (saved) { blocksW.value = saved[0]; blocksH.value = saved[1]; }
} catch {}
blocksW.oninput = updatePixels;
blocksH.oninput = updatePixels;
updatePixels();

resizeButton.onclick = async () => {
  const { w, h } = targetPixels();
  const label = deck || '(デフォルト)';
  if (!confirm(`デッキ ${label} の全画像を ${w}×${h}px に変換します（元画像は上書き）。以後のアップロードもこのサイズに自動変換されます。よろしいですか？`)) return;
  resizeButton.disabled = true;
  statusEl.textContent = '変換中…';
  // Save screen size to meta first so future uploads use the same size.
  await fetch('/set-deck-meta', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck, title: deckTitleInput.value.trim(), screen_width: w, screen_height: h }),
  });
  const res = await fetch('/resize-deck', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck, width: w, height: h }),
  });
  resizeButton.disabled = false;
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    statusEl.textContent = `失敗: ${err.error || res.status}`;
    return;
  }
  const body = await res.json();
  statusEl.textContent = `${body.resized.length} 枚を ${w}×${h}px に変換しました。以後のアップロードも自動変換されます。`;
  refresh();
};

deleteDeckButton.onclick = async () => {
  const label = deck || '(デフォルト)';
  if (!confirm(`デッキ ${label} のスライドをすべて削除します。よろしいですか？`)) return;
  const res = await fetch('/delete-deck', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deck }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    statusEl.textContent = `失敗: ${err.error || res.status}`;
    return;
  }
  statusEl.textContent = `デッキ ${label} を削除しました`;
  deck = '';
  await loadDecks();
  refresh();
};

deckSelect.onchange = () => {
  deck = deckSelect.value;
  statusEl.textContent = '';
  updateEndpoint();
  updateTitleField();
  refresh();
};

endpointUrl.onclick = async () => {
  try {
    await navigator.clipboard.writeText(endpointUrl.textContent);
    statusEl.textContent = 'endpoint-url をコピーしました';
  } catch { /* clipboard unavailable */ }
};

drop.onclick = () => fileInput.click();
fileInput.onchange = () => upload(fileInput.files);
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); upload(e.dataTransfer.files); };
loadDecks().then(refresh);
</script>
</body>
</html>
"""


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
    host = handler.headers.get("Host")
    if host:
        return f"http://{host}"
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
        headers={"User-Agent": "MySlideshowEndpoint/1.0"},
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
        payload = UI_PAGE.encode("utf-8")
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
    parser = argparse.ArgumentParser(description="Serve MySlideshow JSON and image files.")
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
