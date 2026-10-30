# 简幕 · 图片字幕编辑器

Windows 上批量给图片加字幕的桌面应用：文件名识别为字幕，按拍摄时间排序，人物避让布局，统一样式后导出原尺寸图片。

## 安装

到 [Releases](https://github.com/Ver-Max-33/jian-subtitle/releases) 下载 `JianSubtitle-<版本>-win-x64-setup.exe` 运行即可，默认装在当前用户目录，不需要管理员权限。

- 需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime（Windows 11 自带；缺少时安装程序会提示）。
- 安装包还没有 Windows 代码签名，第一次运行时 SmartScreen 可能提示“未知发布者”，选“仍要运行”。
- 装好后，简幕启动时会检查更新；有新版本时点一下就下载、校验、安装并重新打开。更新包都经过签名校验，见 [发布与自动更新](docs/RELEASING.md)。

## 从源码构建

界面是 React + TypeScript（`frontend/`），桌面外壳和字幕渲染是 Python + pywebview（`src/subtitle_app/`）。前端运行时依赖只有 React、`@base-ui/react` 和 `lucide-react`，版本全部锁定。

macOS 上开发和预览：

```bash
.venv/bin/python run_desktop.py
.venv/bin/python scripts/test_release.py
```

前端在项目专用沙箱里构建（禁止联网、禁止读取个人目录），构建产物 `frontend/dist` 和哈希记录一起提交，Windows 打包只用这份核对过的产物、不运行 npm：

```bash
.venv/bin/python scripts/safe_build.py
.venv/bin/python scripts/verify_frontend.py
```

固定 Node 22.14.0 / npm 10.9.2；不要运行 `npx ...@latest`、`npm audit fix` 或开启安装脚本。依赖获取步骤和风险边界见 [npm 供应链安全](docs/NPM_SUPPLY_CHAIN.md)。

Windows 10/11 x64 上打包（需要 Python 3.11 x64 和 Inno Setup 6）：

```powershell
powershell -File .\scripts\build_windows.ps1
```

脚本会核对前端产物、跑测试、用 PyInstaller 打包，再用 Inno Setup 生成 `JianSubtitle-<版本>-win-x64-setup.exe`。`-Mode OneFile` 生成单个 EXE；`-WebView2Installer <微软官方离线安装程序>` 把 WebView2 打进安装包（会检查微软签名）；`-InstallTest` 在本机做一次静默安装、启动检查和卸载。

## 发布

推送 `v*` 标签后，GitHub Actions 在 Windows 上构建安装包并建草稿 release；在本机运行 `scripts/release.py publish` 签名并发布。步骤见 [发布与自动更新](docs/RELEASING.md)。
