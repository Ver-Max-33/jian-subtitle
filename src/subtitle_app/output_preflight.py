from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .models import Asset, ExportOptions


@dataclass(frozen=True, slots=True)
class PreflightResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class OutputPreflight:
    def inspect(self, assets: list[Asset], options: ExportOptions) -> PreflightResult:
        errors: list[str] = []
        warnings: list[str] = []
        output = options.output_dir.expanduser().resolve()
        missing = [asset for asset in assets if not asset.source_path.is_file()]
        errors.extend(f"{asset.filename} 的源文件不存在" for asset in missing)

        existing_parent = output
        while not existing_parent.exists() and existing_parent.parent != existing_parent:
            existing_parent = existing_parent.parent
        if output.exists() and not output.is_dir():
            errors.append("输出路径不是文件夹")
        elif not existing_parent.is_dir() or not os.access(existing_parent, os.W_OK):
            errors.append("无法写入输出文件夹，请选择其他位置")

        source_parents = {asset.source_path.parent.resolve() for asset in assets}
        if output in source_parents:
            errors.append("输出文件夹不能与源图片文件夹相同")
        elif any(output.is_relative_to(parent) for parent in source_parents):
            warnings.append("输出目录位于源图片文件夹内部，后续导入会自动排除它")

        readable_sizes = [
            asset.source_path.stat().st_size
            for asset in assets
            if asset.source_path.is_file()
        ]
        estimated = sum(readable_sizes) * 2
        if existing_parent.is_dir() and estimated:
            try:
                free = shutil.disk_usage(existing_parent).free
            except OSError:
                warnings.append("暂时无法读取输出磁盘的可用空间")
            else:
                if free < estimated:
                    errors.append("输出磁盘可用空间不足")
        return PreflightResult(errors, warnings)
