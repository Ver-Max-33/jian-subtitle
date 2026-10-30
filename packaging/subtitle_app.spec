# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


project_root = Path(SPECPATH).parent
mode = os.environ.get("SUBTITLE_BUILD_MODE", "Installer")
one_file = mode == "OneFile"
debug_console = mode == "Debug"

opencv_datas, opencv_binaries, opencv_hidden = collect_all("cv2")

analysis = Analysis(
    [str(project_root / "run_desktop.py")],
    pathex=[str(project_root / "src")],
    binaries=opencv_binaries,
    # Caption fonts (with their OFL texts) land in "fonts"; font_catalog.bundled_font_dirs() reads the same place.
    datas=opencv_datas + collect_data_files("webview") + [(str(project_root / "frontend/dist"), "frontend"), (str(project_root / "src/subtitle_app/resources/fonts"), "fonts"), (str(project_root / "packaging/third-party"), "licenses")],
    hiddenimports=opencv_hidden + ["webview.platforms.winforms", "webview.platforms.edgechromium", "pythonnet", "clr_loader"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["mediapipe", "matplotlib", "qfluentwidgets", "PySide6", "PyQt6", "PyQt5", "PySide2", "cefpython3", "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cef"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)
version_file = project_root / "packaging" / "version_info.txt"
icon_file = project_root / "src" / "subtitle_app" / "resources" / "app.ico"

if one_file:
    executable = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="JianSubtitle",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        version=str(version_file),
        icon=str(icon_file) if icon_file.exists() else None,
        uac_admin=False,
    )
else:
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="JianSubtitle",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=debug_console,
        version=str(version_file),
        icon=str(icon_file) if icon_file.exists() else None,
        uac_admin=False,
    )
    bundle = COLLECT(
        executable,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="JianSubtitle",
    )
