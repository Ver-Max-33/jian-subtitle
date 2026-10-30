"""macOS build runner: denied-by-default sandbox, no network or personal directories."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
if sys.platform != "darwin":
    raise SystemExit("此隔离脚本只支持 macOS。Windows 打包可使用已验证的前端 dist；重新编译请使用不含个人文件和凭据的隔离 VM。")
node = shutil.which("node")
if not node or not Path("/usr/bin/sandbox-exec").exists():
    raise SystemExit("需要 Node 22 和 macOS sandbox-exec，不能退回无限制构建。")
environment = {"PATH": "/usr/local/bin:/usr/bin:/bin"}
with tempfile.TemporaryDirectory(prefix="jian-subtitle-build-") as temporary:
    runner = ["/usr/bin/sandbox-exec", "-D", f"FRONTEND={FRONTEND}", "-D", f"BUILD_TEMP={temporary}", "-f", str(ROOT / "scripts/frontend-build.sb"), node]
    for command in (["scripts/dependency-guard.mjs"], ["scripts/license-report.mjs"], ["node_modules/typescript/bin/tsc", "--noEmit"], ["scripts/build.mjs"]):
        subprocess.run([*runner, *command], cwd=FRONTEND, env=environment, check=True)
subprocess.run([sys.executable, str(ROOT / "scripts/verify_frontend.py"), "--record"], check=True)
