import type { ReactNode } from 'react';
import { Popover } from '@base-ui/react/popover';
import { ToggleGroup } from '@base-ui/react/toggle-group';
import { Toggle } from '@base-ui/react/toggle';
import { AlignCenter, AlignLeft, AlignRight, Info, RotateCw, SlidersHorizontal } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Asset, Caption, RGBA, Style } from '../types';
import { aspectOf } from '../format';
import { Button, NumberField, Section, Segmented, Select, Switch, Tip } from './ui';
import { FontPicker, PresetSelect, WeightSelect } from './Pickers';
import { ColorRow } from './ColorPicker';
import { imagesOverriding, overriddenRows, percentOfReference, pxOnImage, ROW_KEYS, ROW_NAMES, shortEdge, storedFromImagePx, storedFromPercent, unifiedValueText, type Row, type Scope } from '../styleModel';

/** What the style sections edit: one caption (live preview, then commit) or many (mixed values, one batch write). */
export interface Target {
  batch: boolean;
  styles: Style[];
  get<K extends keyof Style>(key: K): Style[K] | undefined; // undefined: mixed
  preview<K extends keyof Style>(key: K, value: Style[K] | undefined): void;
  apply(patch: Partial<Style>): void;
  preset(name: string): void;
  position: { x?: number; y?: number; rotation?: number; manual?: boolean; captions: number; manualCount: number };
  previewPosition(key: 'x' | 'y' | 'rotation', value: number | undefined): void;
  applyPosition(values: { x?: number; y?: number; rotation?: number; maxWidth?: number }): void;
  layout(mode: 'smart' | 'manual'): void;
  positionsAllowed: boolean;
  /** 「全部图片」 or 「仅这条」; a batch writes each chosen image's own values (spec 4.1). */
  scope: Scope;
  rowOverridden(row: Row): boolean;
  restoreRow(row: Row): void;
  restoreAll(): void;
}
const ROWS = Object.keys(ROW_KEYS) as Row[];

const same = <T,>(values: T[]) => values.length > 0 && values.every(v => JSON.stringify(v) === JSON.stringify(values[0])) ? values[0] : undefined;

export function useSingleTarget(asset: Asset, caption: Caption): Target {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const drafts = w.styleDrafts[caption.id] ?? {};
  const placed = w.positionDrafts[caption.id] ?? {};
  const style = { ...caption.style, ...drafts };
  const rows = overriddenRows(caption.overrides);
  const restore = (keys?: readonly string[]) => act(() => mutate('style_restore', { scope: 'caption', assetId: asset.id, captionId: caption.id, ...(keys ? { keys } : {}) }));
  return {
    batch: false, styles: [style], positionsAllowed: true, scope: w.scope,
    get: key => style[key],
    preview: (key, value) => w.previewStyle(key, value, caption.id, w.scope),
    apply: patch => w.applyStyle(patch, caption, w.scope),
    preset: name => act(() => mutate('apply_preset', { assetId: asset.id, captionId: caption.id, name, scope: w.scope })),
    rowOverridden: row => rows.includes(row),
    restoreRow: row => restore(ROW_KEYS[row]),
    restoreAll: () => restore(),
    position: { x: placed.x ?? caption.position[0], y: placed.y ?? caption.position[1], rotation: placed.rotation ?? caption.rotation, manual: caption.manual, captions: 1, manualCount: caption.manual ? 1 : 0 },
    previewPosition: (key, value) => w.previewPosition(key, value, caption.id),
    applyPosition: values => w.applyPosition(values, caption),
    // 手动 pins the caption where it is; 智能避让 over a hand-placed caption asks first.
    layout: mode => mode === 'manual' ? w.applyPosition({}, caption) : caption.manual ? w.openDialog('smart') : w.rearrange(),
  };
}

