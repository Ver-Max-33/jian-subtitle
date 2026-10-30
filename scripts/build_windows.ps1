param(
    [ValidateSet("Installer", "OneFile")][string]$Mode = "Installer",
    [string]$WebView2Installer = "",
    [switch]$InstallTest,
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"
# Scripts print Chinese; an English-locale Windows console (cp1252) cannot encode it.
$env:PYTHONUTF8 = "1"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $ProjectRoot "scripts\bootstrap_windows.ps1") -PythonExecutable $Python
if ($LASTEXITCODE -ne 0) { throw "环境准备失败。" }
Push-Location $ProjectRoot
try {
    # No npm lifecycle/build code is implicitly executed by this packaging script.
    & .\.venv-win\Scripts\python.exe scripts\verify_frontend.py
    if ($LASTEXITCODE -ne 0) { throw "前端资源与源码/锁文件不匹配，请先隔离构建。" }
    & .\.venv-win\Scripts\python.exe scripts\test_release.py
    if ($LASTEXITCODE -ne 0) { throw "自动测试失败。" }
    $Version = & .\.venv-win\Scripts\python.exe -c "import sys; sys.path.insert(0, 'src'); import subtitle_app; print(subtitle_app.__version__)"
    if ($LASTEXITCODE -ne 0 -or $Version -notmatch '^\d+\.\d+\.\d+$') { throw "无法读取版本号。" }
    $BuildId = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $OutputRoot = Join-Path $ProjectRoot "dist\$BuildId"
    $WorkRoot = Join-Path $ProjectRoot "build\$BuildId"
    $env:SUBTITLE_BUILD_MODE = $Mode
    & .\.venv-win\Scripts\python.exe -m PyInstaller --noconfirm --distpath $OutputRoot --workpath $WorkRoot packaging\subtitle_app.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }
    $Executable = if ($Mode -eq "OneFile") { Join-Path $OutputRoot "JianSubtitle.exe" } else { Join-Path $OutputRoot "JianSubtitle\JianSubtitle.exe" }
    $Smoke = Start-Process -FilePath $Executable -ArgumentList "--smoke-test" -Wait -PassThru
    if ($Smoke.ExitCode -ne 0) { throw "EXE 烟雾检查失败。" }
    if ($Mode -eq "OneFile") {
        Get-FileHash $Executable -Algorithm SHA256
        Write-Host "单文件 EXE：$Executable（目标机需要 WebView2 Runtime）"
        exit 0
    }
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $Candidates = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "$ProgramFilesX86\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")
    $Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Iscc) { throw "请安装官方 Inno Setup 6。" }
    $Definitions = @("/DStagingDir=$(Join-Path $OutputRoot 'JianSubtitle')", "/DReleaseDir=$OutputRoot", "/DAppVersion=$Version")
    if ($WebView2Installer) {
        $Runtime = (Resolve-Path -LiteralPath $WebView2Installer).Path
        $Signature = Get-AuthenticodeSignature -LiteralPath $Runtime
        if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") { throw "WebView2 安装程序没有有效的 Microsoft 签名。" }
        $Definitions += "/DWebView2Installer=$Runtime"
        Get-FileHash -LiteralPath $Runtime -Algorithm SHA256
    }
    & $Iscc @Definitions packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "安装包构建失败。" }
    $Installer = Join-Path $OutputRoot "JianSubtitle-$Version-win-x64-setup.exe"
    Get-FileHash $Installer -Algorithm SHA256
    Write-Host "安装包：$Installer"
    if ($InstallTest) {
        $TestRoot = Join-Path $env:TEMP "JianSubtitle-Test-$BuildId"
        $Process = Start-Process -FilePath $Installer -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", ('/DIR="' + $TestRoot + '"')) -Wait -PassThru
        if ($Process.ExitCode -ne 0) { throw "安装测试失败。" }
        $Smoke = Start-Process -FilePath (Join-Path $TestRoot "JianSubtitle.exe") -ArgumentList "--smoke-test" -Wait -PassThru
        if ($Smoke.ExitCode -ne 0) { throw "安装后的 EXE 检查失败。" }
        # An in-app update runs this installer over the installed copy (src/subtitle_app/updater.py); it must reopen 简幕.
        # No -Wait here: it would also wait for the reopened app, which never exits by itself.
        $Process = Start-Process -FilePath $Installer -ArgumentList @("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1") -PassThru
        $null = $Process.Handle
        $Process.WaitForExit()
        if ($Process.ExitCode -ne 0) { throw "覆盖安装（自动更新）测试失败。" }
        $Reopened = $null
        foreach ($Attempt in 1..30) {
            $Reopened = Get-Process -Name JianSubtitle -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($TestRoot) }
            if ($Reopened) { break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $Reopened) { throw "自动更新安装后没有重新打开简幕。" }
        # A picture of the reopened window, saved next to the installer (CI uploads it): what 简幕 looks like on real Windows.
        Start-Sleep -Seconds 10
        try {
            Add-Type -AssemblyName System.Windows.Forms, System.Drawing
            $Bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
            $Bitmap = New-Object System.Drawing.Bitmap $Bounds.Width, $Bounds.Height
            [System.Drawing.Graphics]::FromImage($Bitmap).CopyFromScreen($Bounds.Location, [System.Drawing.Point]::Empty, $Bounds.Size)
            $Bitmap.Save((Join-Path $OutputRoot "screenshot-reopened.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        }
        catch { Write-Warning "截图失败：$_" }
        $Reopened | Stop-Process -Force
        Start-Sleep -Seconds 2
        $Process = Start-Process -FilePath (Join-Path $TestRoot "unins000.exe") -ArgumentList @("/VERYSILENT", "/NORESTART") -Wait -PassThru
        if ($Process.ExitCode -ne 0) { throw "卸载测试失败，请保留测试目录诊断。" }
    }
}
finally { Pop-Location }
