from __future__ import annotations

import unicodedata

from .models import (
    CaptionRenderRequest,
    CaptionStatus,
    ExportJobItem,
    ExportOptions,
    ExportPlan,
    NamingMode,
    Project,
    StyleSettings,
    stacked_position,
)


class ExportPlanner:
    """Creates the immutable file and render mapping shown during export review."""

    def plan(self, project: Project, options: ExportOptions) -> ExportPlan:
        default_style = StyleSettings.from_mapping(project.default_style)
        items: list[ExportJobItem] = []
        warnings: list[str] = []
        blocking_errors: list[str] = []
        reserved_names: set[str] = set()
        for asset in project.assets:
            if not asset.source_path.is_file():
                blocking_errors.append(f"{asset.filename} 的源文件不存在")
                continue
            if asset.caption_status is CaptionStatus.UNREADABLE:
                blocking_errors.append(f"{asset.filename} 无法读取")
                continue
            if asset.caption_status is CaptionStatus.NEEDS_REVIEW:
                warnings.append(f"{asset.filename} 的自动字幕结构需确认")
            captions = self.caption_requests(asset, default_style, project.show_speaker)
            if not captions:
                if asset.caption_status is not CaptionStatus.NO_CAPTION:
                    warnings.append(f"{asset.filename} 没有字幕")
                if not options.include_no_caption:
                    continue
            requested_name = self._output_name(
                asset.filename, len(items), options
            )
            output_name = self._unique_name(
                requested_name, options, reserved_names
            )
            if output_name != requested_name:
                warnings.append(f"{requested_name} 已存在，将输出为 {output_name}")
            reserved_names.add(self._name_key(output_name))
            items.append(
                ExportJobItem(
                    source_path=asset.source_path,
                    output_path=options.output_dir / output_name,
                    captions=captions,
                    style=default_style,
                    copy_original=(
                        not captions
                        and options.preserve_format
                        and options.preserve_metadata
                    ),
                    preserve_metadata=options.preserve_metadata,
                    quality=options.quality,
                    jpeg_background=options.jpeg_background,
                )
            )
        return ExportPlan(items, warnings, blocking_errors)

    @staticmethod
    def caption_requests(asset, default_style, show_speaker=True):
        return [CaptionRenderRequest(
            f"{subtitle.speaker_id}：{subtitle.text}" if subtitle.speaker_id and show_speaker else subtitle.text,
            subtitle.manual_position_ratio or subtitle.auto_position_ratio or stacked_position(index, len(asset.subtitles)),
            subtitle.rotation,
            StyleSettings.from_mapping({**default_style.to_mapping(), **subtitle.style_overrides}),
        # An empty caption draws nothing but its background box; leave it out, keep the others' own slots.
        ) for index, subtitle in enumerate(asset.subtitles) if subtitle.text.strip()]

    @staticmethod
    def _output_name(filename: str, index: int, options: ExportOptions) -> str:
        from pathlib import Path

        source = Path(filename)
        if options.naming_mode is NamingMode.SEQUENCE:
            stem = f"{options.start_number + index:0{options.digits}d}"
        else:
            stem = source.stem
        suffix = (source.suffix.lower() if options.preserve_format else ".png") if options.image_format == "original" else "." + options.image_format
        return f"{options.prefix}{stem}{options.suffix}{suffix}"

    @staticmethod
    def _name_key(name: str) -> str:
        """How file systems compare names: macOS treats NFC and NFD as one name, Windows and macOS ignore case."""
        return unicodedata.normalize("NFC", name).casefold()

    @staticmethod
    def _unique_name(
        requested_name: str,
        options: ExportOptions,
        reserved_names: set[str],
    ) -> str:
        from pathlib import Path

        requested = Path(requested_name)
        candidate = requested.name
        number = 2
        while (
            ExportPlanner._name_key(candidate) in reserved_names
            or (options.output_dir / candidate).exists()
        ):
            candidate = f"{requested.stem}_{number}{requested.suffix}"
            number += 1
        return candidate
