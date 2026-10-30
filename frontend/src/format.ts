import type { Asset, CaptionStatus, OrderMode } from './types';

export const statusNames: Record<CaptionStatus, string> = { ready: '已确认', missing: '待补字幕', needs_review: '需检查', no_caption: '无需字幕', unreadable: '无法读取' };
// 'issue': the images an export check sent the user to (「去处理」), whatever their status.
export type Filter = 'all' | 'issue' | CaptionStatus;
export const filterOrder: Filter[] = ['all', 'ready', 'missing', 'needs_review', 'no_caption', 'unreadable'];
export const filterNames: Record<Filter, string> = { all: '全部', issue: '导出问题', ...statusNames };
/** What the speaker becomes on export (spec 4.7): 「小林：…」 in front of the caption, or only a record. */
export const speakerHint = (show: boolean, name?: string) => !show ? '只作记录，不显示在字幕里' : name ? `导出时显示为「${name}：…」` : '导出时在字幕前加「说话人：」';
// "拍摄时间", not "创建时间": a copy made in Explorer gets a new creation time, the picture does not.
export const orderNames: Record<OrderMode, string> = { time: '拍摄时间 ↑', time_desc: '拍摄时间 ↓', filename: '文件名自然顺序', import: '导入顺序', manual: '手动顺序' };
export const timeSourceNames = { exif: '照片里记录的拍摄时间', created: '文件创建时间', modified: '文件修改时间（复制过的文件保留这个时间）' };

export const two = (n: number) => String(n).padStart(2, '0');
export const count = (n: number) => n.toLocaleString('zh-CN');
export const isUnresolved = (a: Asset) => a.status === 'missing' || a.status === 'needs_review';
export const aspectOf = (a: Asset) => (a.width && a.height ? a.width / a.height : undefined);
export const sameAspect = (a: Asset, b: Asset) => { const x = aspectOf(a), y = aspectOf(b); return x !== undefined && y !== undefined && Math.abs(x - y) <= 0.01; };

/** Search covers captions, the original filename and speakers; the list keeps its order (L1). */
export function inView(a: Asset, filter: Filter, query: string, issues?: ReadonlySet<string>) {
  if (filter === 'issue' ? !issues?.has(a.id) : filter !== 'all' && a.status !== filter) return false;
  const needle = query.trim().toLocaleLowerCase();
  return !needle || `${a.filename}\n${a.captions.map(c => `${c.text}\n${c.speaker}`).join('\n')}`.toLocaleLowerCase().includes(needle);
}

const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
export function shortTime(value: string) {
  const d = new Date(value);
  return `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}
export function fullTime(value: string) {
  const d = new Date(value);
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}
export function dayTime(value: string) {
  const d = new Date(value), days = Math.round((day(new Date()) - day(d)) / 86400000);
  const clock = `${two(d.getHours())}:${two(d.getMinutes())}`;
  return days === 0 ? `今天 ${clock}` : days === 1 ? `昨天 ${clock}` : `${two(d.getMonth() + 1)}-${two(d.getDate())} ${clock}`;
}
export function formatName(filename: string) {
  const extension = filename.split('.').pop()?.toUpperCase() || '';
  return extension === 'JPG' ? 'JPEG' : extension;
}
export const sourceName = (source: string) => (source === 'manual' ? '手动填写' : source === 'imported' ? '导入文本' : '来自文件名');
export const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`;

export const defaultExportOptions = { naming: 'original', format: 'original', start: 1, digits: 2, prefix: '', suffix: '', quality: 95, metadata: true, includeNoCaption: true, collection: 'all' };
export type ExportOptions = typeof defaultExportOptions;
