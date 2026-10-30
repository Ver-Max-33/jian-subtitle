import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from 'react';
import { Circle, GripVertical, ImageOff, Minus, SearchX } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Asset } from '../types';
import { sameAspect, statusNames } from '../format';
import { Button, Checkbox, Highlight, RowMenu } from './ui';
import { ImagePreview } from './ImagePreview';

const ROW = 40;
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

export function marker(a: Asset) {
  // The list marks only exceptions; confirmed images carry nothing.
  return a.status === 'needs_review' ? <span className="dot warn" aria-label="需检查" /> : a.status === 'missing' ? <Circle className="tone-muted" aria-label="待补字幕" />
    : a.status === 'no_caption' ? <Minus className="tone-muted" aria-label="无需字幕" /> : a.status === 'unreadable' ? <ImageOff className="tone-danger" aria-label="无法读取" /> : null;
}

interface Drag { id: string; from: number; to: number; pointerY: number; grab: number; pointerId: number; started: boolean; startY: number }

/** A standard list (one tab stop, ↑↓ move, Space ticks) that renders only the rows on screen, so 5000 images scroll smoothly. */
export function AssetList() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const scroller = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  const [height, setHeight] = useState(480);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const anchor = useRef<string | undefined>(undefined);
  const autoScroll = useRef<number | undefined>(undefined);
  const rows = w.visible;
  const task = state?.importTask;
  const skeletons = task && (task.state === 'running' || task.state === 'stopping') ? Math.max(0, task.total - task.completed) : 0;
  const total = rows.length + skeletons;
  const manual = w.project?.orderMode === 'manual';
  const checked = new Set(w.selection);
  const start = Math.max(0, Math.floor(scroll / ROW) - 8), end = Math.min(total, Math.ceil((scroll + height) / ROW) + 8);
  const currentIndex = rows.findIndex(a => a.id === w.activeId);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setHeight(element.clientHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Keep the current image in view: glide to a neighbour, jump when it is screens away.
  useLayoutEffect(() => {
    const element = scroller.current;
    if (!element || currentIndex < 0) return;
    const top = currentIndex * ROW;
    if (top < element.scrollTop || top + ROW > element.scrollTop + element.clientHeight) {
      const target = Math.max(0, top - element.clientHeight / 2 + ROW / 2);
      const near = Math.abs(target - element.scrollTop) < element.clientHeight * 2 && !reduced();
      element.scrollTo({ top: target, behavior: near ? 'smooth' : 'auto' });
    }
  }, [currentIndex, w.activeId]);

  const tick = (a: Asset, value: boolean, shift: boolean) => {
    const from = shift && anchor.current ? rows.findIndex(r => r.id === anchor.current) : -1, to = rows.indexOf(a);
    const range = from >= 0 && to >= 0 ? rows.slice(Math.min(from, to), Math.max(from, to) + 1).map(r => r.id) : [a.id];
    anchor.current = a.id;
    w.setSelection(ids => value ? [...new Set([...ids, ...range])] : ids.filter(id => !range.includes(id)));
  };
  const click = (e: MouseEvent, a: Asset) => {
    if (e.metaKey || e.ctrlKey) { tick(a, !checked.has(a.id), false); return; }
    if (e.shiftKey) { tick(a, true, true); return; }
    // In batch mode clicking the text only moves the canvas focus; the ticks stay (L4).
    w.choose(a.id);
  };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    const current = rows[currentIndex];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); w.step(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); const target = e.key === 'Home' ? rows[0] : rows.at(-1); if (target) w.choose(target.id); }
    else if (e.key === ' ' && current) { e.preventDefault(); tick(current, !checked.has(current.id), e.shiftKey); }
    // Ctrl/⌘ + Enter is 「确认并下一张」 everywhere (Shortcuts).
    else if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); document.querySelector<HTMLElement>('[data-caption-text]')?.focus(); }
  };
  const move = (a: Asset, delta: number) => act(async () => {
    const ids = w.assets.map(x => x.id), from = ids.indexOf(a.id), to = from + delta;
    if (to < 0 || to >= ids.length) return;
    ids.splice(to, 0, ...ids.splice(from, 1));
    await mutate('reorder_assets', { assetIds: ids });
  });

  // Manual order: lift after 3 px, the other rows make room, release commits one undoable reorder (L3).
  const stopAutoScroll = () => { if (autoScroll.current !== undefined) cancelAnimationFrame(autoScroll.current); autoScroll.current = undefined; };
  const target = (clientY: number, d: Drag) => {
    const box = scroller.current!.getBoundingClientRect();
    return Math.max(0, Math.min(rows.length - 1, Math.floor((clientY - box.top + scroller.current!.scrollTop - d.grab + ROW / 2) / ROW)));
  };
  const dragMove = (e: PointerEvent) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    if (!d.started && Math.abs(e.clientY - d.startY) < 3) return;
    const next = { ...d, started: true, pointerY: e.clientY, to: target(e.clientY, d) };
    dragRef.current = next; setDrag(next);
    const box = scroller.current!.getBoundingClientRect();
    const speed = e.clientY < box.top + 32 ? -8 : e.clientY > box.bottom - 32 ? 8 : 0;
    stopAutoScroll();
    if (speed) {
      const run = () => {
        scroller.current!.scrollTop += speed;
        const current = dragRef.current;
        if (current) { const moved = { ...current, to: target(current.pointerY, current) }; dragRef.current = moved; setDrag(moved); }
        autoScroll.current = requestAnimationFrame(run);
      };
      autoScroll.current = requestAnimationFrame(run);
    }
  };
  const dragEnd = (e: PointerEvent, cancelled = false) => {
    const d = dragRef.current;
    if (!d || d.pointerId !== e.pointerId) return;
    stopAutoScroll(); dragRef.current = null; setDrag(null);
    if (cancelled || !d.started || d.to === d.from) return;
    // Land before whatever visible row now holds the target slot, or right after the last visible one;
    // rows hidden by the filter keep their places.
    const ids = w.assets.map(a => a.id).filter(id => id !== d.id);
    const others = rows.filter(a => a.id !== d.id);
    const before = others[d.to], after = others[d.to - 1];
    ids.splice(before ? ids.indexOf(before.id) : after ? ids.indexOf(after.id) + 1 : ids.length, 0, d.id);
    act(() => mutate('reorder_assets', { assetIds: ids }));
  };
  const shift = (i: number) => {
    if (!drag?.started) return 0;
    if (i === drag.from) return 0;
    if (drag.to > drag.from && i > drag.from && i <= drag.to) return -ROW;
    if (drag.to < drag.from && i < drag.from && i >= drag.to) return ROW;
    return 0;
  };

  if (!w.assets.length && !skeletons) return <p className="list-empty">还没有图片</p>;
  if (!rows.length && !skeletons) return <div className="list-empty"><SearchX /><p>没有符合条件的图片</p><Button variant="link" onClick={() => { w.setQuery(''); w.setFilter('all'); }}>查看全部图片</Button></div>;
  return <div ref={scroller} className={`asset-list ${w.batch ? 'batch' : ''} ${drag?.started ? 'dragging' : ''}`} role="listbox" aria-label="图片列表" aria-multiselectable tabIndex={0}
    aria-activedescendant={currentIndex >= 0 ? `row-${w.activeId}` : undefined} onKeyDown={key} onScroll={e => setScroll(e.currentTarget.scrollTop)}
    onPointerMove={dragMove} onPointerUp={e => dragEnd(e)} onPointerCancel={e => dragEnd(e, true)}>
    <div className="asset-list-inner" style={{ height: total * ROW }}>
      {currentIndex >= 0 && <div className="current-highlight" aria-hidden style={{ transform: `translateY(${currentIndex * ROW + shift(currentIndex)}px)` }} />}
      {drag?.started && <div className="drop-line" aria-hidden style={{ transform: `translateY(${drag.to * ROW - 1}px)` }} />}
      {Array.from({ length: end - start }, (_, k) => start + k).map(i => {
        const a = rows[i];
        if (!a) return <div key={`skeleton-${i}`} className="asset-row skeleton" style={{ transform: `translateY(${i * ROW}px)` }} aria-hidden><span className="row-thumb" /><span className="skeleton-bar" /></div>;
        const lifted = drag?.started && drag.id === a.id;
        const first = a.captions[0];
        const label = first?.text.trim() ? first.text : a.status === 'missing' || a.status === 'no_caption' || a.status === 'unreadable' ? statusNames[a.status] : '（空字幕）';
        const row = <div id={`row-${a.id}`} role="option" aria-selected={a.id === w.activeId} aria-checked={checked.has(a.id)}
          className={`asset-row ${a.id === w.activeId ? 'current' : ''} ${checked.has(a.id) ? 'checked' : ''} ${first?.text.trim() ? '' : 'placeholder'} ${lifted ? 'lifted' : ''}`}
          style={{ transform: lifted ? `translateY(${drag.pointerY - scroller.current!.getBoundingClientRect().top + scroller.current!.scrollTop - drag.grab}px)` : `translateY(${i * ROW + shift(i)}px)` }}
          title={a.filename} onClick={e => click(e, a)}>
          <span className="row-check"><Checkbox label={`勾选 ${a.filename}`} tabIndex={-1} checked={checked.has(a.id)} onChange={(v, s) => tick(a, v, s)} /></span>
          <ImagePreview assetId={a.id} size={160} className="row-thumb" />
          <span className="row-label"><Highlight text={label} query={w.query} /></span>
          {a.captions.length > 1 && <span className="row-chip">+{a.captions.length - 1}</span>}
          <span className="row-marker">{marker(a)}</span>
          {manual && <span className="row-handle" aria-hidden title="拖动调整顺序"
            onPointerDown={e => {
              if (e.button !== 0) return;
              e.preventDefault(); e.stopPropagation();
              const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
              scroller.current!.setPointerCapture(e.pointerId);
              const d = { id: a.id, from: i, to: i, pointerY: e.clientY, grab: e.clientY - box.top, pointerId: e.pointerId, started: false, startY: e.clientY };
              dragRef.current = d; setDrag(d);
            }}><GripVertical /></span>}
        </div>;
        return <RowMenu key={a.id} items={[
          { label: '查看图片信息', action: () => { w.choose(a.id); w.setView('canvas'); window.dispatchEvent(new CustomEvent('jian:image-info')); } },
          { label: '从文件名重新提取…', action: () => w.openDialog('extract-one', { assetId: a.id }) },
          { label: '设为无需字幕', disabled: a.status === 'no_caption', action: () => act(() => mutate('batch', { operation: 'no_caption', assetIds: [a.id] })) },
          { separator: true },
          { label: '上移一位', disabled: !manual || w.assets[0]?.id === a.id, action: () => move(a, -1) },
          { label: '下移一位', disabled: !manual || w.assets.at(-1)?.id === a.id, action: () => move(a, 1) },
          { label: '选择同宽高比的图片', disabled: !a.width, action: () => w.setSelection(list => [...new Set([...list, ...w.assets.filter(x => sameAspect(x, a)).map(x => x.id)])]) },
          { separator: true },
          { label: '移除图片…', danger: true, action: () => w.openDialog('batch', { operation: 'remove', assetIds: [a.id] }) },
        ]}>{row}</RowMenu>;
      })}
    </div>
  </div>;
}
