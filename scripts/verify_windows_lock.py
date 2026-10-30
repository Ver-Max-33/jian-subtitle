"""Check downloaded wheels and Windows dependency closure without importing them."""
import hashlib
import json
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
environment = {
    "implementation_name": "cpython", "implementation_version": "3.11.7",
    "os_name": "nt", "platform_machine": "AMD64", "platform_python_implementation": "CPython",
    "platform_release": "10", "platform_system": "Windows", "platform_version": "10.0.22631",
    "python_full_version": "3.11.7", "python_version": "3.11", "sys_platform": "win32", "extra": "",
}
lock = (ROOT / "requirements-win.lock").read_text()
records = {}
for wheel in sorted((ROOT / ".build-wheels/win311").glob("*.whl")):
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if f"--hash=sha256:{sha}" not in lock:
        raise SystemExit(f"Hash not in lock: {wheel.name}")
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
    records[canonicalize_name(metadata['Name'])] = {"version": metadata['Version'], "sha256": sha, "file": wheel.name, "requirements": metadata.get_all('Requires-Dist') or []}
for name, record in records.items():
    for line in record["requirements"]:
        required = Requirement(line)
        if required.marker and not required.marker.evaluate(environment):
            continue
        dependency = records.get(canonicalize_name(required.name))
        if not dependency or dependency['version'] not in required.specifier:
            raise SystemExit(f"Windows dependency missing or incompatible: {name} -> {required}")
report = {"target": "CPython 3.11 / Windows x64", "status": "passed", "boundary": "Wheel hashes and metadata only; Windows execution and installer acceptance still required.", "packages": records}
(ROOT / "packaging/third-party/windows-wheel-check.json").write_text(json.dumps(report, indent=2), encoding='utf-8')
print(f"{len(records)} Windows wheels: hashes and dependency closure passed; no Windows binary executed.")
