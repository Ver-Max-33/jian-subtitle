from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
import zlib
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps

from .export_manifest import ExportManifestStore
from .export_planner import ExportPlanner
from .export_service import ExportService
from .import_service import ImportService
from .layout_service import LayoutService
from .models import CaptionStatus, ExportOptions, JobItemStatus, NamingMode, Project, StyleSettings, SubtitleItem, SubtitleSource
from .output_preflight import OutputPreflight
from .preset_store import PresetStore
from .project_store import ProjectStore
from .recent_projects import RecentProject, RecentProjectStore
from .render_service import RenderService
from .speaker_importer import SpeakerImporter
from .source_relocator import SourceRelocator
from .web_contracts import CommandError, boolean, choice, number, style_patch, text_value, validate_stored_style, validate_style_values, windows_filename
from .caption_presets import apply_builtin, builtin_presets, preset_card
from .asset_sorter import ORDER_MODES, capture_time, order_assets, time_source, time_ties
from .web_fonts import bundled_labels, default_font_id, font_codepoints, font_entries, font_id_resolver
from .web_persistence import TrustedStore
from .updater import UpdateError, Updater
from .style_model import APPEARANCE_KEYS, POSITION_KEYS, REFERENCE_EDGE, SCALED_KEYS, captions as project_captions, fold_majority, normalize, overridden, rescale, restore, short_edge, to_proportional, unified, write_override, write_unified