export function useBatchTarget(scope: number | 'all'): Target {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const chosen = w.assets.filter(a => w.selection.includes(a.id));
  const captions = chosen.flatMap(a => scope === 'all' ? a.captions : a.captions.slice(scope, scope + 1));
  const styles = captions.map(c => c.style);
  const write = (payload: Record<string, unknown>) => act(async () => {
    const result = await mutate<{ updated?: string[]; skipped?: { id: string; reason: string }[]; started?: boolean; layoutWarnings?: unknown[] }>('batch_set', { assetIds: w.selection, captions: scope, ...payload });
    if (result.started) return;
    const skipped = result.skipped?.length ?? 0;
    if (skipped) w.toast({ text: `已修改 ${result.updated?.length ?? 0} 张，${skipped} 张没有对应的字幕，已跳过`, tone: 'warn' });
  });
  return {
    batch: true, styles, positionsAllowed: scope !== 'all', scope: 'caption',
    rowOverridden: () => false, restoreRow: () => {}, restoreAll: () => {},
    get: key => same(styles.map(s => s[key])) as never,
    preview: () => {},
    apply: patch => write({ style: patch }),
    preset: name => write({ preset: name }),
    position: {
      x: same(captions.map(c => Math.round(c.position[0] * 1000))) === undefined ? undefined : captions[0]?.position[0],
      y: same(captions.map(c => Math.round(c.position[1] * 1000))) === undefined ? undefined : captions[0]?.position[1],
      rotation: same(captions.map(c => c.rotation)), manual: same(captions.map(c => c.manual)), captions: captions.length, manualCount: captions.filter(c => c.manual).length,
    },
    previewPosition: () => {},
    applyPosition: ({ maxWidth, ...values }) => write(maxWidth === undefined ? { position: values } : { position: { ...values, maxWidth } }),
    layout: mode => { if (mode === 'smart') write({ layout: 'auto' }); },
  };
}

/** The blue dot before a field this caption keeps different from the unified style; hover to see it or undo it (spec 4.1). */
function OverrideDot({ target, row }: { target: Target; row: Row }) {
  const { state, fonts } = useApp();
  const w = useWorkspace();
  if (target.batch || !target.rowOverridden(row)) return null;
  const unified = state!.project!.style;
  const text = unifiedValueText(row, unified, { fontLabel: fonts.find(f => f.id === unified.font_id)?.label ?? null, reference: state!.project!.referenceEdge, edge: w.asset ? shortEdge(w.asset) : null });
  return <Popover.Root>
    <Popover.Trigger openOnHover delay={150} className="override-dot" aria-label={`${ROW_NAMES[row]}：单独修改`} />
    <Popover.Portal><Popover.Positioner className="positioner" side="top" sideOffset={6} collisionPadding={8}><Popover.Popup className="popover override-popover">
      <span>单独修改 · 统一样式是 {text}</span><button type="button" className="link" onClick={() => target.restoreRow(row)}>恢复</button>
    </Popover.Popup></Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}

/** 「另有 N 张单独改过…」: after a 「全部图片」 change, images that kept their own value (spec 4.1). */
function Exceptions({ target, rows }: { target: Target; rows: readonly Row[] }) {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const row = w.lastUnified;
  if (target.batch || !row || !rows.includes(row) || !w.asset || !w.caption) return null;
  const count = imagesOverriding(w.assets, row, { assetId: w.asset.id, captionId: w.caption.id });
  return count ? <div className="section-line"><small className="section-hint"><Info />另有 {count} 张单独改过{ROW_NAMES[row]}，没有跟着变</small>
    <button type="button" className="link" onClick={() => act(() => mutate('style_restore', { scope: 'field', keys: ROW_KEYS[row] }))}>全部恢复</button></div> : null;
}

