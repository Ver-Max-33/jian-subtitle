// Unified style and sizes relative to the picture (spec 4.1, 4.2). Plain functions, type-only imports:
// `node --experimental-strip-types --test "frontend/tests/*.test.ts"` runs them without a bundler.
import type { Asset, Style } from './types';

/** Fields of the 位置 block: they always belong to the caption, whatever the scope. */
export const POSITION_KEYS: readonly string[] = ['max_width', 'alignment', 'safe_edge'];

/** 「全部图片」 writes the unified style; 「仅这条」 an exception for one caption. */
export type Scope = 'all' | 'caption';
/** One line of the style sections; a font is its file, family, face and weight together. */
export type Row = 'font' | 'font_size' | 'text_color' | 'stroke' | 'background' | 'effect' | 'line_spacing' | 'letter_spacing' | 'skew';

export const ROW_KEYS: Record<Row, readonly string[]> = {
  font: ['font_path', 'font_family', 'font_index', 'font_weight'],
  font_size: ['font_size'],
  text_color: ['text_color'],
  stroke: ['stroke_color', 'stroke_width'],
  background: ['show_background', 'background_color'],
  effect: ['effect'],
  line_spacing: ['line_spacing'],
  letter_spacing: ['letter_spacing'],
  skew: ['skew'],
};
export const ROW_NAMES: Record<Row, string> = {
  font: '字体', font_size: '字号', text_color: '文字颜色', stroke: '描边', background: '背景', effect: '效果', line_spacing: '行距', letter_spacing: '字距', skew: '倾斜',
};
const ROWS = Object.keys(ROW_KEYS) as Row[];

export function rowOfKey(key: string): Row | undefined {
  return key === 'font_id' ? 'font' : ROWS.find(row => ROW_KEYS[row].includes(key));
}

export function overriddenRows(overrides: readonly string[]): Row[] {
  return ROWS.filter(row => ROW_KEYS[row].some(key => overrides.includes(key)));
}

/** 「另有 N 张单独改过…」: images with another caption that keeps its own value for this row. */
export function imagesOverriding(assets: readonly Asset[], row: Row, current: { assetId: string; captionId: string }): number {
  const keys = ROW_KEYS[row];
  return assets.filter(a => a.captions.some(c => c.id !== current.captionId && c.overrides.some(key => keys.includes(key)))).length;
}

export function shortEdge(asset: Pick<Asset, 'width' | 'height'>): number | null {
  return asset.width && asset.height ? Math.min(asset.width, asset.height) : null;
}

const rounded = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;
export const percentOfReference = (stored: number, reference: number) => rounded(stored / reference * 100, 1);
export const storedFromPercent = (percent: number, reference: number) => rounded(percent * reference / 100, 2);
/** Stored sizes are pixels at the reference edge; without a reference or a known size they are this picture's pixels. */
export const pxOnImage = (stored: number, reference: number | null, edge: number | null) => (reference && edge ? rounded(stored * edge / reference, 1) : stored);
export const storedFromImagePx = (px: number, reference: number | null, edge: number | null) => (reference && edge ? rounded(px * reference / edge, 2) : px);

const EFFECT_NAMES: Record<string, string> = { none: '无', shadow: '阴影', glow: '发光', outline: '轮廓', relief: '浮雕' };
const hexOf = (c: readonly number[]) => c.slice(0, 3).map(v => v.toString(16).padStart(2, '0')).join('').toUpperCase();
const plain = (value: number) => String(Number(value.toFixed(1)));
/** 「单独修改 · 统一样式是 …」: the unified value in the units the field shows. */
export function unifiedValueText(row: Row, style: Style, { fontLabel, reference, edge }: { fontLabel: string | null; reference: number | null; edge: number | null }): string {
  const px = (value: number) => `${plain(pxOnImage(value, reference, edge))} px`;
  switch (row) {
    case 'font': return fontLabel ?? '原字体';
    case 'font_size': return reference ? `${percentOfReference(style.font_size, reference).toFixed(1)}%` : px(style.font_size);
    case 'text_color': return hexOf(style.text_color);
    case 'stroke': return `${px(style.stroke_width)} · ${hexOf(style.stroke_color)}`;
    case 'background': return style.show_background ? hexOf(style.background_color) : '关';
    case 'effect': return EFFECT_NAMES[style.effect] ?? style.effect;
    case 'line_spacing': return px(style.line_spacing);
    case 'letter_spacing': return px(style.letter_spacing);
    case 'skew': return `${plain(style.skew)}°`;
  }
}

export interface Rect { left: number; top: number; right: number; bottom: number }
export type Corner = 'top-right' | 'bottom-right' | 'top-left' | 'bottom-left';
/** The caption frame's rotate knob (20 px, 4 px off a corner) and its tag (18 px, above or below) go where there is
 * room; the top-right corner first, since captions stack upward from the bottom of the picture (spec 4.8). */
export function chromeCorners(frame: Rect, viewport: Rect): { knob: Corner; tag: 'above' | 'below' } {
  const fits: Record<Corner, boolean> = {
    'top-right': frame.right + 24 <= viewport.right && frame.top - 24 >= viewport.top,
    'bottom-right': frame.right + 24 <= viewport.right && frame.bottom + 24 <= viewport.bottom,
    'top-left': frame.left - 24 >= viewport.left && frame.top - 24 >= viewport.top,
    'bottom-left': frame.left - 24 >= viewport.left && frame.bottom + 24 <= viewport.bottom,
  };
  return { knob: (Object.keys(fits) as Corner[]).find(corner => fits[corner]) ?? 'top-right', tag: frame.top - 22 >= viewport.top ? 'above' : 'below' };
}
