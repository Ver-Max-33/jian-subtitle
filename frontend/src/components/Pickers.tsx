import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Combobox } from '@base-ui/react/combobox';
import { Check, ChevronDown, FolderOpen, Plus, Search } from 'lucide-react';
import { mediaUrl, request } from '../bridge';
import { useApp } from '../state';
import type { Font, PresetCard, Style } from '../types';
import { Select } from './ui';

const weightNames: Record<string, string> = { thin: '极细', hairline: '极细', ultralight: '特细', extralight: '特细', light: '细体', regular: '常规', normal: '常规', book: '常规', roman: '常规', medium: '中等', semibold: '半粗', demibold: '半粗', bold: '粗体', extrabold: '特粗', ultrabold: '特粗', heavy: '超粗', black: '超粗', italic: '斜体', oblique: '斜体' };
export const weightLabel = (variant: string) => variant.split(/\s+/).map(w => weightNames[w.toLowerCase()] || w).join(' ');
// Hidden system faces (".SF NS") and symbol sets cannot set caption text.
const unusable = (family: string) => family.startsWith('.') || /emoji|symbol|wingdings|webdings|marlett|lastresort|dingbats/i.test(family);

function recentFonts(): string[] {
  try { const saved: unknown = JSON.parse(localStorage.getItem('jian-recent-fonts') || '[]'); return Array.isArray(saved) ? saved.filter((v): v is string => typeof v === 'string').slice(0, 5) : []; }
  catch { return []; }
}
function rememberFont(family: string) {
  try { localStorage.setItem('jian-recent-fonts', JSON.stringify([family, ...recentFonts().filter(f => f !== family)].slice(0, 5))); } catch { /* Private webviews may refuse storage. */ }
}

/** The font's own name in its own face, drawn by the backend (P1); plain text until it arrives or if it cannot. */
const faceImages = new Map<string, Promise<string>>();
function FontName({ font }: { font: Font }) {
  const [url, setUrl] = useState<string>();
  const element = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let alive = true;
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(e => e.isIntersecting)) return;
      observer.disconnect();
      // '' remembers a face that cannot draw its own name, so the plain label stays without asking again.
      if (!faceImages.has(font.id)) faceImages.set(font.id, request<{ token: string }>('font_preview', { fontId: font.id }).then(r => mediaUrl(r.result.token)).catch(() => ''));
      void faceImages.get(font.id)!.then(next => { if (alive && next) setUrl(next); });
    });
    if (element.current) observer.observe(element.current);
    return () => { alive = false; observer.disconnect(); };
  }, [font.id]);
  return <span ref={element} className="font-name">{url ? <img src={url} alt={font.label} draggable={false} /> : font.label}</span>;
}