/** 「应用到」 above 文字: it governs 文字、颜色、背景、效果; 位置 always belongs to the caption (spec 4.1). */
function ScopeBar() {
  const w = useWorkspace();
  return <section className="section open scope-section"><div className="section-inner">
    <div className="labelled-row"><span>应用到</span><Segmented label="应用到" value={w.scope} onChange={w.setScope} options={[{ value: 'all', label: '全部图片' }, { value: 'caption', label: '仅这条' }]} /></div>
    <small className="section-hint">{w.scope === 'all' ? '改动应用到所有图片，单独改过的除外' : '改动只影响这条字幕'}</small>
  </div></section>;
}

/** Where sizes are shown: the current picture; in a batch the current one if chosen, else the first chosen. */
function useSizing(target: Target) {
  const w = useWorkspace();
  const chosen = target.batch ? w.assets.filter(a => w.selection.includes(a.id)) : [];
  const image = target.batch ? (chosen.find(a => a.id === w.asset?.id) ?? chosen[0]) : w.asset;
  return { reference: w.project?.referenceEdge ?? null, edge: image ? shortEdge(image) : null };
}

/** 字号 as a share of the short edge with this picture's pixels beside it; fixed pixels in old projects (spec 4.2). */
function FontSizeField({ target, marker }: { target: Target; marker: ReactNode }) {
  const { reference, edge } = useSizing(target);
  const size = target.get('font_size');
  if (!reference) return <NumberField label="字号" marker={marker} prefix="字号" value={size ?? 0} mixed={size === undefined} min={8} max={512} unit="px"
    onPreview={v => target.preview('font_size', v)} onCommit={v => target.apply({ font_size: v })} />;
  return <NumberField label="字号" marker={marker} prefix="字号" value={percentOfReference(size ?? 0, reference)} mixed={size === undefined} digits={1} step={.1}
    min={Math.ceil(8 / reference * 1000) / 10} max={Math.floor(512 / reference * 1000) / 10} unit="%"
    hint={size === undefined ? undefined : `≈ ${Math.round(pxOnImage(size, reference, edge))} px`}
    onPreview={v => target.preview('font_size', v === undefined ? undefined : storedFromPercent(v, reference))} onCommit={v => target.apply({ font_size: storedFromPercent(v, reference) })} />;
}

/** Outline and spacing in this picture's pixels, stored at the reference edge (spec 4.2). */
function PixelField({ target, field, label, prefix, min, max, marker, className }: { target: Target; field: 'stroke_width' | 'line_spacing' | 'letter_spacing'; label: string; prefix?: ReactNode; min: number; max: number; marker?: ReactNode; className?: string }) {
  const { reference, edge } = useSizing(target);
  const stored = target.get(field);
  const fine = reference !== null && edge !== null;
  const shown = (value: number) => pxOnImage(value, reference, edge);
  return <NumberField label={label} prefix={prefix} marker={marker} className={className} unit="px" value={shown(stored ?? 0)} mixed={stored === undefined}
    digits={fine ? 1 : 0} step={fine ? .1 : 1} min={shown(min)} max={shown(max)}
    onPreview={v => target.preview(field, v === undefined ? undefined : storedFromImagePx(v, reference, edge))}
    onCommit={v => target.apply({ [field]: storedFromImagePx(v, reference, edge) })} />;
}

function MorePopover({ label, children }: { label: string; children: ReactNode }) {
  return <Popover.Root>
    <Tip label={label}><Popover.Trigger className="icon-button" aria-label={label}><SlidersHorizontal /></Popover.Trigger></Tip>
    <Popover.Portal><Popover.Positioner className="positioner" side="left" align="start" sideOffset={16} collisionPadding={12}><Popover.Popup className="popover more-popover">
      <Popover.Title className="popover-title">{label}</Popover.Title>{children}
    </Popover.Popup></Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}

