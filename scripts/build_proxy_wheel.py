"""Package the fully reviewed 2014 pure-Python dependency without executing setup.py.

Only the exact official PyPI sdist is accepted. No network, import, dynamic build
backend, egg hook, arbitrary archive extraction or dependency execution is used.
"""
import base64
import hashlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path


def main():
    archive = Path(sys.argv[1])
    output = Path(sys.argv[2])
    expected = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit("proxy_tools source hash mismatch")
    with tarfile.open(archive, "r:gz") as source:
        module = source.extractfile("proxy_tools-0.1.0/proxy_tools/__init__.py").read()
        metadata = source.extractfile("proxy_tools-0.1.0/PKG-INFO").read()
    info = "proxy_tools-0.1.0.dist-info"
    files = {"proxy_tools/__init__.py": module, f"{info}/METADATA": metadata, f"{info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: jian-reviewed-pure-python-packager\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
    files[f"{info}/LICENSE.txt"] = (Path(__file__).resolve().parents[1] / "packaging/third-party/proxy_tools-LICENSE.txt").read_bytes()
    records = []
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        records.append(f"{name},sha256={digest},{len(data)}")
    records.append(f"{info}/RECORD,,")
    files[f"{info}/RECORD"] = ("\n".join(records) + "\n").encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "proxy_tools-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, data in files.items():
            entry = zipfile.ZipInfo(name, date_time=(2014, 1, 1, 0, 0, 0))
            wheel.writestr(entry, data)
    print(destination)
    print(hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
