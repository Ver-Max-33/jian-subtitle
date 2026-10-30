"""Check build/source integrity using only the Python standard library."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / p for p in ("package.json", "package-lock.json", "tsconfig.json", "index.html", "THIRD_PARTY.md", "scripts/build.mjs", "scripts/dependency-guard.mjs", "scripts/license-report.mjs")]
    paths.extend(p for folder in ("src", "public") for p in (ROOT / folder).rglob("*") if p.is_file())
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def outputs():
    paths = ("index.html", "assets/app.js", "assets/app.css", "fonts/NotoSansSC.ttf", "fonts/OFL.txt", "THIRD_PARTY_LICENSES.txt")
    return {p: digest(ROOT / "dist" / p) for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    proof = ROOT / "security/build-proof.json"
    if args.record:
        proof.parent.mkdir(exist_ok=True)
        proof.write_text(json.dumps({"builtAt": datetime.now(timezone.utc).isoformat(), "sources": sources(), "outputs": outputs()}, indent=2), encoding="utf-8")
        print("已记录构建资源与源码哈希；这不是安全证明或发布签名。")
        return
    saved = json.loads(proof.read_text(encoding="utf-8"))
    if saved["sources"] != sources() or saved["outputs"] != outputs():
        raise SystemExit("前端构建过期或被修改，已拒绝打包。")
    print("前端源码、锁文件和构建产物一致。")


if __name__ == "__main__":
    main()