export function PositionSection({ target, collapsed, onToggle }: { target: Target; collapsed?: boolean; onToggle?: () => void }) {
  const w = useWorkspace();
  const p = target.position;
  const alignment = target.get('alignment');
  const safe = target.get('safe_edge');
  const width = target.get('max_width');
  const chosen = target.batch ? w.assets.filter(a => w.selection.includes(a.id)) : [];
  const reference = w.asset && chosen.some(a => a.id === w.asset!.id) ? w.asset : chosen[0];
  const different = reference ? chosen.filter(a => aspectOf(a) !== undefined && aspectOf(reference) !== undefined && Math.abs(aspectOf(a)! - aspectOf(reference)!) > .01).length : 0;
  return <Section title="位置" collapsed={collapsed} onToggle={onToggle} actions={<MorePopover label="更多位置设置">
    <div className="switch-row"><span>旋转时吸附常用角度</span><Switch label="旋转时吸附常用角度" checked={w.rotationSnap} onChange={w.setRotationSnap} /></div>
    <small className="popover-hint">吸附 0°、±45°、±90°、180°，4° 内磁吸</small>
    <div className="switch-row"><span>显示安全边距参考线</span><Switch label="显示安全边距参考线" checked={w.safeGuide} onChange={w.setSafeGuide} /></div>
    {!target.batch && <Button variant="ghost" className="full-width" onClick={() => w.openDialog('reset', { scope: 'position' })}>恢复默认位置…</Button>}
  </MorePopover>}>
    <Segmented label="位置方式" value={p.manual === undefined ? null : p.manual ? 'manual' : 'smart'} onChange={mode => target.layout(mode)}
      options={[{ value: 'smart', label: '智能避让' }, { value: 'manual', label: '手动', disabled: target.batch, title: target.batch ? '拖动或输入 X、Y 即改为手动' : undefined }]} />
    <small className="section-hint">{p.manual === undefined ? `${p.manualCount} 条手动，${p.captions - p.manualCount} 条智能避让` : p.manual ? '拖动或输入数值调整；选「智能避让」与本图自动字幕一起排列' : '自动避开人物；拖动字幕后改为手动'}</small>
    <div className="field-grid">
      <NumberField label="水平位置" prefix="X" value={(p.x ?? 0) * 100} mixed={p.x === undefined} digits={1} step={.1} min={0} max={100} unit="%" disabled={!target.positionsAllowed}
        onPreview={v => target.previewPosition('x', v === undefined ? undefined : v / 100)} onCommit={v => target.applyPosition({ x: v / 100 })} />
      <NumberField label="垂直位置" prefix="Y" value={(p.y ?? 0) * 100} mixed={p.y === undefined} digits={1} step={.1} min={0} max={100} unit="%" disabled={!target.positionsAllowed}
        onPreview={v => target.previewPosition('y', v === undefined ? undefined : v / 100)} onCommit={v => target.applyPosition({ y: v / 100 })} />
      <NumberField label="换行宽度" prefix="宽" value={(width ?? .88) * 100} mixed={width === undefined} min={10} max={100} unit="%"
        onPreview={v => target.preview('max_width', v === undefined ? undefined : v / 100)} onCommit={v => target.applyPosition({ maxWidth: v / 100 })} />
      {/* Stored angles follow Pillow (counter-clockwise); people read clockwise as positive. */}
      <NumberField label="旋转" prefix={<RotateCw />} value={-(p.rotation ?? 0) || 0} mixed={p.rotation === undefined} digits={1} step={.1} min={-180} max={180} unit="°"
        onPreview={v => target.previewPosition('rotation', v === undefined ? undefined : -v || 0)} onCommit={v => target.applyPosition({ rotation: -v || 0 })} />
    </div>
    {!target.positionsAllowed && <small className="section-hint"><Info />范围是「所有字幕」时不能统一位置，请改为「每张第 N 条字幕」</small>}
    {different > 0 && <small className="section-hint"><Info />{different} 张宽高比不同，位置按比例换算</small>}
    <div className="align-row">
      <ToggleGroup value={alignment ? [alignment] : []} onValueChange={v => { if (v[0]) target.apply({ alignment: v[0] }); }} className="align-group" aria-label="对齐">
        {([['left', AlignLeft, '左对齐'], ['center', AlignCenter, '居中对齐'], ['right', AlignRight, '右对齐']] as const).map(([value, Icon, label]) => <Tip key={value} label={label}><Toggle value={value} aria-label={label} className="align-toggle"><Icon /></Toggle></Tip>)}
      </ToggleGroup>
      <div className="switch-row inline"><span>安全边距</span><Switch label="安全边距" checked={safe ?? false} onChange={v => target.apply({ safe_edge: v })} /></div>
    </div>
  </Section>;
}

