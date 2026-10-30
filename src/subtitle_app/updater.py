"""In-app updates for the installed Windows build.

Each GitHub release carries `update.json`: a payload naming the installer, its size and SHA-256, plus an
Ed25519 signature over that payload. The signing key stays on the maintainer's machine (scripts/release.py),
so neither a GitHub token nor a tampered release asset can push code to users. The app trusts only the
public key compiled into it, downloads over HTTPS, checks size and hash, and checks the hash again
right before it starts the installer.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__, ed25519
from .update_key import PUBLIC_KEY

REPOSITORY = "Ver-Max-33/jian-subtitle"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
MANIFEST_URL = f"{RELEASES_URL}/latest/download/update.json"
APP = "jian-subtitle"
MANIFEST_LIMIT = 64 * 1024
INSTALLER_LIMIT = 1024 * 1024 * 1024
NOTES_LIMIT = 4000
_VERSION = re.compile(r"(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})")


class UpdateError(Exception):
    pass


def parse_version(text) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise UpdateError("版本号格式不对")
    return tuple(int(part) for part in match.groups())


def installer_name(version: str) -> str:
    return f"JianSubtitle-{version}-win-x64-setup.exe"


def make_payload(version: str, size: int, sha256: str, notes: str) -> str:
    """The signed text; scripts/release.py makes it, read_manifest checks it."""
    return json.dumps({"app": APP, "version": version, "file": installer_name(version), "size": size, "sha256": sha256, "notes": notes}, ensure_ascii=False, sort_keys=True)


def envelope(payload: str, signature: bytes) -> bytes:
    return json.dumps({"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}).encode("utf-8")


def read_manifest(raw: bytes, public_key: bytes) -> dict:
    """Verify the signature first, then accept only the exact fields and formats we expect."""
    try:
        outer = json.loads(raw)
        payload, signature = outer["payload"], base64.b64decode(outer["signature"], validate=True)
        if not isinstance(payload, str):
            raise TypeError
    except (ValueError, TypeError, KeyError, binascii.Error) as error:
        raise UpdateError("更新信息无法读取") from error
    if not ed25519.verify(public_key, payload.encode("utf-8"), signature):
        raise UpdateError("更新信息的签名无效，已停止更新")
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise TypeError
        version, file, size, sha256, notes = data["version"], data["file"], data["size"], data["sha256"], data["notes"]
    except (ValueError, TypeError, KeyError) as error:
        raise UpdateError("更新信息无法读取") from error
    parse_version(version)
    if (data.get("app") != APP or file != installer_name(version) or type(size) is not int or not 0 < size <= INSTALLER_LIMIT
            or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256) or not isinstance(notes, str) or len(notes) > NOTES_LIMIT):
        raise UpdateError("更新信息不符合要求")
    return {"version": version, "file": file, "size": size, "sha256": sha256, "notes": notes}


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "拒绝跳转到非 HTTPS 地址", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpsOnly, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def secure_urlopen(url: str, timeout: float = 30):
    """HTTPS with certificate checks; redirects may not leave HTTPS."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError("只允许 HTTPS 地址")
    return _opener.open(urllib.request.Request(url, headers={"User-Agent": f"JianSubtitle/{__version__}"}), timeout=timeout)


def launch_installer(path: Path):
    """Inno Setup with a progress window only; /RELAUNCH=1 starts 简幕 again when it is done (packaging/installer.iss)."""
    if sys.platform != "win32":
        raise UpdateError("只能在 Windows 上安装更新")
    subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1"], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _message(error: Exception) -> str:
    if isinstance(error, UpdateError):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        return f"GitHub 返回 {error.code}，请稍后再试"
    if isinstance(error, urllib.error.URLError):
        return f"无法连接 GitHub：{error.reason}"
    return f"下载中断：{error}"


