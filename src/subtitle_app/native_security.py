"""Small version-pinned adapters for pywebview 6.2.1's native file-drop boundary."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit


def local_navigation(url: str, origin: str) -> bool:
    candidate, expected = urlsplit(url), urlsplit(origin)
    return (candidate.scheme, candidate.netloc) == (expected.scheme, expected.netloc) and candidate.path in {"", "/", "/index.html"} and not candidate.username and not candidate.password


class NativeDropPaths(list):
    """Only OS-issued files get a consumable grant, not arbitrary JS event fields."""
    def __init__(self, on_native_drop=None):
        super().__init__()
        self.issued = {}
        self.lock = threading.Lock()
        self.on_native_drop = on_native_drop

    def __iadd__(self, values):
        with self.lock:
            now = time.monotonic()
            self.issued = {p: t for p, t in self.issued.items() if now - t < 30}
            for name, path in values:
                self.issued[str(Path(unquote(path)).resolve())] = now
            super().__iadd__(values)
        if self.on_native_drop:
            self.on_native_drop([Path(unquote(path)).resolve() for _, path in values])
            self.clear()
        return self

    def consume(self, event):
        result = []
        with self.lock:
            for item in event.get("dataTransfer", {}).get("files", []):
                value = item.get("pywebviewFullPath")
                if not isinstance(value, str):
                    continue
                path = Path(value).resolve()
                issued = self.issued.pop(str(path), None)
                if issued is not None and time.monotonic() - issued < 30:
                    result.append(path)
        return result


def attach_native_security(window, origin, controller):
    import webview
    from webview.dom import _dnd_state
    paths = NativeDropPaths(controller.stage_drop)
    _dnd_state["paths"] = paths
    _dnd_state["num_listeners"] = 1
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["REMOTE_DEBUGGING_PORT"] = None

    def initialized(renderer):
        if sys.platform == "darwin":
            from webview.platforms.cocoa import BrowserView

            class JianLocalNavigationDelegate(BrowserView.BrowserDelegate):
                def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, handler):
                    handler(1 if local_navigation(str(action.request().URL()), origin) else 0)

            BrowserView.BrowserDelegate = JianLocalNavigationDelegate
        elif sys.platform == "win32" and renderer != "edgechromium":
            raise RuntimeError("简幕需要 Microsoft Edge WebView2，不能使用旧版 IE 内核")

    def before_show():
        if sys.platform == "win32":
            def guard(sender, args):
                if not local_navigation(str(args.Uri), origin):
                    args.Cancel = True
            window.native.browser.webview.NavigationStarting += guard

    window.events.initialized += initialized
    window.events.before_show += before_show
