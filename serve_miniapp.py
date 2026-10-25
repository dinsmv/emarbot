#!/usr/bin/env python3
"""
HTTP-сервер для Telegram Mini App + раздача файлов из resources/.

Запуск локально:
  python3 serve_miniapp.py

На VPS (порт 8765):
  MINIAPP_PORT=8765 python3 serve_miniapp.py

⚠️  Telegram Mini App в продакшене требует HTTPS.
    Настройте nginx + Let's Encrypt и проксируйте на этот порт.
    MINIAPP_URL=https://materials.emarcapital.pro  (или ваш домен/IP с SSL)
"""

import logging
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).parent
MINIAPP_DIR = ROOT / "miniapp"
RESOURCES_DIR = ROOT / "resources"
PORT = int(__import__("os").getenv("MINIAPP_PORT", "8765"))
CHUNK_SIZE = 1024 * 1024  # 1 MB
MAX_LARGE_STREAMS = 2       # не больше 2 одновременных видео на 1 GB RAM
LARGE_FILE = 5 * 1024 * 1024
_file_slots = threading.Semaphore(MAX_LARGE_STREAMS)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(MINIAPP_DIR), **kwargs)

    def end_headers(self):
        # Локальная разработка: браузер не должен кэшировать HTML/JS/CSS/JSON
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self._route(send_body=True):
            return
        return super().do_GET()

    def do_HEAD(self):
        if self._route(send_body=False):
            return
        f = super().send_head()
        if f:
            f.close()

    def _route(self, send_body: bool) -> bool:
        path_only = self.path.split("?", 1)[0]
        if path_only == "/resources.json":
            self._serve_file(RESOURCES_DIR / "resources.json", "application/json", send_body)
            return True
        if path_only == "/faq.json":
            self._serve_file(RESOURCES_DIR / "faq.json", "application/json", send_body)
            return True
        if path_only.startswith("/files/"):
            rel = unquote(path_only[len("/files/"):])
            filepath = RESOURCES_DIR / "files" / rel
            if filepath.is_file():
                self._serve_file(filepath, self._guess_type(filepath), send_body)
                return True
            self.send_error(404)
            return True
        if path_only in ("/", "/index.html"):
            self.path = "/index.html"
        return False

    def _guess_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        return {
            ".pdf": "application/pdf",
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".mp3": "audio/mpeg",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(ext, "application/octet-stream")

    def _parse_range(self, file_size: int):
        header = self.headers.get("Range")
        if not header or not header.startswith("bytes="):
            return None
        spec = header[6:].strip()
        if "," in spec:
            return None
        if spec.startswith("-"):
            suffix = int(spec[1:])
            start = max(0, file_size - suffix)
            return start, file_size - 1
        start_s, _, end_s = spec.partition("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            return None
        return start, end

    def _send_common_headers(self, content_type: str, inline: bool = False):
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Accept-Ranges", "bytes")
        if inline:
            self.send_header("Content-Disposition", "inline")

    def _stream_file(self, path: Path, start: int, length: int):
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_file(self, path: Path, content_type: str, send_body: bool = True):
        if not path.is_file():
            logging.warning("Файл не найден: %s", path)
            self.send_error(404, f"File not found: {path.name}")
            return

        file_size = path.stat().st_size
        is_large = file_size > LARGE_FILE
        slot_ok = True
        if is_large:
            slot_ok = _file_slots.acquire(timeout=60)
            if not slot_ok:
                self.send_error(503, "Server busy — try again")
                return

        try:
            inline = content_type.startswith("video/") or content_type.startswith("audio/")
            byte_range = self._parse_range(file_size)

            if byte_range:
                start, end = byte_range
                length = end - start + 1
                self.send_response(206)
                self._send_common_headers(content_type, inline)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.end_headers()
                if send_body:
                    self._stream_file(path, start, length)
                return

            self.send_response(200)
            self._send_common_headers(content_type, inline)
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            if send_body:
                self._stream_file(path, 0, file_size)
        finally:
            if is_large and slot_ok:
                _file_slots.release()

    def log_message(self, fmt, *args):
        print(f"[miniapp] {args[0]}")


def main():
    if not MINIAPP_DIR.exists():
        print(f"❌ Нет папки {MINIAPP_DIR}")
        return
    RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
    (RESOURCES_DIR / "files").mkdir(exist_ok=True)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🌐 Mini App: http://0.0.0.0:{PORT}/")
    print(f"   Каталог:  http://0.0.0.0:{PORT}/resources.json")
    print("   Для Telegram укажите HTTPS-URL в MINIAPP_URL (.env)")
    server.serve_forever()


if __name__ == "__main__":
    main()