interface Family { family: string; label: string; font: Font; hint?: string }
export function FontPicker({ fontId, onChange, mixed = false }: { fontId: string | null | undefined; onChange: (fontId: string) => void; mixed?: boolean }) {
  const { fonts } = useApp();
  const [query, setQuery] = useState('');
  const current = fonts.find(f => f.id === fontId);
  const families = new Map<string, Font[]>();
  for (const f of fonts) families.set(f.family, [...(families.get(f.family) ?? []), f]);
  const recent = recentFonts().filter(f => families.has(f));
  const regular = (list: Font[]) => list.find(f => f.weight === 400 || /^(regular|normal)$/i.test(f.variant)) ?? list[0];
  const items: Family[] = [...families.entries()].filter(([family]) => family === current?.family || !unusable(family))
    .map(([family, list]) => ({ family, label: list[0].label, font: regular(list), hint: recent.includes(family) ? '最近使用' : list[0].bundled ? '内置' : list[0].label !== family ? family : undefined }))
    .sort((a, b) => (recent.includes(a.family) ? recent.indexOf(a.family) : 99) - (recent.includes(b.family) ? recent.indexOf(b.family) : 99) || a.label.localeCompare(b.label, 'zh-CN'));
  const selected = items.find(i => i.family === current?.family) ?? null;
  const choose = (item: Family) => {
    // Keep the weight across families when the new one has it; otherwise its Regular.
    const list = families.get(item.family)!;
    const target = current?.weight ? list.reduce((best, f) => Math.abs((f.weight ?? 400) - current.weight!) < Math.abs((best.weight ?? 400) - current.weight!) ? f : best, regular(list)) : regular(list);
    rememberFont(item.family); onChange(target.id);
  };
  return <Combobox.Root items={items} value={selected} inputValue={query} onInputValueChange={setQuery} onOpenChange={() => setQuery('')} onValueChange={v => { if (v) choose(v); }}
    itemToStringLabel={i => i.label} itemToStringValue={i => i.family} isItemEqualToValue={(a, b) => a.family === b.family}
    filter={(i, q) => `${i.label} ${i.family}`.toLocaleLowerCase().includes(q.trim().toLocaleLowerCase())}>
    <Combobox.Trigger className={`field select ${!mixed && fontId === null ? 'invalid' : ''}`} aria-label="字体"><span className={`field-value ${mixed || !current ? 'placeholder' : ''}`}>{mixed ? '混合' : current?.label ?? '字体不可用，选择替代'}</span><ChevronDown className="field-chevron" /></Combobox.Trigger>
    <Combobox.Portal><Combobox.Positioner className="positioner" side="left" align="start" sideOffset={12} collisionPadding={12}><Combobox.Popup className="popover font-popover">
      <div className="popover-search"><Search /><Combobox.Input placeholder="搜索字体，中英文名都可以" aria-label="搜索字体" /></div>
      <Combobox.Empty className="font-empty"><strong>没有找到「{query.trim()}」</strong><small>这台电脑没有安装，试试其他名称</small></Combobox.Empty>
      <Combobox.List className="font-list">{(item: Family) => <Combobox.Item key={item.family} value={item} className="menu-item font-item">
        <span className="menu-check"><Combobox.ItemIndicator><Check /></Combobox.ItemIndicator></span><FontName font={item.font} />{item.hint && <small className="menu-hint">{item.hint}</small>}
      </Combobox.Item>}</Combobox.List>
    </Combobox.Popup></Combobox.Positioner></Combobox.Portal>
  </Combobox.Root>;
}

export function WeightSelect({ fontId, onChange, mixed = false }: { fontId: string | null | undefined; onChange: (fontId: string) => void; mixed?: boolean }) {
  const { fonts } = useApp();
  const current = fonts.find(f => f.id === fontId);
  const variants = current ? fonts.filter(f => f.family === current.family).sort((a, b) => (a.weight ?? 400) - (b.weight ?? 400)) : [];
  return <Select label="字重" value={current?.id ?? ''} mixed={mixed} disabled={!variants.length} placeholder="字重" options={variants.map(v => ({ value: v.id, label: weightLabel(v.variant) }))} onChange={onChange} />;
}

