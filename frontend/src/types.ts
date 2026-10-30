export type CaptionStatus = 'ready' | 'missing' | 'needs_review' | 'no_caption' | 'unreadable';
export type OrderMode = 'time' | 'time_desc' | 'filename' | 'import' | 'manual';
export type RGBA = [number, number, number, number];
export interface Style {
  font_size: number; font_family: string | null; font_id: string | null;
  text_color: RGBA; stroke_color: RGBA; background_color: RGBA;
  stroke_width: number; line_spacing: number; letter_spacing: number;
  show_background: boolean; effect: string; max_width: number; alignment: string; safe_edge: boolean;
  font_weight: number | null; skew: number;
  /** Short edge the pixel sizes are meant for; null keeps fixed pixels (projects from before 2026-10-30). */
  reference_edge?: number | null;
}
/** A built-in look; outline is either fixed pixels or a share of the caption's font size. */
export interface PresetCard {
  name: string; fontLabel: string | null; fontId: string | null; textColor: RGBA; showBackground: boolean;
  backgroundAlpha: number; effect: string; skew: number; strokeRatio: number | null; strokeWidth: number | null;
}
/** `overrides`: the appearance fields this caption keeps different from the unified style. */
export interface Caption { id: string; text: string; source: string; speaker: string; position: [number, number]; manual: boolean; rotation: number; style: Style; overrides: string[] }
export interface Asset {
  id: string; filename: string; sourcePath: string; createdAt: string; modifiedAt: string;
  /** When the picture was taken: EXIF, else the earlier file time (a Windows copy keeps only its modification time). */
  takenAt: string | null; captureTime: string; timeSource: 'exif' | 'created' | 'modified'; timeTie: boolean;
  width: number | null; height: number | null;
  importOrder: number; kind: string; status: CaptionStatus; captions: Caption[];
}
/** `style` is the unified style every caption follows unless it has its own value. */
export interface Project { id: string; name: string; revision: number; path: string; assets: Asset[]; speakers: string[]; orderMode: OrderMode; style: Style; referenceEdge: number | null; showSpeaker: boolean }
export interface Job { recovered?: boolean; id: string; state: string; revision: number; outputDir: string; error: string | null; items: { index: number; file: string; status: string; error: string | null }[] }
export interface BatchTask { id: string; state: string; completed: number; total: number; filename: string; error: string | null; result: { updated: number; warnings: number; skipped: number; warningAssets: { assetId: string; message: string }[] } | null }
export interface ImportTask { id: string; state: 'running' | 'stopping' | 'complete' | 'cancelled' | 'failed'; completed: number; total: number; current: string; error: string | null; result: { imported: number; duplicates: number; issues: number } | null }
/** In-app update (src/subtitle_app/updater.py); only installed Windows builds are `supported`. */
export interface Update {
  current: string; supported: boolean; auto: boolean; version: string | null; notes: string | null; received: number; total: number; error: string | null;
  state: 'idle' | 'checking' | 'latest' | 'available' | 'downloading' | 'ready' | 'installing' | 'failed';
}
export interface Snapshot {
  projectUnchanged?: boolean;
  batchTask?: BatchTask | null; importTask?: ImportTask | null;
  pendingDrop?: { id: string; count: number; folders: boolean } | null; project: Project | null; saveError: string | null; canUndo: boolean; canRedo: boolean;
  issues: { file: string; message: string }[]; recents: { index: number; path: string; name: string; count: number; updatedAt: string; page: string }[];
  presets: string[]; builtinPresets: PresetCard[]; defaultPreset: string | null; job: Job | null; desktop: boolean; closeRequested: boolean; update: Update;
}
export interface Font { id: string; family: string; label: string; variant: string; index: number; weight: number | null; bundled: boolean }
export interface Preview { token: string; backgroundToken?: string; sourceKey?: string; assetId: string; revision: number; width: number; height: number; filename: string; bytes: number; overlays: { id: string; x: number; y: number; width: number; height: number; renderWidth: number; rotation: number; layerToken?: string }[] }
export interface Issue { message: string; assetIds: string[] }
export interface Preflight { id: string; revision: number; errors: Issue[]; warnings: Issue[]; files: string[]; outputs: { assetId: string; file: string }[]; count: number }
export interface Reply<T> { ok: boolean; result: T; state?: Snapshot; error?: { code: string; message: string; affectedIds: string[] } }