export function TextSection({ target, onSavePreset, collapsed, onToggle }: { target: Target; onSavePreset?: () => void; collapsed?: boolean; onToggle?: () => void }) {
  const w = useWorkspace();
  const fontId = target.get('font_id');
  const fontMixed = !target.batch ? false : target.styles.length > 1 && fontId === undefined;
  const changed = ROWS.filter(row => target.rowOverridden(row)).length;
  const note = changed > 0 ? <span className="section-note">已单独修改 {changed} 项<button type="button" className="link" onClick={target.restoreAll}>恢复</button></span> : undefined;
  const reference = w.project?.referenceEdge ?? null;
  const strokeScale = (reference ?? (w.asset ? shortEdge(w.asset) : null) ?? 1080) / 1080;
  const presetHead = target.batch ? <div className="menu-head-row">应用到：<strong>已选 {w.selection.length} 张</strong></div>
    : <><div className="menu-head-row">应用到：<strong>{target.scope === 'all' ? '全部图片' : '仅这条'}</strong></div><small>{target.scope === 'all' ? '替换统一样式，单独改过的不变' : '只改这一条字幕'}</small></>;
  return <Section title="文字" note={note} collapsed={collapsed} onToggle={onToggle} actions={<MorePopover label="更多文字设置">
    <div className="field-grid">
      <PixelField target={target} field="line_spacing" label="行距" prefix="行距" min={0} max={200} marker={<OverrideDot target={target} row="line_spacing" />} />
      <PixelField target={target} field="letter_spacing" label="字间距" prefix="字距" min={-200} max={200} marker={<OverrideDot target={target} row="letter_spacing" />} />
      <NumberField label="倾斜" marker={<OverrideDot target={target} row="skew" />} prefix="倾斜" value={target.get('skew') ?? 0} mixed={target.get('skew') === undefined} min={0} max={30} unit="°" onPreview={v => target.preview('skew', v)} onCommit={v => target.apply({ skew: v })} />
    </div>
    <small className="popover-hint">字间距可以为负；倾斜时描边粗细保持均匀</small>
    {!target.batch && <Button variant="ghost" className="full-width" onClick={() => w.openDialog('reset', { scope: 'style' })}>恢复默认样式…</Button>}
  </MorePopover>}>
    <PresetSelect styles={target.styles} onApply={target.preset} onSave={onSavePreset} onManage={() => w.openDialog('presets')} header={presetHead} strokeScale={strokeScale} />
    <div className="dot-row"><OverrideDot target={target} row="font" /><FontPicker fontId={fontMixed ? undefined : fontId} mixed={fontMixed} onChange={id => target.apply({ font_id: id } as Partial<Style>)} /></div>
    {!target.batch && fontId === null && <small className="field-error">字体不可用，请选择替代字体；不会悄悄换字体导出</small>}
    <div className="field-grid">
      <WeightSelect fontId={fontMixed ? undefined : fontId} mixed={fontMixed} onChange={id => target.apply({ font_id: id } as Partial<Style>)} />
      <FontSizeField target={target} marker={<OverrideDot target={target} row="font_size" />} />
    </div>
    <Exceptions target={target} rows={['font', 'font_size', 'line_spacing', 'letter_spacing', 'skew']} />
  </Section>;
}

