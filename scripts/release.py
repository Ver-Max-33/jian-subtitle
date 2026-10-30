"""Release helper for 简幕. Run on the maintainer's machine (CI only runs `check`).

  python scripts/release.py version 0.3.0     write the version into every file that carries it
  python scripts/release.py keygen            once: make the passphrase-protected update signing key
  python scripts/release.py check v0.3.0      tag, code version and public key agree (CI runs this)
  python scripts/release.py publish v0.3.0    verify the CI-built draft, sign update.json, publish

The private key stays in ~/.config/jian-subtitle; GitHub only ever receives signatures. `publish` signs
only an installer whose GitHub build attestation says the release workflow built it from your local tag.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from subtitle_app.updater import NOTES_LIMIT, REPOSITORY, UpdateError, envelope, installer_name, make_payload, parse_version, read_manifest  # noqa: E402

KEY_PATH = Path.home() / ".config/jian-subtitle/update-signing-key.pem"
WORKFLOW = ".github/workflows/release.yml"
ED25519_SPKI = bytes.fromhex("302a300506032b6570032100")  # DER prefix of a raw 32-byte Ed25519 public key


def read_version(root: Path) -> str:
    return re.search(r'__version__ = "([^"]*)"', (root / "src/subtitle_app/__init__.py").read_text(encoding="utf-8")).group(1)


def read_public_key(root: Path) -> str:
    return re.search(r'PUBLIC_KEY = "([^"]*)"', (root / "src/subtitle_app/update_key.py").read_text(encoding="utf-8")).group(1)


def _rewrite(path: Path, pattern: str, replacement, count: int = 1):
    text, found = re.subn(pattern, replacement, path.read_text(encoding="utf-8"))
    if found != count:
        raise SystemExit(f"{path.name}：找到 {found} 处，应为 {count} 处")
    path.write_text(text, encoding="utf-8")


def write_public_key(root: Path, key: str):
    _rewrite(root / "src/subtitle_app/update_key.py", r'PUBLIC_KEY = "[^"]*"', f'PUBLIC_KEY = "{key}"')


def set_version(root: Path, version: str):
    try:
        parse_version(version)
    except UpdateError as error:
        raise SystemExit(f"{version}：{error}，应为 主.次.修订，例如 0.3.0") from error
    numbers = ", ".join(version.split(".")) + ", 0"
    _rewrite(root / "src/subtitle_app/__init__.py", r'__version__ = "[^"]*"', f'__version__ = "{version}"')
    _rewrite(root / "pyproject.toml", r'(?m)^version = "[^"]*"', f'version = "{version}"')
    _rewrite(root / "packaging/installer.iss", r'#define AppVersion "[^"]*"', f'#define AppVersion "{version}"')
    info = root / "packaging/version_info.txt"
    _rewrite(info, r"(filevers|prodvers)=\(\d+, \d+, \d+, \d+\)", lambda m: f"{m.group(1)}=({numbers})", 2)
    _rewrite(info, r"u'(FileVersion|ProductVersion)', u'[^']*'", lambda m: f"u'{m.group(1)}', u'{version}'", 2)


def check(root: Path, tag: str) -> str:
    version = read_version(root)
    if tag != f"v{version}":
        raise SystemExit(f"标签 {tag} 与代码里的版本 {version} 不一致，标签应为 v{version}")
    try:
        key = base64.b64decode(read_public_key(root), validate=True)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise SystemExit("还没有更新签名公钥：先运行 python scripts/release.py keygen 并提交 update_key.py")
    return version


def plain_notes(body: str) -> str:
    """GitHub release notes (Markdown) as the plain text the update dialog shows."""
    lines = []
    for line in body.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line.startswith("**Full Changelog**") or line.lower() == "## what's changed":
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[*-]\s+", "• ", line)
        line = re.sub(r" by @[\w-]+ in https://github\.com/\S+$", "", line)
        lines.append(line.replace("**", ""))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:NOTES_LIMIT]


def _openssl() -> str:
    """OpenSSL 3 signs Ed25519; macOS's /usr/bin/openssl (LibreSSL) cannot."""
    for candidate in (shutil.which("openssl"), "/opt/homebrew/bin/openssl", "/usr/local/opt/openssl@3/bin/openssl"):
        if candidate and Path(candidate).is_file():
            version = subprocess.run([candidate, "version"], capture_output=True, text=True).stdout
            if version.startswith("OpenSSL 3"):
                return candidate
    raise SystemExit("需要 OpenSSL 3（例如 brew install openssl@3）")


def _run(*command, capture=True) -> str:
    result = subprocess.run(command, stdout=subprocess.PIPE if capture else None, text=True)
    if result.returncode:
        raise SystemExit(f"命令失败：{' '.join(command[:3])} …")
    return (result.stdout or "").strip()