class Updater:
    """States: idle → checking → latest | available → downloading → ready → installing; failed on any error."""

    def __init__(self, data_dir: Path, *, current: str = __version__, public_key: str = PUBLIC_KEY, supported: bool | None = None, urlopen=None, launch=None):
        self.folder = Path(data_dir) / "updates"
        self.settings = Path(data_dir) / "update-settings.json"
        self.current = current
        try:
            self.key = base64.b64decode(public_key, validate=True)
        except binascii.Error:
            self.key = b""
        if supported is None:
            supported = bool(getattr(sys, "frozen", False)) and sys.platform == "win32"
        self.supported = supported and len(self.key) == 32
        self.urlopen = urlopen or secure_urlopen
        self.launch = launch or launch_installer
        self.lock = threading.Lock()
        self.state, self.release, self.received, self.error, self.path = "idle", None, 0, None, None
        try:
            self.auto = json.loads(self.settings.read_text(encoding="utf-8")).get("auto") is not False
        except (OSError, ValueError, AttributeError):
            self.auto = True
        if self.supported:
            self._clean()

    def snapshot(self) -> dict:
        with self.lock:
            release = self.release or {}
            return {"current": self.current, "supported": self.supported, "auto": self.auto, "state": self.state, "version": release.get("version"),
                    "notes": release.get("notes"), "received": self.received, "total": release.get("size", 0), "error": self.error}

    def start(self):
        if self.supported and self.auto:
            self.check(manual=False)

    def set_auto(self, enabled: bool):
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.settings.write_text(json.dumps({"auto": enabled}), encoding="utf-8")
        with self.lock:
            self.auto = enabled

    def check(self, manual: bool = True):
        if not self.supported:
            raise UpdateError("开发版本不检查更新")
        with self.lock:
            if self.state in {"checking", "downloading", "installing"}:
                return
            self.state, self.error = "checking", None
        threading.Thread(target=self._check, args=(manual,), name="subtitle-update-check", daemon=True).start()

    def download(self):
        with self.lock:
            if self.state in {"downloading", "ready", "installing"}:
                return
            if not self.release or self.state not in {"available", "failed"}:
                raise UpdateError("没有可下载的更新")
            self.state, self.error, self.received = "downloading", None, 0
            release = self.release
        threading.Thread(target=self._download, args=(release,), name="subtitle-update-download", daemon=True).start()

    def install(self):
        with self.lock:
            if self.state != "ready":
                raise UpdateError("更新还没有下载完成")
            path, release = self.path, self.release
        # The file sat on disk since the download: check it again right before running it.
        if _sha256(path) != release["sha256"]:
            path.unlink(missing_ok=True)
            self._set(state="failed", error="安装包校验失败，已删除，请重新下载")
            raise UpdateError("安装包校验失败，已删除，请重新下载")
        try:
            self.launch(path)
        except (OSError, UpdateError) as error:
            self._set(state="failed", error=f"无法启动安装程序：{error}")
            raise UpdateError(f"无法启动安装程序：{error}") from error
        self._set(state="installing")

    def _set(self, **values):
        with self.lock:
            for name, value in values.items():
                setattr(self, name, value)

    def _check(self, manual: bool):
        try:
            with self.urlopen(MANIFEST_URL, timeout=20) as response:
                raw = response.read(MANIFEST_LIMIT + 1)
            if len(raw) > MANIFEST_LIMIT:
                raise UpdateError("更新信息过大")
            release = read_manifest(raw, self.key)
            if parse_version(release["version"]) > parse_version(self.current):
                self._set(state="available", release=release, received=0)
            else:
                self._set(state="latest", release=None)
        except urllib.error.HTTPError as error:
            if error.code == 404:  # The latest release has no signed update information.
                self._set(state="latest", release=None)
            else:
                self._set(state="failed" if manual else "idle", error=_message(error) if manual else None)
        except (UpdateError, OSError, http.client.HTTPException, ValueError) as error:
            self._set(state="failed" if manual else "idle", error=_message(error) if manual else None)

    def _download(self, release: dict):
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self.folder / release["file"]
        partial = self.folder / (release["file"] + ".part")
        try:
            if target.is_file() and _sha256(target) == release["sha256"]:
                self._set(state="ready", path=target, received=release["size"])
                return
            digest, received = hashlib.sha256(), 0
            url = f"{RELEASES_URL}/download/v{release['version']}/{release['file']}"
            with self.urlopen(url, timeout=30) as response, partial.open("wb") as output:
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    received += len(chunk)
                    if received > release["size"]:
                        raise UpdateError("安装包校验失败（大小不符），已删除")
                    digest.update(chunk)
                    output.write(chunk)
                    self._set(received=received)
            if received != release["size"]:
                raise UpdateError("安装包校验失败（大小不符），已删除")
            if digest.hexdigest() != release["sha256"]:
                raise UpdateError("安装包校验失败（SHA-256 不符），已删除")
            os.replace(partial, target)
            self._set(state="ready", path=target)
        except (UpdateError, OSError, http.client.HTTPException, ValueError) as error:
            partial.unlink(missing_ok=True)
            self._set(state="failed", error=_message(error))

    def _clean(self):
        """Drop partial downloads and installers that are not newer than this build."""
        if not self.folder.is_dir():
            return
        current = parse_version(self.current)
        for file in self.folder.iterdir():
            match = re.fullmatch(r"JianSubtitle-(.+)-win-x64-setup\.exe", file.name)
            try:
                stale = not match or parse_version(match.group(1)) <= current
            except UpdateError:
                stale = True
            if stale and file.is_file():
                file.unlink(missing_ok=True)
