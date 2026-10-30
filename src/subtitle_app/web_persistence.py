"""Authenticated application-owned state; never accept a project-provided manifest path."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4


class TrustedStore:
    def __init__(self, root: Path):
        self.root = root
        key_path = root / "state.key"
        try:
            with key_path.open("xb") as stream:
                os.chmod(key_path, 0o600)
                stream.write(secrets.token_bytes(32))
                stream.flush(); os.fsync(stream.fileno())
        except FileExistsError:
            pass
        self.key = key_path.read_bytes()
        if len(self.key) != 32:
            raise ValueError("应用状态密钥损坏，请保留数据并联系支持")

    def save(self, name: str, payload):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        signature = hmac.new(self.key, (name + "\n" + encoded).encode(), hashlib.sha256).hexdigest()
        destination = self.root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"payload": encoded, "signature": signature}, stream, ensure_ascii=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, name: str, default=None):
        path = self.root / name
        if not path.exists():
            return default
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("应用状态文件过大")
        data = json.loads(path.read_text(encoding="utf-8"))
        encoded = data["payload"]
        expected = hmac.new(self.key, (name + "\n" + encoded).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, data.get("signature", "")):
            raise ValueError("应用状态校验失败，未读取其中的文件授权")
        return json.loads(encoded)
