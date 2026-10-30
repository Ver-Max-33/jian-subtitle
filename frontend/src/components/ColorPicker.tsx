import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import { Popover } from '@base-ui/react/popover';
import { Check } from 'lucide-react';
import type { RGBA } from '../types';
import { Button, NumberField } from './ui';

type Hsv = [number, number, number];
const swatches = [
  ['#FFFFFF', '白色'], ['#1E1E1E', '深灰'], ['#000000', '黑色'], ['#FFDC41', '黄色'], ['#FFF3CD', '浅黄'],
  ['#BFDBFE', '浅蓝'], ['#0A74DE', '蓝色'], ['#24704B', '绿色'], ['#D93025', '红色'], ['#748AB0', '灰蓝'],
] as const;
export const hexOf = (c: RGBA) => '#' + c.slice(0, 3).map(x => x.toString(16).padStart(2, '0')).join('').toUpperCase();
const rgbaOf = (hex: string, alpha: number): RGBA => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), Math.round(alpha / 100 * 255)];
const names: Record<string, string> = Object.fromEntries(swatches.map(([c, n]) => [c, n]));
const light = (hex: string) => { const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)); return r * .299 + g * .587 + b * .114 > 186; };

function recentColors(): string[] {
  try { const saved: unknown = JSON.parse(localStorage.getItem('jian-recent-colors') || '[]'); return Array.isArray(saved) ? saved.filter((v): v is string => typeof v === 'string' && validHex(v)).slice(0, 5) : []; }
  catch { return []; }
}
function rememberColor(hex: string) {
  try { localStorage.setItem('jian-recent-colors', JSON.stringify([hex, ...recentColors().filter(c => c !== hex)].slice(0, 5))); } catch { /* Private webviews may refuse storage. */ }
}

/**
 * One colour row of the inspector: swatch, HEX and opacity. The popover is a draft: every change previews on the
 * real caption raster, 应用颜色 commits once (one undo), Esc / 取消 / clicking outside restores (P2).
 */