SCOPES = ("all", "caption")
# Update commands never touch the project, so they work during tasks and ignore its revision.
UPDATE_ACTIONS = {"update_check", "update_download", "update_auto", "open_releases"}


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class WebController:
    """UI-independent command boundary. Commit to disk before acknowledging a mutation."""

    IMPORT_CHUNK = 48

    def __init__(self, data_dir: Path, native=None, updater: Updater | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.native = native
        self.project: Project | None = None
        self.project_path: Path | None = None
        self.lock = threading.RLock()
        self.store = ProjectStore()
        self.presets = PresetStore(self.data_dir / "presets.json")
        self.recents = RecentProjectStore(self.data_dir / "recent.json")
        self.grants: set[Path] = set()
        self.trusted = TrustedStore(self.data_dir)
        try:
            self.grants = {Path(p) for p in self.trusted.load("grants.json", [])}
        except (ValueError, KeyError, TypeError, OSError):
            self.grants = set()  # Fail closed; the user can explicitly relink sources.
        self.outputs: dict[str, Path] = {}
        self.undo: list[bytes] = []
        self.redo: list[bytes] = []
        self._snapshot_project = None
        self._snapshot_path = None
        self._snapshot_encoded = None
        self.replies: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self.media: OrderedDict[str, bytes] = OrderedDict()
        self.media_keys: OrderedDict[str, str] = OrderedDict()
        self.preview_sources: OrderedDict[tuple, Image.Image] = OrderedDict()
        self.preview_source_lock = threading.Lock()
        self.layout = LayoutService()
        self.layout_renderer = RenderService()
        self.save_error: str | None = None
        self.issues: list[dict] = []
        self.preflight = None
        self.job: dict | None = None
        self.stop_event = threading.Event()
        self.close_requested = False
        self.pending_drop = None
        self.recovery_path = None
        self.batch_task = None
        self.batch_stop = threading.Event()
        self.import_task = None
        self.import_stop = threading.Event()
        self.font_previews: OrderedDict[str, bytes] = OrderedDict()
        self.updater = updater if updater is not None else Updater(self.data_dir)

    @property
    def running(self):
        return bool(self.job and self.job["state"] in {"running", "stopping"})

    @property
    def batch_running(self):
        return bool(self.batch_task and self.batch_task["state"] in {"running", "stopping"})

    @property
    def import_running(self):
        return bool(self.import_task and self.import_task["state"] in {"running", "stopping"})

    def dispatch(self, request: dict) -> dict:
        try:
            if not isinstance(request, dict):
                raise CommandError("INVALID_INPUT", "请求必须是对象")
            action = text_value(request.get("action"), "命令", 64, empty=False)
            payload = request.get("payload", {})
            if not isinstance(payload, dict):
                raise CommandError("INVALID_INPUT", "参数必须是对象")
            if action == "preview":
                return {"ok": True, "result": self.preview(payload)}
            if action == "output_preview":
                return {"ok": True, "result": self.output_preview(payload)}
            if action == "recent_preview":
                return {"ok": True, "result": self.recent_preview(payload)}
            if action == "font_preview":
                return {"ok": True, "result": self.font_preview(payload)}
            with self.lock:
                if action == "state":
                    unchanged = bool(self.project and payload.get("knownProjectId") == self.project.id
                                     and payload.get("knownRevision") == self.project.revision
                                     and payload.get("knownPath") == str(self.project_path))
                    return {"ok": True, "result": self.snapshot(include_project=not unchanged)}
                if action == "fonts":
                    return {"ok": True, "result": [{k: v for k, v in entry.items() if k != "path"} for entry in font_entries().values()]}
                request_id = text_value(request.get("requestId"), "请求编号", 100, empty=False)
                digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                cached = self.replies.get(request_id)
                if cached:
                    if cached[0] != digest:
                        raise CommandError("REQUEST_REUSED", "请求编号重复，请重试")
                    return {**cached[1], "state": self.snapshot()}
                if self.running and action not in {"stop_export", "cancel_close", "open_output", *UPDATE_ACTIONS}:
                    raise CommandError("EXPORT_BUSY", "导出进行中，停止后才能编辑")
                if self.batch_running and action not in {"cancel_batch", "cancel_close", *UPDATE_ACTIONS}:
                    raise CommandError("BATCH_BUSY", "批量处理进行中，完成或取消后才能编辑")
                if self.import_running and action not in {"cancel_import", "cancel_close", "close_app", *UPDATE_ACTIONS}:
                    raise CommandError("IMPORT_BUSY", "正在导入图片，完成或取消后才能编辑")
                # Task controls act on a task, not on a revision: an import moves the revision on every chunk.
                if self.project and action not in {"cancel_close", "stop_export", "open_output", "close_app", "cancel_import", "dismiss_import", "update_install", *UPDATE_ACTIONS}:
                    if request.get("projectId") != self.project.id or request.get("expectedRevision") != self.project.revision:
                        raise CommandError("REVISION_CONFLICT", "项目已变化，请刷新后重试")
                result = self._execute(action, payload)
                response = {"ok": True, "result": result, "state": self.snapshot()}
                self.replies[request_id] = (digest, {"ok": True, "result": result})
                while len(self.replies) > 128:
                    self.replies.popitem(last=False)
                return response
        except CommandError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error), "affectedIds": error.affected_ids}}
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {"ok": False, "error": {"code": "IO_ERROR", "message": str(error), "affectedIds": []}}

    def _execute(self, action: str, p: dict):
        if action in UPDATE_ACTIONS or action == "update_install":
            return self._update(action, p)
        if action in {"cancel_batch", "dismiss_batch"}:
            if not self.batch_task or p.get("taskId") != self.batch_task["id"]:
                raise CommandError("TASK_MISSING", "批量任务不存在")
            if action == "cancel_batch":
                if self.batch_running:
                    self.batch_stop.set()
                    self.batch_task["state"] = "stopping"
            elif not self.batch_running:
                self.batch_task = None
            return None
        if action in {"cancel_import", "dismiss_import"}:
            if not self.import_task or p.get("taskId") != self.import_task["id"]:
                raise CommandError("TASK_MISSING", "导入任务不存在")
            if action == "cancel_import":
                if self.import_running:
                    self.import_stop.set()
                    self.import_task["state"] = "stopping"
            elif not self.import_running:
                self.import_task = None
            return None
        # Reading pixels for layout is slow, so large selections run as a task; plain field writes stay instant.
        if (action == "batch_style" or (action == "batch_set" and "layout" in p)) and len(self._ids(self._require_project(), p)) > 32:
            return self._start_batch(action, p)
        if action in {"accept_drop", "dismiss_drop"}:
            if action == "dismiss_drop" and (not self.pending_drop or self.pending_drop["id"] != p.get("dropId")):
                return None
            if not self.pending_drop or self.pending_drop["id"] != p.get("dropId"):
                raise CommandError("DROP_EXPIRED", "拖入的文件已过期，请重新拖入")
            if action == "dismiss_drop":
                self.pending_drop = None
                return None
            paths = []
            for path in self.pending_drop["paths"]:
                if path.is_dir():
                    iterator = path.rglob("*") if boolean(p.get("recursive", False), "包含子文件夹") else path.iterdir()
                    paths.extend(x for x in iterator if x.is_file() and x.suffix.lower() in ImportService.SUPPORTED_EXTENSIONS)
                else:
                    paths.append(path)
            if "newProjectName" in p:
                self._execute("new_project", {"name": p["newProjectName"]})
            self.pending_drop = None
            return self._start_import(paths)
        if action == "recover_project":
            if self.recovery_path is None:
                raise CommandError("INVALID_PROJECT", "没有待恢复的项目")
            return self.open_project(self.recovery_path, recover=True)
        if action == "view_page":
            page = choice(p.get("page"), ("import", "review", "editor", "export"), "页面")
            project = copy.deepcopy(self._require_project())
            if project.last_page != page:
                project.last_page = page
                self._save(project)
                self.project = project
                self._record_recent()
            return None
        if action == "new_project":
            project = Project.create(text_value(p.get("name", "未命名项目"), "项目名称", 100, empty=False).strip())
            project.style_model = 2
            # 5 % of the short edge (54 px at 1080); a saved default keeps its own size (spec 4.2).
            preset = self.presets.default_style()
            project.default_style = (preset or StyleSettings(stroke_width=2, show_background=True, font_size=54)).to_mapping()
            project.default_style["reference_edge"] = project.default_style["reference_edge"] or REFERENCE_EDGE
            font_id = default_font_id()
            if font_id and not project.default_style.get("font_path"):
                project.default_style.update(style_patch({"font_id": font_id}))
            destination = self.data_dir / "projects" / f"{project.id}.subtitle-project.json"
            self.store.save(project, destination)
            self.project, self.project_path = project, destination
            self.undo.clear(); self.redo.clear(); self.issues.clear(); self.job = None; self.batch_task = None
            self._record_recent()
            return None
        if action in {"choose_images", "choose_folder", "open_project", "save_as", "choose_output", "import_speakers", "relocate", "export_log"}:
            if self.native is None:
                raise CommandError("DESKTOP_REQUIRED", "此操作需要桌面窗口，请在桌面版中选择文件")
            result = self.native(action, p)
            if not result:
                return {"cancelled": True}
            if action in {"choose_images", "choose_folder"}:
                if "newProjectName" in p:
                    self._execute("new_project", {"name": p["newProjectName"]})
                return self._start_import([Path(x) for x in result])
            if action == "open_project":
                return self.open_project(Path(result), recover=bool(p.get("recover")))
            if action == "save_as":
                destination = Path(result).resolve()
                if destination in self.grants or destination.suffix != ".json":
                    raise CommandError("INVALID_PATH", "请使用 .json 项目文件，不能覆盖源图")
                self.store.save(self._require_project(), destination)
                self.project_path = destination
                self.save_error = None
                self._record_recent()
                return None
            if action == "choose_output":
                key = uuid4().hex
                self.outputs[key] = Path(result).resolve()
                return {"token": key, "label": str(self.outputs[key])}
            if action == "import_speakers":
                names = SpeakerImporter().load(Path(result))
                project = copy.deepcopy(self._require_project())
                project.speakers = list(dict.fromkeys([*project.speakers, *names]))
                self._commit(project)
                return {"count": len(names)}
            if action == "relocate":
                project = copy.deepcopy(self._require_project())
                root = Path(result).resolve()
                for asset in project.assets:
                    if not self._authorized(asset.source_path):
                        if asset.caption_status != CaptionStatus.UNREADABLE:
                            asset.unavailable_previous_status = asset.caption_status
                        asset.caption_status = CaptionStatus.UNREADABLE
                relocation = SourceRelocator().relocate(project.assets, root)
                for asset in project.assets:
                    if asset.source_path.resolve().is_relative_to(root) and asset.source_path.is_file():
                        self.grants.add(asset.source_path.resolve())
                self._commit(project)
                self.trusted.save("grants.json", sorted(str(p) for p in self.grants))
                return {"relocated": relocation.relocated_count, "unresolved": relocation.unresolved_count, "ambiguous": relocation.ambiguous_count}
            if action == "export_log":
                Path(result).write_text(json.dumps(self.job_snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
                return None
        if action == "open_recent":
            entries = self.recents.list()
            index = int(number(p.get("index"), 0, max(0, len(entries) - 1), "项目", True))
            return self.open_project(entries[index].path, recover=bool(p.get("recover")))
        if action == "remove_recent":
            self.recents.remove(text_value(p.get("path"), "项目记录", 4096))
            return None
        if action == "retry_save":
            self.store.save(self._require_project(), self.project_path)
            self.save_error = None
            return None
        if action in {"undo", "redo"}:
            source, target = (self.undo, self.redo) if action == "undo" else (self.redo, self.undo)
            if not source:
                return None
            project = self.store._decode(json.loads(zlib.decompress(source[-1])))
            current = self._require_project()
            project.revision = current.revision + 1
            previous = self._history_entry(current)
            self._save(project)
            source.pop(); target.append(previous); self.project = project
            self._trim_history(target)
            return None
        if action == "preflight":
            return self.inspect_export(p)
        if action == "start_export":
            return self.start_export(p)
        if action == "stop_export":
            self._check_job(p)
            self.stop_event.set()
            self.job["state"] = "stopping" if self.running else self.job["state"]
            return None
        if action == "retry_export":
            self._check_job(p)
            if self.job["revision"] != self._require_project().revision:
                raise CommandError("REVISION_CONFLICT", "项目已修改，请重新预检")
            pending = [item for item in self.job["items"] if item.status != JobItemStatus.SUCCESS]
            for item in pending:
                if item.output_path.exists():
                    if item.output_fingerprint and fingerprint(item.output_path) == item.output_fingerprint:
                        item.status = JobItemStatus.SUCCESS
                        item.error_message = None
                        continue
                    raise CommandError("OUTPUT_CHANGED", "任务输出位置已有不同文件，未覆盖。请返回导出页重新预检。")
                if not self._authorized(item.source_path) or fingerprint(item.source_path) != item.source_fingerprint:
                    raise CommandError("SOURCE_CHANGED", "源图已变化，请重新预检")
                item.status = JobItemStatus.PENDING
                item.error_message = None
            self._launch_job()
            return None
        if action == "detect_regions":
            asset = self._asset(self._require_project(), p.get("assetId"))
            regions = self.layout.analyze_path(self._source(asset)).regions
            return {"regions": regions, "detected": len(regions)}
        if action == "open_output":
            self._check_job(p)
            if self.native:
                self.native("open_output", {"path": str(self.job["output_dir"])})
            return None
        if action == "open_source":
            asset = self._asset(self._require_project(), p.get("assetId"))
            path = self._source(asset)
            if self.native is None:
                raise CommandError("DESKTOP_REQUIRED", "请在桌面版中打开源图片文件夹")
            self.native("open_source", {"path": str(path)})
            return None
        if action == "cancel_close":
            self.close_requested = False
            return None
        if action == "close_app":
            if self.running:
                raise CommandError("EXPORT_BUSY", "请先安全停止导出")
            if self.native:
                self.native("close_app", {})
            return None
        if action == "preset":
            operation = choice(p.get("operation"), ("save", "delete", "rename", "default"), "预设操作")
            name = text_value(p.get("name"), "预设名称", 64, empty=False).strip()
            if operation == "save":
                asset, caption = self._caption(self._require_project(), p)
                if name in builtin_presets():
                    raise CommandError("PRESET_EXISTS", "这是内置预设的名称，请换一个")
                if name in self.presets.list() and not p.get("overwrite"):
                    raise CommandError("PRESET_EXISTS", "同名预设已存在，请确认覆盖")
                # The preset keeps this picture's pixels and its short edge, so it looks the same elsewhere (spec 4.2).
                style = self._style(caption)
                reference = style["reference_edge"]
                edge = short_edge(asset) or reference or REFERENCE_EDGE
                style = {**(rescale(style, edge / reference) if reference else style), "reference_edge": edge}
                self.presets.save(name, StyleSettings.from_mapping(style))
            elif operation == "delete":
                self.presets.delete(name)
            elif operation == "rename":
                self.presets.rename(name, text_value(p.get("newName"), "预设名称", 64, empty=False))
            else:
                # 经典 is exactly the look a new project gets with no saved default.
                if name in builtin_presets() and name != "经典":
                    raise CommandError("PRESET_BUILTIN", "这个内置预设不能设为默认，请先存为自己的预设")
                self.presets.set_default(None if name == "经典" else name)
            return None
        project = copy.deepcopy(self._require_project())
        result = self._mutate(project, action, p)
        if project != self.project:
            self._commit(project)
        return result

    def _mutate(self, project, action, p, progress=None):
        if action == "rename":
            project.name = text_value(p.get("name"), "项目名称", 100, empty=False).strip()
        elif action == "reorder_assets":
            ids = self._ids(project, p)
            if len(ids) != len(project.assets):
                raise CommandError("INVALID_INPUT", "排序必须包含全部图片")
            order = {identifier: index for index, identifier in enumerate(ids)}
            project.assets.sort(key=lambda a: order[a.id])
            project.order_mode = "manual"
        elif action == "set_order":
            mode = choice(p.get("mode"), tuple(m for m in ORDER_MODES if m != "manual"), "排序方式")
            project.assets[:] = order_assets(project.assets, mode)
            project.order_mode = mode
        elif action in {"caption_text", "caption_add", "caption_delete", "caption_move", "caption_style", "caption_position", "caption_reset", "caption_speaker", "apply_preset", "smart_layout"}:
            asset = self._asset(project, p.get("assetId"))
            if action == "caption_add":
                if len(asset.subtitles) >= 20:
                    raise CommandError("LIMIT", "每张图片最多 20 条字幕")
                item = SubtitleItem(uuid4().hex, "", SubtitleSource.MANUAL)
                asset.subtitles.append(item)
                self._invalidate(asset)
                return {"captionId": item.id}
            _, caption = self._caption(project, p)
            if action == "caption_text":
                caption.text = text_value(p.get("text"), "字幕")
                caption.source = SubtitleSource.MANUAL
                self._invalidate(asset)
            elif action == "caption_speaker":
                value = text_value(p.get("speaker", ""), "说话人", 80).strip()
                caption.speaker_id = value or None
                if value and value not in project.speakers:
                    project.speakers.append(value)
                self._invalidate(asset)
            elif action == "caption_delete":
                asset.subtitles.remove(caption)
                self._invalidate(asset)
            elif action == "caption_move":
                index = asset.subtitles.index(caption)
                target = index + int(choice(p.get("delta"), (-1, 1), "方向"))
                if 0 <= target < len(asset.subtitles):
                    asset.subtitles.insert(target, asset.subtitles.pop(index))
                    self._invalidate(asset)
            elif action == "caption_style":
                # 「全部图片」 writes the unified style; 「仅这条」 an exception for this caption (spec 4.1).
                write = write_unified if choice(p.get("scope", "caption"), SCOPES, "作用范围") == "all" else write_override
                write(project, caption, style_patch(p.get("style")))
            elif action == "caption_position":
                # Apply only changed axes against the latest queued project state.
                position = self._position(asset, caption)
                caption.manual_position_ratio = (number(p.get("x", position[0]), 0, 1, "X"), number(p.get("y", position[1]), 0, 1, "Y"))
                caption.rotation = number(p.get("rotation", caption.rotation), -180, 180, "旋转")
                if "maxWidth" in p:
                    caption.style_overrides["max_width"] = number(p["maxWidth"], 0.1, 1, "最大宽度")
            elif action == "caption_reset":
                if p.get("scope") == "position":
                    caption.manual_position_ratio = None; caption.auto_position_ratio = None; caption.rotation = 0
                elif p.get("scope") == "style":
                    # Position fields stay with the caption; only its look follows the unified style again.
                    restore([caption])
                else:
                    raise CommandError("INVALID_INPUT", "请选择恢复范围")
            elif action == "apply_preset":
                # A preset is a template: 「全部图片」 replaces the unified style with it, 「仅这条」 applies it here only.
                if choice(p.get("scope", "caption"), SCOPES, "作用范围") == "all":
                    write_unified(project, caption, self._preset_style(p.get("name"), asset, caption, project, base=unified(project)))
                else:
                    write_override(project, caption, self._preset_style(p.get("name"), asset, caption, project))
            else:
                targets = {c.id for c in asset.subtitles if c.manual_position_ratio is None or c.id == caption.id}
                return self._layout_asset(project, asset, targets)
        elif action == "project_settings":
            project.show_speaker = boolean(p.get("showSpeaker"), "说话人前缀")
        elif action == "style_to_proportional":
            if unified(project)["reference_edge"]:
                raise CommandError("ALREADY_PROPORTIONAL", "已经是按画面比例")
            return {"referenceEdge": to_proportional(project)}
        elif action == "style_restore":
            # 「恢复」: captions follow the unified style again; position fields are never touched.
            scope = choice(p.get("scope"), ("caption", "field", "project", "selection"), "恢复范围")
            keys = p.get("keys")
            if keys is not None and (not isinstance(keys, list) or not keys or any(key not in APPEARANCE_KEYS for key in keys)):
                raise CommandError("INVALID_INPUT", "恢复的样式字段无效")
            if scope == "caption":
                items = [self._caption(project, p)[1]]
            elif scope == "selection":
                ids = set(self._ids(project, p))
                ordinal = None if p.get("captions") == "all" else int(number(p.get("captions"), 0, 19, "字幕范围", True))
                items = [c for a in project.assets if a.id in ids for c in (a.subtitles if ordinal is None else a.subtitles[ordinal:ordinal + 1])]
            else:
                if scope == "field" and keys is None:
                    raise CommandError("INVALID_INPUT", "请指定要恢复的样式字段")
                items = list(project_captions(project))
                keys = None if scope == "project" else keys
            return {"restored": restore(items, keys)}
        elif action == "speakers":
            operation = choice(p.get("operation"), ("add", "remove"), "说话人操作")
            name = text_value(p.get("name"), "说话人", 80, empty=False).strip()
            if operation == "add" and name not in project.speakers:
                project.speakers.append(name)
            elif operation == "remove" and name in project.speakers:
                # Captions keep the name they show; only the list of choices changes.
                project.speakers.remove(name)
        elif action == "batch_set":
            ids = set(self._ids(project, p))
            ordinal, style, axes, rotation, speaker, layout, preset = self._batch_set_args(p)
            updated, skipped, layout_warnings = [], [], []
            for index, asset in enumerate(a for a in project.assets if a.id in ids):
                if progress:
                    progress(index, asset.filename)
                targets = asset.subtitles if ordinal is None else asset.subtitles[ordinal:ordinal + 1]
                if asset.caption_status == CaptionStatus.UNREADABLE or not targets:
                    skipped.append({"id": asset.id, "reason": "图片不可读" if asset.caption_status == CaptionStatus.UNREADABLE else "没有对应的字幕"})
                    continue
                for caption in targets:
                    if preset:
                        write_override(project, caption, self._preset_style(preset, asset, caption, project))
                    write_override(project, caption, style)
                    if axes:
                        current = self._position(asset, caption)
                        caption.manual_position_ratio = (axes.get("x", current[0]), axes.get("y", current[1]))
                    if rotation is not None:
                        caption.rotation = rotation
                    if speaker is not None:
                        caption.speaker_id = speaker or None
                if speaker is not None:
                    if speaker and speaker not in project.speakers:
                        project.speakers.append(speaker)
                    self._invalidate(asset)
                if layout:
                    try:
                        placed = self._layout_asset(project, asset, {c.id for c in targets})
                        if placed["warning"]:
                            layout_warnings.append({"assetId": asset.id, "message": placed["warning"]})
                    except (CommandError, OSError) as error:
                        layout_warnings.append({"assetId": asset.id, "message": str(error)})
                updated.append(asset.id)
            return {"updated": updated, "skipped": skipped, "layoutWarnings": layout_warnings, "revision": project.revision}
        elif action == "confirm":
            asset = self._asset(project, p.get("assetId"))
            self._source(asset)
            bad = [c.id for c in asset.subtitles if not c.text.strip()]
            if bad or not asset.subtitles:
                raise CommandError("CAPTION_EMPTY", "请填写这张图片的全部字幕，或标记为无需字幕", bad)
            asset.caption_status = CaptionStatus.READY
        elif action == "confirm_batch":
            # 「标为已确认」 for many: only images whose captions are all filled in; the rest are reported (spec 4.5).
            ids = set(self._ids(project, p))
            confirmed, skipped = [], []
            for asset in (a for a in project.assets if a.id in ids and a.caption_status != CaptionStatus.NO_CAPTION):
                try:
                    readable = asset.caption_status != CaptionStatus.UNREADABLE and bool(self._source(asset))
                except (CommandError, OSError):
                    readable = False
                reason = ("图片不可读" if not readable else "没有字幕" if not asset.subtitles
                          else "有空字幕" if any(not c.text.strip() for c in asset.subtitles) else None)
                if reason:
                    skipped.append({"id": asset.id, "reason": reason})
                else:
                    asset.caption_status = CaptionStatus.READY
                    confirmed.append(asset.id)
            return {"confirmed": confirmed, "skipped": skipped}
        elif action in {"batch", "replace_preview", "replace", "batch_style_preview", "batch_style"}:
            ids = set(self._ids(project, p))
            assets = [a for a in project.assets if a.id in ids]
            if action in {"replace_preview", "replace"}:
                search = text_value(p.get("search"), "查找文字", 1000, empty=False)
                replacement = text_value(p.get("replacement", ""), "替换文字", 1000)
                matches = [{"assetId": a.id, "captionId": c.id, "before": c.text, "after": c.text.replace(search, replacement)} for a in assets for c in a.subtitles if search in c.text]
                if action == "replace":
                    for asset in assets:
                        for caption in asset.subtitles:
                            if search in caption.text:
                                caption.text = text_value(caption.text.replace(search, replacement), "替换后的字幕")
                                caption.source = SubtitleSource.MANUAL
                                self._invalidate(asset)
                return {"matches": matches, "images": len(set(m["assetId"] for m in matches)), "revision": project.revision}
            if action in {"batch_style_preview", "batch_style"}:
                source_asset, source_caption = self._caption(project, p)
                ordinal = int(number(p.get("ordinal", 0), 0, 19, "字幕序号", True))
                all_captions = boolean(p.get("allCaptions", False), "字幕范围")
                copy_style = boolean(p.get("style", True), "复制样式")
                copy_position = boolean(p.get("position", False), "复制位置")
                same_aspect = boolean(p.get("sameAspect", False), "同宽高比")
                source_ratio = self._aspect(source_asset) if same_aspect or copy_position else None
                if not copy_style and not copy_position:
                    raise CommandError("EMPTY_SCOPE", "请选择要应用的字段")
                if all_captions and copy_position and source_caption.manual_position_ratio is not None:
                    raise CommandError("POSITION_SCOPE", "不能把同一手动坐标复制给所有字幕。请选择同序号字幕，或先将来源改为智能避让。")
                updated, skipped, different_aspect, layout_warnings = [], [], [], []
                for asset_index, asset in enumerate(assets):
                    if progress:
                        progress(asset_index, asset.filename)
                    if asset.id == source_asset.id:
                        skipped.append({"id": asset.id, "reason": "来源图片"}); continue
                    if same_aspect or copy_position:
                        try:
                            ratio = self._aspect(asset)
                        except (CommandError, OSError):
                            skipped.append({"id": asset.id, "reason": "图片不可读"}); continue
                        if same_aspect and abs(ratio - source_ratio) > .01:
                            skipped.append({"id": asset.id, "reason": "宽高比不同"}); continue
                    targets = asset.subtitles if all_captions else asset.subtitles[ordinal:ordinal + 1]
                    if not targets or asset.caption_status == CaptionStatus.UNREADABLE:
                        skipped.append({"id": asset.id, "reason": "没有对应字幕或图片不可读"}); continue
                    updated.append(asset.id)
                    if copy_position and abs(ratio - source_ratio) > .01:
                        different_aspect.append(asset.id)
                    if action == "batch_style":
                        old_positions = {c.id: (c.manual_position_ratio, c.auto_position_ratio, c.rotation) for c in targets}
                        for caption in targets:
                            if copy_style:
                                copied = self._style(source_caption, project)
                                caption.style_overrides = copy.deepcopy({k: v for k, v in copied.items() if k in APPEARANCE_KEYS or k in POSITION_KEYS})
                                normalize(project, [caption])
                            if copy_position:
                                caption.manual_position_ratio = source_caption.manual_position_ratio
                                caption.auto_position_ratio = None
                                caption.rotation = source_caption.rotation
                        if copy_position and source_caption.manual_position_ratio is None:
                            result = self._layout_asset(project, asset, {c.id for c in targets})
                            if not result["placed"]:
                                for caption in targets:
                                    caption.manual_position_ratio, caption.auto_position_ratio, caption.rotation = old_positions[caption.id]
                            if result["warning"]:
                                layout_warnings.append({"assetId": asset.id, "message": result["warning"]})
                return {"updated": updated, "skipped": skipped, "differentAspect": different_aspect, "revision": project.revision, "layoutWarnings": layout_warnings}
            operation = choice(p.get("operation"), ("remove", "no_caption", "clear", "extract", "speaker"), "批量操作")
            for asset in assets:
                if operation == "remove":
                    project.assets.remove(asset)
                elif operation in {"no_caption", "clear"}:
                    asset.subtitles.clear()
                    asset.caption_status = CaptionStatus.NO_CAPTION if operation == "no_caption" else CaptionStatus.MISSING
                elif operation == "extract":
                    ImportService().reclassify_asset(asset, overwrite_manual=boolean(p.get("overwrite", False), "覆盖手动字幕"))
                    if asset.caption_status == CaptionStatus.READY:
                        asset.caption_status = CaptionStatus.NEEDS_REVIEW
                else:
                    speaker = text_value(p.get("speaker", ""), "说话人", 80).strip()
                    for caption in asset.subtitles:
                        caption.speaker_id = speaker or None
                    if speaker and speaker not in project.speakers:
                        project.speakers.append(speaker)
                    self._invalidate(asset)
            return {"count": len(assets)}
        else:
            raise CommandError("UNKNOWN_COMMAND", "不支持的操作")

    def _update(self, action: str, p: dict):
        if action in {"update_install", "open_releases"} and self.native is None:
            raise CommandError("DESKTOP_REQUIRED", "此操作需要桌面窗口")
        try:
            if action == "update_check":
                self.updater.check()
            elif action == "update_download":
                self.updater.download()
            elif action == "update_auto":
                self.updater.set_auto(boolean(p.get("enabled"), "自动检查更新"))
            elif action == "open_releases":
                self.native("open_releases", {})
            else:
                # Projects are committed on every change; closing hands the files to the installer.
                self.updater.install()
                self.native("close_app", {})
        except UpdateError as error:
            raise CommandError("UPDATE_FAILED", str(error)) from error
        return None

    def _batch_set_args(self, p):
        """A field-level edit for many images: only the fields named here are written, nothing is copied."""
        scope = p.get("captions")
        ordinal = None if scope == "all" else int(number(scope, 0, 19, "字幕范围", True))
        style = style_patch(p["style"]) if "style" in p else {}
        position = p.get("position", {})
        if not isinstance(position, dict) or set(position) - {"x", "y", "rotation", "maxWidth"}:
            raise CommandError("INVALID_INPUT", "位置参数无效")
        axes = {key: number(position[key], 0, 1, key.upper()) for key in ("x", "y") if key in position}
        rotation = number(position["rotation"], -180, 180, "旋转") if "rotation" in position else None
        if "maxWidth" in position:
            style["max_width"] = number(position["maxWidth"], 0.1, 1, "最大宽度")
        speaker = text_value(p["speaker"], "说话人", 80).strip() if "speaker" in p else None
        layout = choice(p["layout"], ("auto",), "位置方式") if "layout" in p else None
        preset = p.get("preset")
        if preset is not None and preset not in self.presets.list() and preset not in builtin_presets():
            raise CommandError("PRESET_MISSING", "预设不存在")
        if not style and not axes and rotation is None and speaker is None and layout is None and preset is None:
            raise CommandError("EMPTY_SCOPE", "请选择要修改的内容")
        if ordinal is None and axes:
            raise CommandError("POSITION_SCOPE", "不能把同一位置给每张图的所有字幕。请把范围改为「每张第 N 条字幕」。")
        if layout and axes:
            raise CommandError("INVALID_INPUT", "智能避让与手动位置不能同时设置")
        return ordinal, style, axes, rotation, speaker, layout, preset

    def _preset_style(self, name, asset, caption, project, base=None):
        """The style fields a preset sets on this caption (or on `base`, the unified style), in this project's sizes.
        A preset is a look, not a layout."""
        # Proportional projects convert to their reference edge, fixed-pixel ones to this picture (spec 4.2).
        target = unified(project)["reference_edge"] or short_edge(asset) or REFERENCE_EDGE
        saved = self.presets.list()
        if name in saved:
            style = saved[name].to_mapping()
            # Wrap width, alignment and edge margin stay with the caption.
            for key in (*POSITION_KEYS, "reference_edge"):
                style.pop(key)
            return rescale(style, target / (saved[name].reference_edge or REFERENCE_EDGE))
        if name in builtin_presets():
            try:
                style = apply_builtin(name, base or self._style(caption, project))
            except LookupError:
                raise CommandError("FONT_MISSING", "内置字体缺失，请重新安装简幕") from None
            style.pop("reference_edge", None)
            # Built-in looks are defined at 1080; an outline given as a share of the font size is already in project sizes.
            ratio = builtin_presets()[name].stroke_ratio is not None
            fixed = {key: value for key, value in style.items() if key in SCALED_KEYS and not (ratio and key == "stroke_width")}
            return {**style, **rescale(fixed, target / REFERENCE_EDGE)}
        raise CommandError("PRESET_MISSING", "预设不存在")

    def _start_batch(self, action, payload):
        project = copy.deepcopy(self._require_project())
        # Validate the whole scope before starting; neither check decodes source pixels.
        if action == "batch_style":
            count = len(self._mutate(project, "batch_style_preview", payload)["updated"])
        else:
            self._batch_set_args(payload)
            count = len(payload["assetIds"])
        self.batch_stop.clear()
        task = {"id": uuid4().hex, "state": "running", "completed": 0,
                "total": len(payload["assetIds"]), "filename": "", "error": None, "result": None}
        self.batch_task = task

        def progress(completed, filename):
            if self.batch_stop.is_set():
                raise CommandError("BATCH_CANCELLED", "已取消，项目未改变")
            with self.lock:
                task["completed"], task["filename"] = completed, filename

        def run():
            try:
                result = self._mutate(project, action, payload, progress=progress)
                with self.lock:
                    if self.batch_stop.is_set():
                        task["state"] = "cancelled"
                        return
                    if project != self.project:
                        self._commit(project)
                    task.update(state="complete", completed=task["total"], result={
                        "updated": len(result["updated"]), "warnings": len(result["layoutWarnings"]),
                        "warningAssets": result["layoutWarnings"][:20], "skipped": len(result["skipped"]),
                    })
            except Exception as error:
                with self.lock:
                    task["state"] = "cancelled" if self.batch_stop.is_set() else "failed"
                    task["error"] = None if self.batch_stop.is_set() else str(error)

        threading.Thread(target=run, name="subtitle-batch-layout", daemon=True).start()
        return {"started": True, "taskId": task["id"], "count": count}

    def _layout_asset(self, project, asset, target_ids):
        analysis = self.layout.analyze_path(self._source(asset))
        default_style = StyleSettings.from_mapping(project.default_style)
        requests = ExportPlanner.caption_requests(asset, default_style, project.show_speaker)
        for request in requests:
            validate_stored_style(request.style.to_mapping())
        geometry = self.layout_renderer.measure(analysis.image_size, requests, default_style)
        targets, sizes, occupied = [], [], []
        for caption, bounds in zip(asset.subtitles, geometry):
            if not caption.text.strip():
                continue
            x1, y1, x2, y2 = bounds["bounds"]
            if caption.id in target_ids:
                targets.append(caption)
                sizes.append((x2-x1, y2-y1))
            else:
                occupied.append((x1, y1, x2-x1, y2-y1))
        result = self.layout.arrange(analysis, sizes, occupied)
        placed = result.positions is not None and bool(targets)
        if placed:
            for caption, position in zip(targets, result.positions):
                caption.auto_position_ratio = position
                caption.manual_position_ratio = None
        warning = ("空间不足，已保留原位置。请减小字号或调整手动字幕。" if not placed else
                   "字幕之间已分开，但部分位置仍覆盖人物，请检查。" if result.overlaps_people else None)
        if not targets:
            warning = "请先填写字幕，再使用智能避让。"
        return {"regions": analysis.regions, "detected": len(analysis.regions), "placed": placed,
                "count": len(targets) if placed else 0, "warning": warning}

    def import_paths(self, paths: list[Path]):
        """Read and add images in the calling thread (command line, tests); the window imports through `_start_import`."""
        new_paths, duplicates = self._prepare_import(paths)
        return self._import(new_paths, duplicates)

    def _prepare_import(self, paths):
        if not self.project:
            self._execute("new_project", {"name": "未命名项目"})
        project = self._require_project()
        existing = {a.source_path.resolve() for a in project.assets}
        unique_paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
        new_paths = [p for p in unique_paths if p not in existing]
        if len(new_paths) + len(project.assets) > 5000:
            raise CommandError("LIMIT", "每个项目最多 5000 张图片")
        return new_paths, len(paths) - len(new_paths)

    def _start_import(self, paths):
        new_paths, duplicates = self._prepare_import(paths)
        self.import_stop.clear()
        task = {"id": uuid4().hex, "state": "running", "completed": 0, "total": len(new_paths), "current": "", "error": None, "result": None}
        self.import_task = task
        threading.Thread(target=self._import, args=(new_paths, duplicates, task), name="subtitle-import", daemon=True).start()
        return {"started": True, "taskId": task["id"], "total": len(new_paths), "duplicates": duplicates}

    def _import(self, paths, duplicates, task=None):
        """Read a chunk at a time and add each chunk once read, so pictures appear while the rest load.

        The whole import is one undo step. Editing waits for it (IMPORT_BUSY), so no edit interleaves with the chunks.
        """
        with self.lock:
            self.issues = []
            start = len(self._require_project().assets)
        count, first = 0, True
        try:
            for offset in range(0, len(paths), self.IMPORT_CHUNK):
                if task and self.import_stop.is_set():
                    break
                chunk = paths[offset:offset + self.IMPORT_CHUNK]
                if task:
                    with self.lock:
                        task["current"] = chunk[0].name
                imported = ImportService().import_paths(chunk)
                with self.lock:
                    if task and self.import_stop.is_set():
                        break
                    project = copy.deepcopy(self._require_project())
                    existing = {a.source_path.resolve() for a in project.assets}
                    for asset in imported.assets:
                        if asset.source_path in existing:
                            continue
                        existing.add(asset.source_path); self.grants.add(asset.source_path)
                        asset.import_order = len(project.assets)
                        if asset.caption_status == CaptionStatus.READY:
                            asset.caption_status = CaptionStatus.NEEDS_REVIEW
                        project.assets.append(asset); count += 1
                    # A hand-arranged project keeps its order and receives the new pictures at the end, oldest first.
                    if project.order_mode == "manual":
                        project.assets[start:] = order_assets(project.assets[start:], "time")
                    else:
                        project.assets[:] = order_assets(project.assets, project.order_mode)
                    self.issues.extend({"file": item.path.name, "message": item.message} for item in imported.issues)
                    self._commit(project, history=first)
                    first = False
                    self.trusted.save("grants.json", sorted(str(p) for p in self.grants))
                    if task:
                        task["completed"] += len(chunk)
        except Exception as error:
            if task is None:
                raise
            with self.lock:
                task["error"] = str(error)
        summary = {"imported": count, "duplicates": duplicates, "issues": len(self.issues)}
        if task:
            with self.lock:
                task["state"] = "failed" if task["error"] else "cancelled" if self.import_stop.is_set() else "complete"
                task["result"] = summary
        return {**summary, "issues": self.issues}

    def stage_drop(self, paths):
        with self.lock:
            if not self.running and not self.batch_running and not self.import_running:
                self.pending_drop = {"id": uuid4().hex, "paths": list(paths)}

    def open_project(self, path: Path, *, recover=False):
        path = path.resolve()
        source_directory = path.parent
        recovered = False
        if path.suffix != ".json" or path.stat().st_size > self.store.MAX_BYTES:
            raise CommandError("INVALID_PROJECT", "项目格式或大小不合法")
        try:
            project = self.store._load_file(path)
        except (OSError, ValueError, TypeError, KeyError):
            backup = path.with_name(path.name + ".bak")
            if not recover or not backup.exists():
                self.recovery_path = path if backup.exists() else None
                raise CommandError("BACKUP_AVAILABLE" if backup.exists() else "INVALID_PROJECT", "项目无法读取，可选择恢复备份" if backup.exists() else "项目无法读取")
            project = self.store._load_file(backup)
            project.id = uuid4().hex
            project.name = f"{project.name}（恢复）"
            path = self.data_dir / "projects" / f"{project.id}.subtitle-project.json"
            recovered = True
        if len(project.assets) > 5000 or len({a.id for a in project.assets}) != len(project.assets):
            raise CommandError("INVALID_PROJECT", "项目素材数量或编号不合法")
        for asset in project.assets:
            if len(asset.subtitles) > 20 or len({c.id for c in asset.subtitles}) != len(asset.subtitles):
                raise CommandError("INVALID_PROJECT", "字幕数量或编号不合法")
            if asset.source_path.resolve().is_relative_to(source_directory):
                self.grants.add(asset.source_path.resolve())
            if not self._authorized(asset.source_path):
                asset.unavailable_previous_status = asset.caption_status
                asset.caption_status = CaptionStatus.UNREADABLE
            elif asset.width is None and asset.source_path.is_file():
                # Projects from before sizes were recorded: read the header once; saved with the next edit.
                try:
                    with Image.open(asset.source_path) as opened:
                        asset.width, asset.height = ImportService.upright_size(opened)
                except (OSError, ValueError, Image.DecompressionBombError):
                    pass
            for caption in asset.subtitles:
                text_value(caption.text, "字幕")
                number(caption.rotation, -180, 180, "旋转")
                for position in (caption.manual_position_ratio, caption.auto_position_ratio):
                    if position is not None:
                        if len(position) != 2:
                            raise CommandError("INVALID_PROJECT", "坐标不合法")
                        for value in position:
                            number(value, 0, 1, "坐标")
                validate_style_values({**project.default_style, **caption.style_overrides})
        if project.style_model < 2:
            # Not an undo step: the picture is unchanged; the fold is saved with the next edit.
            fold_majority(project)
        SourceRelocator().mark_missing(project.assets)
        if recovered:
            self.store.save(project, path)
        self.project, self.project_path = project, path
        self.undo.clear(); self.redo.clear(); self.job = None; self.batch_task = None; self.issues.clear(); self.save_error = None
        self._record_recent()
        self.recovery_path = None
        self._recover_job()
        return {"recovered": recovered, "page": project.last_page if project.last_page in {"import", "review", "editor", "export"} else "review"}

    def _commit(self, project, *, history=True):
        """Save `project` as the new state. `history=False` folds the change into the previous undo step."""
        current = self._require_project()
        project.revision = current.revision + 1
        previous = self._history_entry(current) if history else None
        self._save(project)
        if history:
            self.undo.append(previous)
            self.redo.clear()
            self._trim_history(self.undo)
        self.project = project; self.preflight = None
        self._record_recent()

    def _history_entry(self, project):
        return zlib.compress(json.dumps(self.store._encode(project), ensure_ascii=False, separators=(",", ":")).encode(), level=1)

    def _trim_history(self, stack):
        while len(stack) > 50 or (len(stack) > 1 and sum(map(len, self.undo)) + sum(map(len, self.redo)) > 32 * 1024 * 1024):
            stack.pop(0)

    def _save(self, project):
        try:
            self.store.save(project, self.project_path)
        except OSError as error:
            self.save_error = str(error)
            raise CommandError("SAVE_FAILED", "保存失败，输入尚未提交。请重试或另存项目。") from error
        self.save_error = None

    def _record_recent(self):
        if self.project and self.project_path:
            try:
                self.recents.record(RecentProject(self.project_path, self.project.name, len(self.project.assets), self.project.updated_at, self.project.last_page))
            except OSError:
                pass  # A recent-index failure must not turn a committed edit into a retry.

    def _require_project(self):
        if self.project is None:
            raise CommandError("NO_PROJECT", "请先创建或打开项目")
        return self.project

    @staticmethod
    def _asset(project, identifier):
        result = next((a for a in project.assets if a.id == identifier), None)
        if result is None:
            raise CommandError("ASSET_MISSING", "图片不在当前项目中")
        return result

    def _caption(self, project, p):
        asset = self._asset(project, p.get("assetId"))
        caption = next((c for c in asset.subtitles if c.id == p.get("captionId")), None)
        if caption is None:
            raise CommandError("CAPTION_MISSING", "字幕已不存在")
        return asset, caption

    def _ids(self, project, p):
        ids = p.get("assetIds")
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            raise CommandError("EMPTY_SCOPE", "请明确选择图片范围")
        available = {a.id for a in project.assets}
        if any(identifier not in available for identifier in ids):
            raise CommandError("ASSET_MISSING", "图片不在当前项目中")
        return ids

    @staticmethod
    def _invalidate(asset):
        asset.caption_status = CaptionStatus.NEEDS_REVIEW if asset.subtitles and all(c.text.strip() for c in asset.subtitles) else CaptionStatus.MISSING

    def _authorized(self, path):
        return path.resolve() in self.grants and path.suffix.lower() in ImportService.SUPPORTED_EXTENSIONS

    def _aspect(self, asset):
        # The file, not the size recorded at import: the picture may have been cropped since.
        with Image.open(self._source(asset)) as source:
            width, height = source.size
            if source.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
            return width / height

    def _source(self, asset):
        if not self._authorized(asset.source_path):
            raise CommandError("SOURCE_PERMISSION", "请重新定位素材文件夹以授权读取", [asset.id])
        if not asset.source_path.is_file():
            raise CommandError("SOURCE_MISSING", "源文件不存在，请重新定位", [asset.id])
        return asset.source_path.resolve()

    @staticmethod
    def _position(asset, caption):
        """Where a caption sits: placed by hand, by smart layout, or stacked up from the bottom by default."""
        return caption.manual_position_ratio or caption.auto_position_ratio or (0.5, max(0.12, 0.86 - asset.subtitles.index(caption) * 0.12))

    def _style(self, caption, project=None):
        return {**StyleSettings().to_mapping(), **(project or self._require_project()).default_style, **caption.style_overrides}

    @staticmethod
    def caption_font_bytes(font_id):
        """A bundled caption font for the editor's live preview (spec 4.4). Only files pinned in fonts.lock.json;
        system fonts are referenced by name instead."""
        font = font_entries().get(font_id)
        path = Path(font["path"]) if font and font["bundled"] else None
        if path is None or path.name not in bundled_labels() or path.suffix.lower() not in {".ttf", ".otf"}:
            return None
        return path.read_bytes(), "font/otf" if path.suffix.lower() == ".otf" else "font/ttf"

    @staticmethod
    def _public_style(style, resolve_font):
        """What the editor sees of a style: the font as an id, never a path on this computer."""
        public = {k: v for k, v in style.items() if k not in {"font_path", "font_index"}}
        public["font_id"] = resolve_font(style)
        return public

    def snapshot(self, *, include_project=True):
        project = self.project
        encoded = None
        if include_project and project is self._snapshot_project and self.project_path == self._snapshot_path:
            encoded = self._snapshot_encoded
        elif include_project and project:
            assets = []
            resolve_font = font_id_resolver()
            tied = {identifier for group in time_ties(project.assets) for identifier in group}
            for asset in project.assets:
                captions = []
                for caption in asset.subtitles:
                    captions.append({"id": caption.id, "text": caption.text, "source": caption.source.value, "speaker": caption.speaker_id or "", "position": self._position(asset, caption), "manual": caption.manual_position_ratio is not None, "rotation": caption.rotation,
                                     "style": self._public_style(self._style(caption), resolve_font), "overrides": overridden(caption)})
                assets.append({"id": asset.id, "filename": asset.filename, "sourcePath": str(asset.source_path), "createdAt": asset.created_at.isoformat(), "modifiedAt": asset.modified_at.isoformat(),
                               "takenAt": asset.taken_at.isoformat() if asset.taken_at else None, "captureTime": capture_time(asset).isoformat(), "timeSource": time_source(asset), "timeTie": asset.id in tied,
                               "width": asset.width, "height": asset.height, "importOrder": asset.import_order, "kind": asset.filename_kind.value, "status": asset.caption_status.value, "captions": captions})
            encoded = {"id": project.id, "name": project.name, "revision": project.revision, "assets": assets, "speakers": project.speakers, "path": str(self.project_path), "orderMode": project.order_mode,
                       "style": self._public_style(unified(project), resolve_font), "referenceEdge": unified(project)["reference_edge"], "showSpeaker": project.show_speaker}
            self._snapshot_project, self._snapshot_path, self._snapshot_encoded = project, self.project_path, encoded
        return {"project": encoded, "projectUnchanged": not include_project, "batchTask": copy.deepcopy(self.batch_task), "importTask": copy.deepcopy(self.import_task), "saveError": self.save_error, "canUndo": bool(self.undo), "canRedo": bool(self.redo), "issues": self.issues, "recents": [{"index": i, "path": str(r.path), "name": r.name, "count": r.asset_count, "page": r.page, "updatedAt": r.updated_at.isoformat()} for i, r in enumerate(self.recents.list())], "presets": list(self.presets.list()), "builtinPresets": [preset_card(name) for name in builtin_presets()], "defaultPreset": self.presets.default_name, "job": self.job_snapshot(), "desktop": self.native is not None, "closeRequested": self.close_requested, "update": self.updater.snapshot(), "pendingDrop": {"id": self.pending_drop["id"], "count": len(self.pending_drop["paths"]), "folders": any(p.is_dir() for p in self.pending_drop["paths"])} if self.pending_drop else None}

    def preview(self, p):
        with self.lock:
            current = self._require_project()
            if p.get("projectId") != current.id or p.get("revision") != current.revision:
                raise CommandError("REVISION_CONFLICT", "预览已过期")
            project = copy.copy(current)
            project.default_style = copy.deepcopy(current.default_style)
            asset = copy.deepcopy(self._asset(current, p.get("assetId")))
            project.assets = [asset]
            path = self._source(asset)
            raw = boolean(p.get("raw", False), "预览模式")
            editable = not raw and boolean(p.get("editable", False), "可编辑预览")
            layers_only = editable and boolean(p.get("layersOnly", False), "字幕图层预览")
            size = int(number(p.get("size", 1440), 160, 4096, "预览尺寸", True))
            overrides, texts = p.get("styles", {}), p.get("texts", {})
            if not isinstance(overrides, dict) or not isinstance(texts, dict) or len(overrides) > 64 or len(texts) > 64:
                raise CommandError("INVALID_INPUT", "字幕预览参数无效")
            captions = {c.id: c for c in asset.subtitles}
            if any(caption_id not in captions for caption_id in (*overrides, *texts)):
                raise CommandError("CAPTION_MISSING", "字幕已不存在")
            for caption_id, values in overrides.items():
                captions[caption_id].style_overrides.update(style_patch(values))
            for caption_id, text in texts.items():
                # Unsaved editor text renders live; nothing is written to the project here.
                captions[caption_id].text = text_value(text, "字幕")
        stat = path.stat()
        source_stamp = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        source_key = hashlib.sha256(repr((*source_stamp, size)).encode()).hexdigest()
        dimensions = None
        if editable:
            with self.preview_source_lock:
                source = self.preview_sources.get(source_stamp)
                if source is None:
                    with Image.open(path) as opened:
                        source = ImageOps.exif_transpose(opened).convert("RGBA")
                    if source.width * source.height * 4 <= 128 * 1024 * 1024:
                        self.preview_sources[source_stamp] = source
                if source_stamp in self.preview_sources:
                    self.preview_sources.move_to_end(source_stamp)
                while len(self.preview_sources) > 2 or sum(im.width * im.height * 4 for im in self.preview_sources.values()) > 128 * 1024 * 1024:
                    self.preview_sources.popitem(last=False)
        else:
            with Image.open(path) as opened:
                if raw:
                    dimensions = opened.size
                    if opened.getexif().get(274) in {5, 6, 7, 8}:
                        dimensions = dimensions[::-1]
                    opened.draft("RGB", (size, size))
                    opened.thumbnail((size, size), Image.Resampling.LANCZOS)
                source = ImageOps.exif_transpose(opened).convert("RGBA")
        dimensions = dimensions or source.size
        overlays, layers = [], []
        media = {}
        def encode(image, photo=False):
            image = image.copy()
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            stream = io.BytesIO()
            if photo and image.getchannel("A").getextrema()[0] == 255:
                # Opaque pixels only: JPEG encodes ~10x faster and ships ~5x smaller than PNG.
                image.convert("RGB").save(stream, format="JPEG", quality=92, subsampling=0)
            else:
                image.save(stream, format="PNG")
            token = uuid4().hex
            media[token] = stream.getvalue()
            return token
        background_token = encode(source, photo=True) if editable and (not layers_only or p.get("backgroundKey") != source_key) else None
        if not raw:
            # Planner must receive the exact project defaults, not a browser font approximation.
            render_project = copy.deepcopy(project); render_project.assets = [asset]
            plan = ExportPlanner().plan(render_project, ExportOptions(self.data_dir / "unused"))
            if not plan.items:
                raise CommandError("SOURCE_UNREADABLE", "图片无法读取")
            for request in plan.items[0].captions:
                validate_stored_style(request.style.to_mapping())
            source = RenderService().render(source, plan.items[0].captions, StyleSettings.from_mapping(project.default_style), geometry=overlays, layers=layers if editable else None, layers_only=layers_only)
            for caption, overlay in zip(asset.subtitles, overlays):
                overlay["id"] = caption.id
            for layer, overlay in zip(layers, overlays):
                overlay["layerToken"] = encode(layer)
        token = "" if layers_only else encode(source, photo=raw)
        if sum(map(len, media.values())) > 64 * 1024 * 1024:
            raise CommandError("PREVIEW_TOO_LARGE", "预览内容过大，请减少字幕数量或字号")
        with self.lock:
            self.media.update(media)
            while len(self.media) > 96 or sum(map(len, self.media.values())) > 64 * 1024 * 1024:
                self.media.popitem(last=False)
        return {"token": token, "backgroundToken": background_token, "sourceKey": source_key, "assetId": asset.id, "revision": project.revision, "width": dimensions[0], "height": dimensions[1], "overlays": overlays, "filename": asset.filename, "bytes": stat.st_size}

    def inspect_export(self, p):
        project = copy.deepcopy(self._require_project())
        if "assetIds" in p:
            ids = set(self._ids(project, p))
            project.assets = [a for a in project.assets if a.id in ids]
        output = self.outputs.get(p.get("outputToken"))
        if output is None:
            raise CommandError("OUTPUT_REQUIRED", "请选择输出文件夹")
        output = output.resolve()
        mode = NamingMode(choice(p.get("naming", "original"), ("original", "sequence"), "命名方式"))
        options = ExportOptions(output, naming_mode=mode, start_number=number(p.get("start", 1), 0, 999999, "起始序号", True), digits=number(p.get("digits", 2), 1, 8, "位数", True), prefix=text_value(p.get("prefix", ""), "前缀", 100), suffix=text_value(p.get("suffix", ""), "后缀", 100), include_no_caption=boolean(p.get("includeNoCaption", True), "无需字幕"), preserve_metadata=boolean(p.get("metadata", True), "元数据"), image_format=choice(p.get("format", "original"), ("original", "png", "jpg", "webp", "bmp"), "格式"), quality=number(p.get("quality", 95), 1, 100, "质量", True))
        inspected = OutputPreflight().inspect(project.assets, options)
        errors = [{"message": x, "assetIds": []} for x in inspected.errors]
        warnings = [{"message": x, "assetIds": []} for x in inspected.warnings]
        # One card per problem, not per file: 200 unconfirmed images are a single task in 校对.
        unconfirmed = [a for a in project.assets if a.caption_status in {CaptionStatus.MISSING, CaptionStatus.NEEDS_REVIEW}]
        if unconfirmed:
            errors.append({"message": f"{unconfirmed[0].filename} 的字幕尚未确认" if len(unconfirmed) == 1 else f"{len(unconfirmed)} 张图片的字幕尚未确认，例如 {unconfirmed[0].filename}", "assetIds": [a.id for a in unconfirmed]})
        for asset in project.assets:
            try:
                self._source(asset)
                for caption in asset.subtitles:
                    style = self._style(caption)
                    validate_stored_style(style)
                    if style.get("font_path"):
                        missing = {ord(c) for c in caption.text if not c.isspace()} - font_codepoints(style["font_path"], style.get("font_index", 0))
                        if missing:
                            errors.append({"message": f"{asset.filename} 的字体缺少 {len(missing)} 个字形，请替换字体", "assetIds": [asset.id]})
            except (CommandError, OSError) as error:
                errors.append({"message": str(error), "assetIds": [asset.id]})
        plan = ExportPlanner().plan(copy.deepcopy(project), options)
        errors.extend({"message": x, "assetIds": []} for x in plan.blocking_errors)
        # Images awaiting review already block above; the planner's per-file reminder would repeat it.
        repeated = {message for a in unconfirmed for message in (f"{a.filename} 的自动字幕结构需确认", f"{a.filename} 没有字幕")}
        warnings.extend({"message": x, "assetIds": []} for x in plan.warnings if x not in repeated)
        assets_by_path = {a.source_path: a for a in project.assets}
        blocked_ids = {identifier for error in errors for identifier in error["assetIds"]}
        renderer = RenderService()
        for item in plan.items:
            if not windows_filename(item.output_path.name):
                errors.append({"message": f"Windows 文件名不合法：{item.output_path.name}", "assetIds": []})
            if item.output_path.parent.resolve() != output:
                errors.append({"message": "输出文件名不能包含路径", "assetIds": []})
            asset = assets_by_path.get(item.source_path)
            if asset and asset.id not in blocked_ids:
                try:
                    with Image.open(self._source(asset)) as opened:
                        dimensions = opened.size
                        if opened.getexif().get(274) in {5, 6, 7, 8}:
                            dimensions = dimensions[::-1]
                    geometry = renderer.measure(dimensions, item.captions, item.style)
                    if any(g["overflow"] for g in geometry):
                        errors.append({"message": f"{asset.filename} 的字幕超出图片，请减小字号或调整位置", "assetIds": [asset.id]})
                    for i, first in enumerate(geometry):
                        x1, y1, x2, y2 = first["bounds"]
                        if any(min(x2, g["bounds"][2]) > max(x1, g["bounds"][0]) and min(y2, g["bounds"][3]) > max(y1, g["bounds"][1]) for g in geometry[i + 1:]):
                            warnings.append({"message": f"{asset.filename} 的字幕区域可能重叠，请检查位置", "assetIds": [asset.id]})
                            break
                except (ValueError, OSError) as error:
                    errors.append({"message": str(error), "assetIds": [asset.id]})
        if not plan.items:
            errors.append({"message": "没有可导出的图片", "assetIds": []})
        token = uuid4().hex
        self.preflight = {"id": token, "revision": project.revision, "plan": plan, "options": options, "errors": errors, "warnings": warnings}
        outputs = [{"assetId": assets_by_path[i.source_path].id, "file": i.output_path.name} for i in plan.items if i.source_path in assets_by_path]
        return {"id": token, "revision": project.revision, "errors": errors, "warnings": warnings, "files": [i.output_path.name for i in plan.items], "outputs": outputs, "count": len(plan.items)}

    def start_export(self, p):
        check = self.preflight
        if not check or check["id"] != p.get("preflightId") or check["revision"] != self._require_project().revision:
            raise CommandError("PREFLIGHT_EXPIRED", "预检已过期，请重新检查")
        if check["errors"]:
            raise CommandError("PREFLIGHT_BLOCKED", "请先解决预检问题")
        if check["warnings"] and p.get("acknowledge") is not True:
            raise CommandError("WARNINGS_REQUIRE_CONFIRMATION", "请确认导出提示")
        items = copy.deepcopy(check["plan"].items)
        for item in items:
            item.source_fingerprint = fingerprint(item.source_path)
        self.job = {"id": uuid4().hex, "revision": check["revision"], "state": "running", "items": items, "output_dir": check["options"].output_dir, "error": None}
        self._launch_job()
        return {"jobId": self.job["id"]}

    def _launch_job(self):
        self.stop_event.clear(); self.job["state"] = "running"; self.job["error"] = None
        self._save_manifest()
        threading.Thread(target=self._run_job, name="subtitle-export", daemon=True).start()

    def _save_manifest(self):
        job = self.job
        record = {"checkpointVersion": 1, "id": job["id"], "projectId": self.project.id, "revision": job["revision"], "outputDir": str(job["output_dir"]), "state": job["state"], "error": job["error"], "items": [ExportManifestStore._encode_item(i) for i in job["items"]]}
        self.trusted.save("active-job.json", record)
        # A digest prevents untrusted project IDs from becoming filesystem paths.
        key = hashlib.sha256(self.project.id.encode()).hexdigest()
        self.trusted.save(f"job-{key}.json", record)

    @staticmethod
    def _checkpoint_name(job_id, index):
        key = hashlib.sha256(job_id.encode()).hexdigest()
        return f"job-checkpoints/{key}/{index}.json"

    def _save_item_checkpoint(self, index):
        job = self.job
        self.trusted.save(self._checkpoint_name(job["id"], index), {
            "jobId": job["id"], "projectId": self.project.id, "revision": job["revision"],
            "index": index, "item": ExportManifestStore._encode_item(job["items"][index]),
        })

    def _recover_job(self):
        try:
            key = hashlib.sha256(self.project.id.encode()).hexdigest()
            saved = self.trusted.load(f"job-{key}.json") or self.trusted.load("active-job.json")
            if not saved or saved["projectId"] != self.project.id or saved["revision"] != self.project.revision:
                return
            items = [ExportManifestStore._decode_item(i) for i in saved["items"]]
            output = Path(saved["outputDir"]).resolve()
            for index, item in enumerate(items):
                if saved.get("checkpointVersion") == 1 and saved["state"] in {"running", "stopping"}:
                    checkpoint = self.trusted.load(self._checkpoint_name(saved["id"], index))
                    if checkpoint:
                        if (checkpoint["jobId"], checkpoint["projectId"], checkpoint["revision"], checkpoint["index"]) != (saved["id"], self.project.id, saved["revision"], index):
                            raise ValueError("任务检查点不匹配")
                        recovered = ExportManifestStore._decode_item(checkpoint["item"])
                        if (recovered.source_path, recovered.output_path, recovered.source_fingerprint) != (item.source_path, item.output_path, item.source_fingerprint):
                            raise ValueError("任务检查点文件映射不匹配")
                        items[index] = item = recovered
                if item.output_path.parent.resolve() != output or not windows_filename(item.output_path.name):
                    raise ValueError("输出路径校验失败")
                if item.status == JobItemStatus.RUNNING:
                    item.status = JobItemStatus.PENDING
                if item.output_path.is_file() and item.output_fingerprint and fingerprint(item.output_path) == item.output_fingerprint:
                    item.status = JobItemStatus.SUCCESS
                elif item.status == JobItemStatus.SUCCESS:
                    item.status = JobItemStatus.FAILED
                    item.error_message = "已导出的文件被移动或修改"
            complete = all(i.status == JobItemStatus.SUCCESS for i in items)
            self.job = {"id": saved["id"], "revision": saved["revision"], "state": "complete" if complete else "stopped", "items": items, "output_dir": output, "error": saved["error"], "recovered": not complete}
        except (ValueError, KeyError, TypeError, OSError):
            self.issues.append({"file": "导出记录", "message": "任务记录无法校验，请重新预检；现有输出不会被覆盖。"})

    def _run_job(self):
        job = self.job
        exporter = ExportService()
        try:
            for index, item in enumerate(job["items"]):
                if item.status == JobItemStatus.SUCCESS:
                    continue
                if self.stop_event.is_set():
                    break
                with self.lock:
                    item.status = JobItemStatus.RUNNING
                try:
                    if not self._authorized(item.source_path) or fingerprint(item.source_path) != item.source_fingerprint:
                        raise CommandError("SOURCE_CHANGED", "源图已变化，请重新预检")
                    def prepared(path):
                        with self.lock:
                            item.output_fingerprint = fingerprint(path)
                            self._save_item_checkpoint(index)
                    if item.copy_original and item.output_path.suffix == item.source_path.suffix.lower():
                        exporter.copy_original(item.source_path, item.output_path, on_ready=prepared)
                    else:
                        exporter.export_image(item.source_path, item.output_path, item.captions, item.style, preserve_metadata=item.preserve_metadata, quality=item.quality, jpeg_background=item.jpeg_background, on_ready=prepared)
                    item.output_fingerprint = fingerprint(item.output_path)
                except Exception as error:
                    with self.lock:
                        item.status = JobItemStatus.FAILED
                        item.error_message = str(error)
                else:
                    with self.lock:
                        item.status = JobItemStatus.SUCCESS
                self._save_item_checkpoint(index)
        except Exception as error:
            job["error"] = str(error)
        finally:
            with self.lock:
                job["state"] = "stopped" if self.stop_event.is_set() else "failed" if job["error"] or any(i.status != JobItemStatus.SUCCESS for i in job["items"]) else "complete"
                try:
                    self._save_manifest()
                except OSError as error:
                    job["error"] = f"任务记录未保存：{error}"

    def _check_job(self, p):
        if not self.job or self.job["id"] != p.get("jobId"):
            raise CommandError("JOB_MISSING", "导出任务不存在")

    def job_snapshot(self):
        if not self.job:
            return None
        job = self.job
        return {"id": job["id"], "state": job["state"], "revision": job["revision"], "outputDir": str(job["output_dir"]), "error": job["error"], "recovered": job.get("recovered", False), "items": [{"index": i, "file": item.output_path.name, "status": item.status.value, "error": item.error_message} for i, item in enumerate(job["items"])]}

    def output_preview(self, p):
        with self.lock:
            self._check_job(p)
            index = int(number(p.get("index"), 0, len(self.job["items"]) - 1, "输出图片", True))
            item = self.job["items"][index]
            if item.status != JobItemStatus.SUCCESS or not item.output_fingerprint or fingerprint(item.output_path) != item.output_fingerprint:
                raise CommandError("OUTPUT_CHANGED", "导出图片已移动或发生变化")
            with Image.open(item.output_path) as opened:
                result = ImageOps.exif_transpose(opened).convert("RGBA")
                result.thumbnail((640, 640), Image.Resampling.LANCZOS)
                stream = io.BytesIO(); result.save(stream, format="PNG")
            token = uuid4().hex
            self.media[token] = stream.getvalue()
            while len(self.media) > 48:
                self.media.popitem(last=False)
            return {"token": token}

    def font_preview(self, p):
        """The font's name drawn in the font itself, for the font list; rendered once per font, then cached."""
        font_id = p.get("fontId")
        entry = font_entries().get(font_id) if isinstance(font_id, str) else None
        if entry is None:
            raise CommandError("FONT_MISSING", "字体已不可用，请重新选择")
        token = f"font-{font_id}"
        with self.lock:
            if token in self.font_previews:
                return {"token": token}
        # A face that lacks the glyphs of its own name would draw boxes; the list shows the name as text instead.
        if {ord(c) for c in entry["label"] if not c.isspace()} - font_codepoints(entry["path"], entry["index"]):
            raise CommandError("FONT_PREVIEW_UNAVAILABLE", "这个字体不能显示自己的名称")
        font = RenderService()._font(StyleSettings(font_path=entry["path"], font_index=entry["index"], font_weight=entry["weight"]), 26)
        left, top, right, bottom = font.getbbox(entry["label"])
        image = Image.new("RGBA", (min(right - left, 640) + 4, 40))
        ImageDraw.Draw(image).text((2 - left, (40 - (bottom - top)) / 2 - top), entry["label"], font=font, fill=(0, 0, 0, 255))
        stream = io.BytesIO(); image.save(stream, format="PNG")
        with self.lock:
            # Kept apart from `media`, whose canvas previews come and go much faster.
            self.font_previews[token] = stream.getvalue()
            while len(self.font_previews) > 512:
                self.font_previews.popitem(last=False)
        return {"token": token}

    def media_bytes(self, token):
        with self.lock:
            return self.media.get(token) or self.font_previews.get(token)

    def recent_preview(self, p):
        with self.lock:
            entry = next((r for r in self.recents.list() if str(r.path) == p.get("path")), None)
            if entry is None or entry.path.stat().st_size > 32 * 1024 * 1024:
                raise CommandError("INVALID_PROJECT", "最近项目不可读")
            project = self.store._load_file(entry.path)
            if not project.assets:
                raise CommandError("EMPTY_PROJECT", "项目没有图片")
            path = self._source(project.assets[0])
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
            image.thumbnail((320, 320), Image.Resampling.LANCZOS)
            stream = io.BytesIO(); image.save(stream, format="PNG")
        with self.lock:
            token = uuid4().hex
            self.media[token] = stream.getvalue()
            while len(self.media) > 48:
                self.media.popitem(last=False)
        return {"token": token}
