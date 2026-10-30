import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { ArrowDown, ArrowUp, Check } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Asset, Caption } from '../types';
import { shortTime, statusNames, two } from '../format';
import { Button, Highlight, RowMenu, Tip } from './ui';
import { ImagePreview } from './ImagePreview';
import { statusIcon } from './LeftPanel';

const BASE = 78, LINE = 34;
const heightOf = (a: Asset) => BASE + Math.max(0, a.captions.length - 1) * LINE;
// The caption cell a double-click or Enter asked for; focused when it renders.
const pendingFocus = { captionId: '' };

function CaptionCell({ asset, caption }: { asset: Asset; caption: Caption }) {
  const { editText, compose, draft } = useApp();
  const w = useWorkspace();
  const [text, setText] = useState(caption.text);
  const composing = useRef(false);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (!draft.current || draft.current.captionId !== caption.id) setText(caption.text); }, [caption.id, caption.text]);
  useEffect(() => { if (pendingFocus.captionId === caption.id) { pendingFocus.captionId = ''; field.current?.focus(); field.current?.select(); } }, [caption.id]);
  return <textarea ref={field} className="cell-input" rows={1} aria-label="字幕" value={text} placeholder="填写这张图片的字幕…" maxLength={10000}
    onFocus={() => w.chooseCaption(caption.id)}
    onCompositionStart={() => { composing.current = true; compose(true); }}
    onCompositionEnd={e => { composing.current = false; compose(false); w.setLiveText({ captionId: caption.id, text: e.currentTarget.value }); }}
    onChange={e => { setText(e.target.value); editText(asset.id, caption.id, e.target.value); if (!composing.current) w.setLiveText({ captionId: caption.id, text: e.target.value }); }}
    onKeyDown={e => {
      if (e.key === 'Escape' || (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing)) {
        e.preventDefault(); e.stopPropagation(); (e.currentTarget.closest('.list-scroll') as HTMLElement | null)?.focus();
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) w.confirmAndNext(asset);
      }
    }} />;
}

export function ListView() {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const scroller = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  const [height, setHeight] = useState(600);
  const rows = w.visible;
  const offsets = useMemo(() => { const o = [0]; for (const a of rows) o.push(o[o.length - 1] + heightOf(a)); return o; }, [rows]);
  const first = (y: number) => { let lo = 0, hi = rows.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (offsets[mid + 1] <= y) lo = mid + 1; else hi = mid; } return lo; };
  const start = Math.max(0, first(scroll) - 4), end = Math.min(rows.length, first(scroll + height) + 5);
  const current = rows.findIndex(a => a.id === w.activeId);
  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setHeight(element.clientHeight));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const element = scroller.current;
    if (!element || current < 0) return;
    const top = offsets[current], bottom = offsets[current + 1];
    if (top < element.scrollTop || bottom > element.scrollTop + element.clientHeight) element.scrollTo({ top: Math.max(0, top - element.clientHeight / 3) });
  }, [current]);
  const edit = (a: Asset, caption?: Caption) => { const target = caption ?? a.captions[0]; if (!target) return; pendingFocus.captionId = target.id; if (a.id !== w.activeId) w.choose(a.id, { caption: target.id }); else document.querySelector<HTMLTextAreaElement>(`[data-cell="${target.id}"] textarea`)?.focus(); };
  const key = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); w.step(e.key === 'ArrowDown' ? 1 : -1); }
    if (e.key === 'Enter' && rows[current]) { e.preventDefault(); edit(rows[current]); }
  };
  const order = w.project!.orderMode;
  return <div className="list-view">
    <div className="list-card" role="grid" aria-label="字幕列表" aria-rowcount={rows.length}>
      <div className="list-head" role="row">
        <span role="columnheader">#</span><span role="columnheader" /><span role="columnheader">原文件名</span><span role="columnheader">字幕</span><span role="columnheader">说话人</span>
        <span role="columnheader"><Tip label="按拍摄时间排序；再点一次反过来"><button type="button" className="sort-head" onClick={() => act(() => mutate('set_order', { mode: order === 'time' ? 'time_desc' : 'time' }))}>拍摄时间{order === 'time' ? <ArrowUp /> : order === 'time_desc' ? <ArrowDown /> : null}</button></Tip></span>
        <span role="columnheader">状态</span>
      </div>
      <div ref={scroller} className="list-scroll" tabIndex={0} onKeyDown={key} onScroll={e => setScroll(e.currentTarget.scrollTop)}>
        <div style={{ height: offsets[rows.length], position: 'relative' }}>
          {rows.slice(start, end).map((a, k) => {
            const i = start + k, active = a.id === w.activeId;
            const row = <div role="row" aria-selected={active} className={`list-row ${active ? 'current' : ''} ${w.selection.includes(a.id) ? 'checked' : ''}`} style={{ transform: `translateY(${offsets[i]}px)`, height: heightOf(a) }}
              onClick={e => { if (!active && !(e.target as HTMLElement).closest('button, textarea')) w.choose(a.id); }}>
              <span className="cell numeric muted">{two(w.assets.indexOf(a) + 1)}</span>
              <span className="cell"><ImagePreview assetId={a.id} size={240} className="list-thumb" /></span>
              <span className="cell filename muted"><Highlight text={a.filename} query={w.query} /></span>
              <span className="cell captions">{a.captions.length ? a.captions.map(c => <span key={c.id} data-cell={c.id} className="caption-line" onDoubleClick={() => edit(a, c)}>
                {active ? <CaptionCell asset={a} caption={c} /> : <span className={c.text.trim() ? '' : 'muted'}><Highlight text={c.text || '（空字幕）'} query={w.query} /></span>}</span>)
                : <span className="caption-line muted">{a.status === 'no_caption' ? '无需字幕' : '填写这张图片的字幕…'}</span>}</span>
              <span className="cell captions">{a.captions.length ? a.captions.map(c => <span key={c.id} className="caption-line">{c.speaker || <span className="muted">—</span>}</span>) : <span className="caption-line muted">—</span>}</span>
              <span className="cell numeric">{shortTime(a.captureTime)}{a.timeTie && <Tip label="与其他图片的时间相同，顺序按文件名"><span className="dot warn tie" /></Tip>}</span>
              <span className="cell status">{active && a.captions.length && a.status !== 'ready' ? <Button variant="soft" onClick={() => w.confirmAndNext(a)}><Check />确认</Button>
                : <span className={`status-label ${a.status}`}><span className="filter-icon">{statusIcon(a.status)}</span>{statusNames[a.status]}</span>}</span>
            </div>;
            return <RowMenu key={a.id} items={[
              { label: '编辑字幕', disabled: !a.captions.length, action: () => edit(a) },
              { label: '在画布中打开', action: () => { w.choose(a.id); w.setView('canvas'); } },
              { label: '从文件名重新提取…', action: () => w.openDialog('extract-one', { assetId: a.id }) },
              { label: '设为无需字幕', disabled: a.status === 'no_caption', action: () => act(() => mutate('batch', { operation: 'no_caption', assetIds: [a.id] })) },
              { separator: true },
              { label: '移除图片…', danger: true, action: () => w.openDialog('batch', { operation: 'remove', assetIds: [a.id] }) },
            ]}>{row}</RowMenu>;
          })}
        </div>
      </div>
    </div>
  </div>;
}