function color(target: Target, key: 'text_color' | 'stroke_color' | 'background_color', label: string, alpha = true) {
  const value = target.get(key);
  return <ColorRow label={label} value={(value ?? target.styles[0]?.[key] ?? [0, 0, 0, 255]) as RGBA} mixed={value === undefined} alpha={alpha}
    onPreview={c => target.preview(key, c)} onApply={c => target.apply({ [key]: c })} />;
}

export function ColorSection({ target, collapsed, onToggle }: { target: Target; collapsed?: boolean; onToggle?: () => void }) {
  return <Section title="颜色" collapsed={collapsed} onToggle={onToggle}>
    <div className="labelled-row"><span className="dot-anchor"><OverrideDot target={target} row="text_color" />文字</span>{color(target, 'text_color', '文字颜色')}</div>
    <div className="labelled-row"><span className="dot-anchor"><OverrideDot target={target} row="stroke" />描边</span>{color(target, 'stroke_color', '描边颜色', false)}
      <PixelField target={target} field="stroke_width" label="描边宽度" min={0} max={200} className="narrow" /></div>
    <Exceptions target={target} rows={['text_color', 'stroke']} />
  </Section>;
}

export function BackgroundSection({ target, collapsed, onToggle }: { target: Target; collapsed?: boolean; onToggle?: () => void }) {
  const shown = target.get('show_background');
  return <Section title="背景" collapsed={collapsed} onToggle={onToggle} added={onToggle ? undefined : shown !== false}
    onAdd={() => target.apply({ show_background: true })} onRemove={() => target.apply({ show_background: false })}>
    {shown === undefined && <small className="section-hint">部分图片有背景；修改会统一开启</small>}
    <div className="dot-row"><OverrideDot target={target} row="background" />{color(target, 'background_color', '字幕背景颜色')}</div>
    <Exceptions target={target} rows={['background']} />
  </Section>;
}

const effects = [{ value: 'shadow', label: '阴影' }, { value: 'glow', label: '发光' }, { value: 'outline', label: '轮廓' }, { value: 'relief', label: '浮雕' }];
export function EffectSection({ target, collapsed, onToggle }: { target: Target; collapsed?: boolean; onToggle?: () => void }) {
  const effect = target.get('effect');
  return <Section title="效果" collapsed={collapsed} onToggle={onToggle} added={onToggle ? undefined : effect !== 'none'}
    onAdd={() => target.apply({ effect: 'shadow' })} onRemove={() => target.apply({ effect: 'none' })}>
    <div className="dot-row"><OverrideDot target={target} row="effect" /><Select label="文字效果" value={effect && effect !== 'none' ? effect : ''} mixed={effect === undefined} options={effects} onChange={v => target.apply({ effect: v })} /></div>
    <Exceptions target={target} rows={['effect']} />
  </Section>;
}

export function StyleSections({ target, collapsible = false, onSavePreset }: { target: Target; collapsible?: boolean; onSavePreset?: () => void }) {
  const w = useWorkspace();
  const toggle = (name: string) => collapsible ? () => w.setOpenSection(w.openSection === name ? null : name) : undefined;
  const collapsed = (name: string) => collapsible ? w.openSection !== name : undefined;
  return <>
    <PositionSection target={target} collapsed={collapsed('位置')} onToggle={toggle('位置')} />
    {!target.batch && <ScopeBar />}
    <TextSection target={target} onSavePreset={onSavePreset} collapsed={collapsed('文字')} onToggle={toggle('文字')} />
    <ColorSection target={target} collapsed={collapsed('颜色')} onToggle={toggle('颜色')} />
    <BackgroundSection target={target} collapsed={collapsed('背景')} onToggle={toggle('背景')} />
    <EffectSection target={target} collapsed={collapsed('效果')} onToggle={toggle('效果')} />
  </>;
}
