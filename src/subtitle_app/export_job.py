from __future__ import annotations

from collections.abc import Callable

from .export_service import ExportService
from .models import ExportJobItem, ExportJobResult, JobItemStatus


class ExportJobRunner:
    """Runs isolated export items and returns a retryable result snapshot."""

    def __init__(self, exporter: ExportService | None = None) -> None:
        self._exporter = exporter or ExportService()

    def run(
        self,
        items: list[ExportJobItem],
        *,
        is_cancelled: Callable[[], bool] | None = None,
        on_progress: Callable[[int, int, ExportJobItem], None] | None = None,
    ) -> ExportJobResult:
        cancelled = is_cancelled or (lambda: False)
        was_cancelled = False
        for index, item in enumerate(items):
            if cancelled():
                was_cancelled = True
                for remaining in items[index:]:
                    if remaining.status is JobItemStatus.PENDING:
                        remaining.status = JobItemStatus.SKIPPED
                break
            item.status = JobItemStatus.RUNNING
            try:
                if item.copy_original:
                    self._exporter.copy_original(item.source_path, item.output_path)
                else:
                    self._exporter.export_image(
                        item.source_path,
                        item.output_path,
                        item.captions,
                        item.style,
                        preserve_metadata=item.preserve_metadata,
                        **({"quality": item.quality, "jpeg_background": item.jpeg_background}
                           if item.quality != 95 or item.jpeg_background != (255, 255, 255) else {}),
                    )
            except Exception as error:
                item.status = JobItemStatus.FAILED
                item.error_code = self._error_code(error)
                item.error_message = str(error)
            else:
                item.status = JobItemStatus.SUCCESS
            if on_progress is not None:
                on_progress(index + 1, len(items), item)
        return ExportJobResult(
            items=items,
            success_count=sum(item.status is JobItemStatus.SUCCESS for item in items),
            failed_count=sum(item.status is JobItemStatus.FAILED for item in items),
            skipped_count=sum(item.status is JobItemStatus.SKIPPED for item in items),
            cancelled=was_cancelled,
        )

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, FileNotFoundError):
            return "SOURCE_MISSING"
        if isinstance(error, PermissionError):
            return "OUTPUT_NOT_WRITABLE"
        if isinstance(error, FileExistsError):
            return "OUTPUT_NAME_CONFLICT"
        return "RENDER_FAILED"
