from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .web_controller import WebController


class LimitedHTTPServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class AppServer:
    """Loopback-only, session-authenticated API; no filesystem or shell bridge."""

    def __init__(self, controller: WebController, frontend: Path, port: int = 0):
        self.controller = controller
        self.frontend = frontend.resolve()
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "JianSubtitle"

            def setup(self):
                self.request.settimeout(10)
                super().setup()

            def log_message(self, *args):
                pass

            def _valid_host(self):
                return self.headers.get("Host") == owner.authority

            def _authorized(self):
                origin = self.headers.get("Origin")
                token = self.headers.get("X-Jian-Token", "")
                return self._valid_host() and (origin is None or origin == owner.origin) and token.isascii() and hmac.compare_digest(token, owner.token)

            def _send(self, status, body: bytes, content_type="application/json; charset=utf-8"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; connect-src 'self'; font-src 'self'; base-uri 'none'; object-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'")
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                if not self._valid_host():
                    return self._send(403, b'{}')
                path = urlsplit(self.path).path
                if path.startswith("/media/"):
                    if not self._authorized():
                        return self._send(403, b'{}')
                    token = path.removeprefix("/media/")
                    body = owner.controller.media_bytes(token)
                    kind = "image/jpeg" if body and body[:3] == b"\xff\xd8\xff" else "image/png" if body else "application/json"
                    return self._send(200 if body else 404, body or b'{}', kind)
                if path.startswith("/caption-fonts/"):
                    if not self._authorized():
                        return self._send(403, b'{}')
                    font = owner.controller.caption_font_bytes(path.removeprefix("/caption-fonts/"))
                    return self._send(200, *font) if font else self._send(404, b'{}')
                paths = {"/": "index.html", "/index.html": "index.html", "/assets/app.js": "assets/app.js", "/assets/app.css": "assets/app.css", "/fonts/NotoSansSC.ttf": "fonts/NotoSansSC.ttf"}
                if path not in paths:
                    return self._send(404, b'{}')
                target = owner.frontend / paths[path]
                if not target.is_file() or not target.resolve().is_relative_to(owner.frontend):
                    return self._send(404, b'{}')
                return self._send(200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream")

            def do_POST(self):
                if not self._authorized():
                    return self._send(403, b'{}')
                if self.path != "/api":
                    return self._send(404, b'{}')
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 1024 * 1024 or self.headers.get("Content-Type") != "application/json":
                        return self._send(413, b'{}')
                    self.connection.settimeout(10)
                    request = json.loads(self.rfile.read(length))
                    result = owner.controller.dispatch(request)
                except (ValueError, OSError):
                    return self._send(400, b'{}')
                except Exception:
                    result = {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "操作失败，请重试；输入仍保留在当前页面", "affectedIds": []}}
                self._send(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())

        self.http = LimitedHTTPServer(("127.0.0.1", port), Handler)
        self.http.daemon_threads = True
        self.authority = f"127.0.0.1:{self.http.server_port}"
        self.origin = f"http://{self.authority}"
        self.url = f"{self.origin}/#session={self.token}"

    def start(self):
        threading.Thread(target=self.http.serve_forever, name="subtitle-loopback", daemon=True).start()

    def stop(self):
        self.http.shutdown()
        self.http.server_close()