interface SpeakerItem { value: string; label: string; add?: boolean }
/** Type to filter; a name that is not on the list is offered as 「添加「…」为说话人」 right there (P3). */
export function SpeakerPicker({ value, speakers, onChange, onImport, mixed = false }: { value: string; speakers: string[]; onChange: (speaker: string) => void; onImport: () => void; mixed?: boolean }) {
  const [query, setQuery] = useState('');
  const typed = query.trim();
  const items: SpeakerItem[] = [{ value: '', label: '未设置' }, ...speakers.map(s => ({ value: s, label: s })),
    ...(typed && !speakers.includes(typed) && typed !== '未设置' ? [{ value: typed, label: `添加「${typed}」为说话人`, add: true }] : [])];
  const selected = mixed ? null : items.find(i => !i.add && i.value === value) ?? null;
  return <Combobox.Root items={items} value={selected} inputValue={query} onInputValueChange={setQuery} onOpenChange={() => setQuery('')} onValueChange={v => { if (v) onChange(v.value); }}
    itemToStringLabel={i => i.label} itemToStringValue={i => i.value} isItemEqualToValue={(a, b) => a.value === b.value && !!a.add === !!b.add}
    filter={(i, q) => i.add || i.label.toLocaleLowerCase().includes(q.trim().toLocaleLowerCase())}>
    <Combobox.Trigger className="field select" aria-label="说话人"><span className={`field-value ${mixed || !value ? 'placeholder' : ''}`}>{mixed ? '混合' : value || '未设置'}</span><ChevronDown className="field-chevron" /></Combobox.Trigger>
    <Combobox.Portal><Combobox.Positioner className="positioner" sideOffset={4} align="start" collisionPadding={12}><Combobox.Popup className="popover speaker-popover">
      <div className="popover-search"><Search /><Combobox.Input placeholder="输入姓名" aria-label="搜索或添加说话人" maxLength={80} /></div>
      <Combobox.List className="speaker-list">{(item: SpeakerItem) => <Combobox.Item key={`${item.add ? '+' : ''}${item.value}`} value={item} className={`menu-item ${item.add ? 'add-item' : ''}`}>
        <span className="menu-check">{item.add ? <Plus /> : <Combobox.ItemIndicator><Check /></Combobox.ItemIndicator>}</span><span className={`menu-label ${item.value ? '' : 'placeholder'}`}>{item.label}</span>
      </Combobox.Item>}</Combobox.List>
      <button type="button" className="popover-footer" onClick={onImport}><FolderOpen />从 TXT 导入名单…</button>
    </Combobox.Popup></Combobox.Positioner></Combobox.Portal>
  </Combobox.Root>;
}

const hex = (c: number[]) => `rgb(${c[0]},${c[1]},${c[2]})`;
export function PresetBadge({ card }: { card?: PresetCard }) {
  return <span className="preset-badge" style={card ? { color: hex(card.textColor), background: card.showBackground ? 'var(--inverse)' : 'var(--fill-strong)', fontStyle: card.skew ? 'italic' : undefined } : undefined}>字</span>;
}
// Mirrors caption_presets.apply_builtin: a look reads as applied only while the caption still wears it.
// Fixed outlines are defined at 1080 and scaled like every size (`strokeScale` = this project's sizes ÷ 1080).
export const wearsPreset = (card: PresetCard, s: Style, strokeScale = 1) => s.show_background === card.showBackground
  && (!card.showBackground || s.background_color[3] === card.backgroundAlpha)
  && s.effect === card.effect && s.skew === card.skew && s.text_color.join() === card.textColor.join()
  && Math.abs(s.stroke_width - (card.strokeRatio === null ? (card.strokeWidth ?? 0) * strokeScale : Math.round(card.strokeRatio * s.font_size))) < .01
  && (card.fontId === null || s.font_id === card.fontId);

export function PresetSelect({ styles, onApply, onSave, onManage, header, strokeScale = 1 }: { styles: Style[]; onApply: (name: string) => void; onSave?: () => void; onManage: () => void; header?: ReactNode; strokeScale?: number }) {
  const { state } = useApp();
  const cards = state!.builtinPresets;
  const worn = cards.filter(card => styles.length > 0 && styles.every(s => wearsPreset(card, s, strokeScale))).map(c => c.name)[0];
  const mixed = styles.length > 1 && !worn && cards.some(card => styles.some(s => wearsPreset(card, s, strokeScale)));
  const options = [
    ...cards.map(card => ({ value: card.name, label: <span className="preset-option"><PresetBadge card={card} />{card.name}</span>, hint: card.fontLabel ?? undefined })),
    ...state!.presets.map(name => ({ value: name, label: <span className="preset-option"><PresetBadge />{name}</span>, hint: state!.defaultPreset === name ? '新项目默认' : '我的预设' })),
    ...(onSave ? [{ value: '__save', label: '存为新预设…' }] : []), { value: '__manage', label: '管理预设…' },
  ];
  return <Select label="预设" prefix="预设" value={worn ?? ''} mixed={mixed} placeholder="自定义" options={options} header={header}
    onChange={v => v === '__manage' ? onManage() : v === '__save' ? onSave?.() : onApply(v)} />;
}
