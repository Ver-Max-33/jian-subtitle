param([string]$PythonLauncher = "py", [string]$PythonExecutable = "")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($env:OS -ne "Windows_NT") { throw "需要 Windows 10/11 x64。" }
Push-Location $ProjectRoot
try {
    # CI passes the interpreter from actions/setup-python; locally the py launcher finds it.
    if (-not $PythonExecutable) { $PythonExecutable = & $PythonLauncher -3.11-64 -c "import sys; print(sys.executable)" }
    & $PythonExecutable -c "import struct, sys; sys.exit(sys.version_info[:2] != (3, 11) or struct.calcsize('P') != 8)"
    if ($LASTEXITCODE -ne 0) { throw "请先安装官方 Python 3.11 x64。" }
    if (-not (Test-Path ".venv-win\Scripts\python.exe")) {
        & $PythonExecutable -m venv .venv-win
        if ($LASTEXITCODE -ne 0) { throw "创建隔离 Python 环境失败。" }
    }
    $Wheelhouse = Join-Path $ProjectRoot ".build-wheels"
    New-Item -ItemType Directory -Path $Wheelhouse -Force | Out-Null
    $SourceArchive = Join-Path $Wheelhouse "proxy_tools-0.1.0.tar.gz"
    $SourceHash = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
    if (-not (Test-Path $SourceArchive)) {
        Invoke-WebRequest -Uri "https://files.pythonhosted.org/packages/f2/cf/77d3e19b7fabd03895caca7857ef51e4c409e0ca6b37ee6e9f7daa50b642/proxy_tools-0.1.0.tar.gz" -OutFile $SourceArchive
    }
    if ((Get-FileHash $SourceArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $SourceHash) { throw "proxy_tools 源码校验失败，未执行安装。" }
    & .\.venv-win\Scripts\python.exe scripts\build_proxy_wheel.py $SourceArchive $Wheelhouse
    if ($LASTEXITCODE -ne 0) { throw "生成已审查的纯 Python wheel 失败。" }
    & .\.venv-win\Scripts\python.exe -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes --no-compile --find-links $Wheelhouse -r requirements-win.lock
    if ($LASTEXITCODE -ne 0) { throw "锁定依赖安装失败。" }
    & .\.venv-win\Scripts\python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw "依赖完整性检查失败。" }
}
finally { Pop-Location }
