from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

from .web_controller import WebController
from .web_server import AppServer


def default_data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "JianSubtitle"
    return Path.home() / "Library/Application Support/JianSubtitle" if sys.platform == "darwin" else Path.home() / ".local/share/jian-subtitle"


def prefers_dark(platform=sys.platform) -> bool:
    """Whether the system asks apps for dark mode. The page follows it by itself; this only colours the window."""
    try:
        if platform == "win32":
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if platform == "darwin":
            # Light mode has no value, so `defaults` exits non-zero.
            result = subprocess.run(["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True, timeout=2, check=True)
            return result.stdout.strip() == "Dark"
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def window_background(dark: bool) -> str:
    """The canvas colour of the matching theme, so the window never flashes white before the page paints."""
    return "#1E1E1E" if dark else "#F5F5F5"


def frontend_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "frontend"
    return Path(__file__).resolve().parents[2] / "frontend/dist"


def utf8_console():
    """Print Chinese on any console. A frozen app ignores PYTHONUTF8; an English Windows console is cp1252."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    utf8_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="受保护的浏览器预览（无原生文件对话框）")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--import", dest="images", type=Path, nargs="*")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--smoke-test", action="store_true", help="验证资源与核心渲染后退出")
    args = parser.parse_args(argv)
    if not (frontend_dir() / "index.html").is_file():
        parser.error("前端尚未构建，请先按 README 构建 frontend")
    if args.smoke_test:
        from PIL import Image
        from .models import StyleSettings
        from .render_service import RenderService
        import webview
        assert RenderService().render(Image.new("RGB", (64, 64)), [], StyleSettings()).size == (64, 64)
        print("简幕资源与 Python 渲染检查通过", flush=True)
        return 0
    controller = WebController(args.data_dir)
    if args.images:
        controller.import_paths(args.images)
    server = AppServer(controller, frontend_dir(), args.port)
    if args.browser:
        server.start()
        print(server.url, flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            server.stop()
        return 0
    import webview

    window = None
    allow_close = False

    def native(action, p):
        nonlocal allow_close
        if action == "choose_images":
            return window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=("图片 (*.jpg;*.jpeg;*.png;*.webp;*.bmp)",))
        if action in {"choose_folder", "choose_output", "relocate"}:
            chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
            if not chosen:
                return None
            root = Path(chosen[0]).resolve()
            if action == "choose_folder":
                iterator = root.rglob("*") if p.get("recursive") is True else root.iterdir()
                return [str(path) for path in sorted(iterator) if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"} and not any(path.resolve().is_relative_to(output) for output in controller.outputs.values())]
            return str(root)
        if action in {"open_project", "import_speakers"}:
            types = ("字幕项目 (*.json)",) if action == "open_project" else ("说话人列表 (*.txt)",)
            chosen = window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
            return chosen[0] if chosen else None
        if action in {"save_as", "export_log"}:
            chosen = window.create_file_dialog(webview.FileDialog.SAVE, save_filename="字幕项目.subtitle-project.json" if action == "save_as" else "导出记录.json", file_types=("JSON (*.json)",))
            return chosen[0] if chosen else None
        if action == "open_output":
            path = str(Path(p["path"]).resolve())
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        if action == "open_source":
            path = Path(p["path"]).resolve()
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            elif sys.platform == "win32":
                os.startfile(str(path.parent))
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        if action == "open_releases":
            import webbrowser
            from .updater import RELEASES_URL
            webbrowser.open(RELEASES_URL)
        if action == "close_app":
            allow_close = True
            window.destroy()

    controller.native = native
    server.start()
    # Installed Windows builds look for a signed update in the background (updater.py); others do nothing.
    controller.updater.start()
    # No injected js_api: all calls use the small authenticated HTTP command protocol.
    # Remote pages cannot inherit a privileged generic Python object.
    window = webview.create_window("简幕", server.url, width=1440, height=900, min_size=(960, 680), background_color=window_background(prefers_dark()), text_select=True)
    from .native_security import attach_native_security
    attach_native_security(window, server.url, controller)

    def closing():
        if allow_close:
            return True
        controller.close_requested = True
        return False

    window.events.closing += closing
    try:
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=False, private_mode=True)
    except Exception as error:
        if sys.platform != "win32":
            raise
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "简幕未能启动。请确认已安装 Microsoft WebView2 Runtime。\n\n" + str(error)[:1000], "简幕启动失败", 0x10)
        return 1
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