def keygen(path: Path):
    """Make the signing key once. A rerun never replaces it; it only writes the public half again."""
    openssl = _openssl()
    if path.exists() and path.stat().st_size == 0:
        path.unlink()  # Left by a cancelled run: OpenSSL creates the file before it asks for the passphrase.
    if path.exists():
        print(f"已有私钥 {path}，不会覆盖，只重新导出公钥。")
    else:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        print("生成更新签名私钥。请设置口令并记好（输入两次）：")
        try:
            _run(openssl, "genpkey", "-algorithm", "ed25519", "-aes-256-cbc", "-out", str(path), capture=False)
        finally:
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
        os.chmod(path, 0o600)
    print("再输入一次口令，导出公钥：")
    result = subprocess.run([openssl, "pkey", "-in", str(path), "-pubout", "-outform", "DER"], stdout=subprocess.PIPE)
    der = result.stdout
    if result.returncode or len(der) != 44 or not der.startswith(ED25519_SPKI):
        raise SystemExit("没有导出公钥：口令不对或私钥文件损坏。私钥保持原样，可以重新运行 keygen。")
    write_public_key(ROOT, base64.b64encode(der[12:]).decode("ascii"))
    print(f"私钥：{path}（权限 600，口令保护）\n公钥已写入 src/subtitle_app/update_key.py，请提交。\n"
          "请把私钥文件和口令备份到密码管理器：丢了它，已安装的版本就再也收不到自动更新。")


def _sign(openssl: str, key: Path, payload: Path, signature: Path, attempts: int = 3):
    """OpenSSL asks for the passphrase itself; a typo should not mean downloading the installer again."""
    for attempt in range(attempts):
        print("输入私钥口令以签名：" if attempt == 0 else "口令不对，再输一次：")
        if subprocess.run([openssl, "pkeyutl", "-sign", "-rawin", "-inkey", str(key), "-in", str(payload), "-out", str(signature)]).returncode == 0:
            return
    raise SystemExit(f"口令连续 {attempts} 次不对，已停止，草稿没有发布。")


def publish(tag: str, key_path: Path):
    version = check(ROOT, tag)
    public_key = base64.b64decode(read_public_key(ROOT))
    commit = _run("git", "-C", str(ROOT), "rev-parse", f"{tag}^{{commit}}")
    remote = _run("git", "-C", str(ROOT), "ls-remote", "origin", f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}").split()
    if commit not in remote:
        raise SystemExit(f"GitHub 上的 {tag} 不是本地的 {commit[:12]}，已停止")
    if f'PUBLIC_KEY = "{read_public_key(ROOT)}"' not in _run("git", "-C", str(ROOT), "show", f"{tag}:src/subtitle_app/update_key.py"):
        raise SystemExit(f"{tag} 里的公钥与当前代码不同，已停止")
    info = json.loads(_run("gh", "release", "view", tag, "--repo", REPOSITORY, "--json", "isDraft,body,url"))
    if not info["isDraft"]:
        raise SystemExit(f"{tag} 已经发布过了")
    name = installer_name(version)
    with tempfile.TemporaryDirectory(prefix="jian-release-") as temporary:
        folder = Path(temporary)
        _run("gh", "release", "download", tag, "--repo", REPOSITORY, "--pattern", name, "--dir", str(folder), capture=False)
        installer = folder / name
        # Built by our release workflow, on a GitHub-hosted runner, from exactly the commit you tagged.
        _run("gh", "attestation", "verify", str(installer), "--repo", REPOSITORY, "--signer-workflow", f"{REPOSITORY}/{WORKFLOW}",
             "--source-ref", f"refs/tags/{tag}", "--source-digest", commit, "--deny-self-hosted-runners", capture=False)
        data = installer.read_bytes()
        payload = make_payload(version, len(data), hashlib.sha256(data).hexdigest(), plain_notes(info["body"]))
        (folder / "payload").write_bytes(payload.encode("utf-8"))
        _sign(_openssl(), key_path, folder / "payload", folder / "signature")
        manifest = envelope(payload, (folder / "signature").read_bytes())
        try:
            read_manifest(manifest, public_key)  # exactly what installed copies will check
        except UpdateError as error:
            raise SystemExit(f"签名与应用里的公钥对不上：{error}") from error
        (folder / "update.json").write_bytes(manifest)
        _run("gh", "release", "upload", tag, str(folder / "update.json"), "--repo", REPOSITORY, "--clobber", capture=False)
    _run("gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest", capture=False)
    print(f"已发布 {tag}：{info['url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version").add_argument("version")
    commands.add_parser("keygen").add_argument("--key", type=Path, default=KEY_PATH)
    commands.add_parser("check").add_argument("tag")
    publisher = commands.add_parser("publish")
    publisher.add_argument("tag")
    publisher.add_argument("--key", type=Path, default=KEY_PATH)
    args = parser.parse_args()
    if args.command == "version":
        set_version(ROOT, args.version)
        print(f"版本已改为 {args.version}。提交后打标签 v{args.version} 并推送标签。")
    elif args.command == "keygen":
        keygen(args.key)
    elif args.command == "check":
        print(f"{args.tag}：版本 {check(ROOT, args.tag)}，公钥已配置")
    else:
        publish(args.tag, args.key)


if __name__ == "__main__":
    main()