export function ColorRow({ label, value, mixed = false, onPreview, onApply, alpha = true }: { label: string; value: RGBA; mixed?: boolean; onPreview: (color?: RGBA) => void; onApply: (color: RGBA) => void; alpha?: boolean }) {
  const [open, setOpen] = useState(false);
  const [color, setColor] = useState(hexOf(value));
  const [opacity, setOpacity] = useState(Math.round(value[3] / 255 * 100));
  const [recent, setRecent] = useState<string[]>([]);
  const valid = validHex(color);
  const change = (next: string, a = opacity) => { setColor(next); setOpacity(a); if (validHex(next)) onPreview(rgbaOf(next.toUpperCase(), a)); };
  const toggle = (next: boolean) => {
    if (next) { setColor(hexOf(value)); setOpacity(Math.round(value[3] / 255 * 100)); setRecent(recentColors()); } else onPreview(undefined);
    setOpen(next);
  };
  const apply = () => { const hex = color.toUpperCase(); rememberColor(hex); onApply(rgbaOf(hex, opacity)); setOpen(false); };
  return <Popover.Root open={open} onOpenChange={toggle}>
    <Popover.Trigger className="field color-field" aria-label={`${label}：${mixed ? '混合' : `${names[hexOf(value)] || hexOf(value)}，不透明度 ${Math.round(value[3] / 255 * 100)}%`}`}>
      <span className={`swatch ${mixed ? 'mixed' : ''}`} style={mixed ? undefined : { '--swatch': hexOf(value), '--swatch-alpha': value[3] / 255 } as CSSProperties} />
      <span className={`field-value numeric ${mixed ? 'placeholder' : ''}`}>{mixed ? '混合' : hexOf(value).slice(1)}</span>
      {alpha && !mixed && <span className="field-suffix numeric">{Math.round(value[3] / 255 * 100)}%</span>}
    </Popover.Trigger>
    <Popover.Portal><Popover.Positioner className="positioner" side="left" align="start" sideOffset={16} collisionPadding={12}><Popover.Popup className="popover color-popover">
      <Popover.Title className="popover-title">{label}</Popover.Title>
      <ColorPicker color={color} onChange={hex => change(hex)} />
      <div className="swatches" role="group" aria-label="常用颜色">{swatches.map(([c, name]) => <button type="button" key={c} title={`${name} ${c}`} aria-label={`${name} ${c}`} aria-pressed={c === color.toUpperCase()} onClick={() => change(c)} style={{ '--swatch': c } as CSSProperties}>{c === color.toUpperCase() && <Check style={{ color: light(c) ? '#1E1E1E' : '#FFFFFF' }} />}</button>)}</div>
      {recent.length > 0 && <><small className="popover-label">最近使用</small><div className="swatches" role="group" aria-label="最近使用的颜色">{recent.map(c => <button type="button" key={c} title={c} aria-label={`最近使用 ${c}`} onClick={() => change(c)} style={{ '--swatch': c } as CSSProperties} />)}</div></>}
      <div className="color-values">
        <label className={`field ${valid ? '' : 'invalid'}`}><span className="field-prefix">HEX</span><input value={color} aria-label="十六进制颜色" maxLength={7} spellCheck={false} autoComplete="off" aria-invalid={!valid} onChange={e => change(e.target.value.startsWith('#') ? e.target.value : `#${e.target.value}`)} /></label>
        {alpha && <NumberField label="不透明度" prefix="不透明" value={opacity} min={0} max={100} unit="%" onPreview={a => { if (a !== undefined && valid) onPreview(rgbaOf(color, a)); }} onCommit={a => change(color, a)} />}
      </div>
      {!valid && <small className="field-error">请输入 #RRGGBB</small>}
      <div className="popover-actions"><Button onClick={() => toggle(false)}>取消</Button><Button variant="primary" disabled={!valid} onClick={apply}>应用颜色</Button></div>
    </Popover.Popup></Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}
const validHex = (hex: string) => /^#[0-9A-Fa-f]{6}$/.test(hex);

function toHsv(hex: string): Hsv {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
  const h = !delta ? 0 : max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return [h * 60, max ? delta / max : 0, max];
}
function fromHsv(h: number, s: number, v: number) {
  const f = (n: number) => { const k = (n + h / 60) % 6; return Math.round(255 * (v - v * s * Math.max(0, Math.min(k, 4 - k, 1)))).toString(16).padStart(2, '0'); };
  return `#${f(5)}${f(3)}${f(1)}`.toUpperCase();
}
export function ColorPicker({ color, onChange }: { color: string; onChange: (color: string) => void }) {
  const [hsv, setHsv] = useState<Hsv>(() => toHsv(validHex(color) ? color : '#FFFFFF'));
  const current = useRef(hsv);
  const lastColor = useRef(validHex(color) ? color.toUpperCase() : '#FFFFFF');
  const pointer = useRef<{ id: number; target: HTMLDivElement; initial: Hsv } | null>(null);
  useEffect(() => {
    if (!validHex(color) || color.toUpperCase() === lastColor.current) return;
    const next = toHsv(color);
    // Hue is undefined for grays; hue and saturation are undefined at black.
    // Preserve those editing axes instead of replacing them with arbitrary zeros.
    if (next[1] === 0) next[0] = current.current[0];
    if (next[2] === 0) next[1] = current.current[1];
    lastColor.current = color.toUpperCase(); current.current = next; setHsv(next);
  }, [color]);
  const commit = (next: Hsv) => {
    current.current = next; setHsv(next);
    const hex = fromHsv(...next);
    lastColor.current = hex; onChange(hex);
  };
  const setPoint = (element: HTMLElement, x: number, y: number) => {
    const r = element.getBoundingClientRect();
    if (!r.width || !r.height) return;
    commit([current.current[0], Math.max(0, Math.min(1, (x - r.left) / r.width)), 1 - Math.max(0, Math.min(1, (y - r.top) / r.height))]);
  };
  const release = (cancelled: boolean) => {
    const active = pointer.current;
    if (!active) return;
    pointer.current = null;
    if (active.target.hasPointerCapture(active.id)) active.target.releasePointerCapture(active.id);
    if (cancelled) commit(active.initial);
  };
  const finish = (e: PointerEvent<HTMLDivElement>) => {
    if (pointer.current?.id !== e.pointerId) return;
    setPoint(e.currentTarget, e.clientX, e.clientY); release(false);
  };
  const [h, s, v] = hsv;
  return <div className="color-picker">
    <div className="color-sv-wrap"><div className="color-sv" role="slider" tabIndex={0} aria-label="饱和度和亮度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s * 100)} aria-valuetext={`饱和度 ${Math.round(s * 100)}%，亮度 ${Math.round(v * 100)}%`} style={{ backgroundColor: `hsl(${h},100%,50%)` }}
      onPointerDown={e => {
        if (e.button !== 0 || pointer.current) return;
        e.preventDefault(); e.currentTarget.focus({ preventScroll: true });
        pointer.current = { id: e.pointerId, target: e.currentTarget, initial: [...current.current] };
        e.currentTarget.setPointerCapture(e.pointerId); setPoint(e.currentTarget, e.clientX, e.clientY);
      }} onPointerMove={e => { if (pointer.current?.id === e.pointerId) setPoint(e.currentTarget, e.clientX, e.clientY); }} onPointerUp={finish}
      onPointerCancel={e => { if (pointer.current?.id === e.pointerId) release(true); }} onLostPointerCapture={e => { if (pointer.current?.id === e.pointerId) release(true); }}
      onKeyDown={e => {
        if (e.key === 'Escape' && pointer.current) { e.preventDefault(); e.stopPropagation(); release(true); return; }
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
        e.preventDefault();
        const [hue, saturation, value] = current.current;
        commit([hue, Math.max(0, Math.min(1, saturation + (e.key === 'ArrowRight' ? .01 : e.key === 'ArrowLeft' ? -.01 : 0))), Math.max(0, Math.min(1, value + (e.key === 'ArrowUp' ? .01 : e.key === 'ArrowDown' ? -.01 : 0)))]);
      }}><span className="color-sv-thumb" style={{ left: `${s * 100}%`, top: `${(1 - v) * 100}%`, backgroundColor: fromHsv(h, s, v) }} /></div></div>
    <div className="hue-control"><input aria-label="色相" aria-valuetext={`${Math.round(h)}°`} className="hue-slider" type="range" min={0} max={360} step={1} value={h} style={{ '--hue-color': `hsl(${h},100%,50%)` } as CSSProperties} onChange={e => commit([Number(e.target.value), current.current[1], current.current[2]])} /></div>
  </div>;
}
