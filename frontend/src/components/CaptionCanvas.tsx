import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react';
import { RotateCw } from 'lucide-react';
import type { Asset, Caption, Preview, Style } from '../types';
import type { EditorFrame, StyleDrafts } from './useEditorPreview';
import { normalizeRotation, pointerRotationDelta, snapRotation } from './captionRotation';
import { chromeCorners } from '../styleModel';
import { InlineEditor } from './InlineEditor';
import { ApproxCaption } from './ApproxLayer';

export interface PositionDraft { x?: number; y?: number; rotation?: number }
export type PositionDrafts = Record<string, PositionDraft>;
type Mode = 'move' | 'rotate' | 'width' | 'width-left';
interface Placement { id: string; x: number; y: number; width: number; rotation: number }
interface Guides { x?: number; y?: number }
interface Drag extends Placement { mode: Mode; snapped: boolean; guides?: Guides }
type Overlay = Preview['overlays'][number];
interface Gesture extends Placement {
  px: number; py: number; lastX: number; lastY: number;
  mode: Mode; assetId: string; pointerId: number; target: HTMLDivElement;
  rawRotation: number; snappedAngle?: number; moved: boolean; corners: ReturnType<typeof chromeCorners>;
}

function geometry(caption: Caption, overlay: Overlay, frame: EditorFrame, style: Style, draft?: PositionDraft) {
  const { width: iw, height: ih } = frame.preview;
  const scale = style.font_size / (frame.styles[caption.id]?.font_size || style.font_size);
  const rotation = draft?.rotation ?? caption.rotation;
  const radians = rotation * Math.PI / 180;
  const rw = overlay.renderWidth * iw * scale, rh = overlay.height * ih * scale;
  const width = Math.ceil(Math.abs(rw * Math.cos(radians)) + Math.abs(rh * Math.sin(radians)));
  const height = Math.ceil(Math.abs(rw * Math.sin(radians)) + Math.abs(rh * Math.cos(radians)));
  let left = Math.round((draft?.x ?? caption.position[0]) * iw - width / 2);
  let top = Math.round((draft?.y ?? caption.position[1]) * ih - height / 2);
  if (style.safe_edge) {
    const margin = Math.min(12, Math.floor(iw / 20), Math.floor(ih / 20));
    left = Math.min(Math.max(left, margin), Math.max(margin, iw - width - margin));
    top = Math.min(Math.max(top, margin), Math.max(margin, ih - height - margin));
  }
  return { x: (left + width / 2) / iw, y: (top + height / 2) / ih, w: width / iw, h: height / ih, scale, rotation };
}
const safeMargin = (iw: number, ih: number) => Math.min(12, Math.floor(iw / 20), Math.floor(ih / 20));

/** Center lines, safe margins and the other captions' edges pull a moving caption within 4 screen px (E4). */
function snap(value: number, half: number, lines: number[], threshold: number) {
  let best: { center: number; line: number; distance: number } | undefined;
  for (const line of lines) {
    for (const center of [line, line + half, line - half]) {
      const distance = Math.abs(value - center);
      if (distance <= threshold && (!best || distance < best.distance)) best = { center, line, distance };
    }
  }
  return best;
}

let lastView = { fx: .5, fy: .5 };

/** Drag state stays here: a pointer frame does not rerender the inspector or filmstrip. */
export function CaptionCanvas({ frame, asset, captionId, styles, positions, zoom, onZoom, onScale, showSafe, rotationSnap, regions, onCaption, onWidth, onCommit, label, selected, hidden, tool, onPlace, onBackground, onEmpty, hovered, onHover, onOpenText, readOnly = false, editingId = null, texts = {} }: {
  frame: EditorFrame; asset: Asset; captionId?: string; styles: StyleDrafts; positions: PositionDrafts; zoom: string; showSafe: boolean; rotationSnap: boolean; regions: number[][];
  onZoom: (zoom: string) => void; onScale: (percent: number) => void;
  onCaption: (id: string) => void; onWidth: (id: string, width?: number) => void;
  onCommit: (assetId: string, captionId: string, final: PositionDraft & { maxWidth?: number }) => Promise<unknown>;
  label?: ReactNode; selected: boolean; hidden: boolean; tool: 'select' | 'text'; onPlace: (x: number, y: number) => void;
  onBackground: () => void; onEmpty: () => void; hovered?: string | null; onHover: (id: string | null) => void; onOpenText: (id: string, at: { x: number; y: number }) => void; readOnly?: boolean;
  /** The caption being typed on the canvas: its frame turns dashed and loses its handles (spec 4.3, 4.8). */
  editingId?: string | null;
  /** Unsaved typing per caption: drawn in the page at once, rendered precisely when typing pauses. */
  texts?: Record<string, string>;
}) {
  const canvas = useRef<HTMLDivElement>(null), stage = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState({ width: 0, height: 0 });
  const [drag, setDrag] = useState<Drag>();
  const [panning, setPanning] = useState(false);
  const gesture = useRef<Gesture | undefined>(undefined);
  const draft = useRef<Drag | undefined>(undefined);
  const animation = useRef<number | undefined>(undefined);
  const widthTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const version = useRef(0);
  const pan = useRef<{ x: number; y: number; left: number; top: number; pointerId: number } | undefined>(undefined);
  // A pan that moved is not a click on the empty canvas.
  const moved = useRef(false);
  // Image point that must stay under the same screen point across a zoom change: the viewport center, or the cursor for wheel zoom.
  const anchor = useRef({ fx: .5, fy: .5, cx: 0, cy: 0 });
  const appliedZoom = useRef<string | undefined>(undefined);
  const wheelTarget = useRef<number | undefined>(undefined);
  const latestWidth = useRef(onWidth); latestWidth.current = onWidth;
  const latestZoom = useRef(onZoom); latestZoom.current = onZoom;
  const zoomRef = useRef(zoom); zoomRef.current = zoom;
  const { preview } = frame;
  const dimensions = zoom === 'fit' ? fit : { width: preview.width * Number(zoom) / 100, height: preview.height * Number(zoom) / 100 };
  const measureAnchor = (clientX?: number, clientY?: number) => {
    const area = canvas.current, box = stage.current?.getBoundingClientRect();
    if (!area || !box?.width || !box.height) return;
    const a = area.getBoundingClientRect();
    const x = clientX ?? a.left + area.clientWidth / 2, y = clientY ?? a.top + area.clientHeight / 2;
    anchor.current = { fx: (x - box.left) / box.width, fy: (y - box.top) / box.height, cx: x - a.left, cy: y - a.top };
    if (clientX === undefined) lastView = { fx: anchor.current.fx, fy: anchor.current.fy };
  };
  useEffect(() => {
    const target = canvas.current;
    if (!target) return;
    const update = () => {
      const css = getComputedStyle(target);
      const w = target.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
      const h = target.clientHeight - parseFloat(css.paddingTop) - parseFloat(css.paddingBottom);
      const ratio = Math.max(0, Math.min(w / preview.width, h / preview.height));
      setFit({ width: preview.width * ratio, height: preview.height * ratio });
    };
    update(); const observer = new ResizeObserver(update); observer.observe(target);
    return () => observer.disconnect();
  }, [preview.width, preview.height]);
  useLayoutEffect(() => {
    const area = canvas.current, box = stage.current?.getBoundingClientRect();
    if (!area || !box?.width) return;
    if (appliedZoom.current !== zoom) {
      // A freshly opened image keeps the region the user was looking at on the previous one.
      const a = area.getBoundingClientRect(), k = appliedZoom.current === undefined ? { ...lastView, cx: area.clientWidth / 2, cy: area.clientHeight / 2 } : anchor.current;
      area.scrollLeft += box.left + k.fx * box.width - (a.left + k.cx);
      area.scrollTop += box.top + k.fy * box.height - (a.top + k.cy);
      appliedZoom.current = zoom; wheelTarget.current = undefined;
    }
    measureAnchor();
  }, [zoom, dimensions.width, dimensions.height]);
  useEffect(() => { if (dimensions.width) onScale(dimensions.width / preview.width * 100); }, [dimensions.width, preview.width]);
  useEffect(() => {
    const area = canvas.current;
    if (!area) return;
    // Pinch (ctrl+wheel in WebView2) or ⌘/Ctrl + wheel zooms at the cursor; plain wheel keeps scrolling.
    const wheel = (e: WheelEvent) => {
      const box = stage.current?.getBoundingClientRect();
      if ((!e.ctrlKey && !e.metaKey) || !box?.width) return;
      e.preventDefault();
      // Several wheel events can land before React renders the previous zoom; compound them.
      const current = wheelTarget.current ?? box.width / preview.width * 100;
      const next = Math.min(400, Math.max(10, current * Math.exp(-Math.max(-50, Math.min(50, e.deltaY)) * .006)));
      const value = String(Math.round(next * 10) / 10);
      if (value === zoomRef.current) return;
      if (wheelTarget.current === undefined) measureAnchor(e.clientX, e.clientY);
      wheelTarget.current = next;
      latestZoom.current(value);
    };
    area.addEventListener('wheel', wheel, { passive: false });
    return () => area.removeEventListener('wheel', wheel);
  }, [preview.width]);
  useEffect(() => () => { if (animation.current !== undefined) cancelAnimationFrame(animation.current); clearTimeout(widthTimer.current); if (gesture.current?.mode.startsWith('width')) latestWidth.current(gesture.current.id); version.current++; }, []);
  const release = (start: Gesture) => {
    if (start.target.hasPointerCapture(start.pointerId)) start.target.releasePointerCapture(start.pointerId);
  };
  const stopScheduled = () => {
    if (animation.current !== undefined) cancelAnimationFrame(animation.current);
    animation.current = undefined; clearTimeout(widthTimer.current); widthTimer.current = undefined;
  };
  const cancel = () => {
    const start = gesture.current;
    if (!start) return;
    stopScheduled(); gesture.current = undefined; draft.current = undefined; version.current++;
    if (start.mode.startsWith('width')) latestWidth.current(start.id);
    release(start); setDrag(undefined);
  };
  const updateGesture = (e: PointerEvent<HTMLDivElement>) => {
    const start = gesture.current, box = stage.current?.getBoundingClientRect();
    if (!start || e.pointerId !== start.pointerId || !box?.width || !box.height) return;
    // A click should not create an accidental move/undo entry.
    if (!start.moved && Math.hypot(e.clientX - start.px, e.clientY - start.py) < 3) return;
    start.moved = true;
    const dx = (e.clientX - start.px) / box.width, dy = (e.clientY - start.py) / box.height;
    const radians = start.rotation * Math.PI / 180;
    const widthDelta = ((e.clientX - start.px) * Math.cos(radians) - (e.clientY - start.py) * Math.sin(radians)) / box.width;
    let rotation = start.rotation;
    if (start.mode === 'rotate') {
      const currentCaption = asset.captions.find(c => c.id === start.id);
      const overlay = preview.overlays.find(o => o.id === start.id);
      if (!currentCaption || !overlay) { cancel(); return; }
      // Edge constraints can move the visible center as the rotated bounds grow.
      const center = geometry(currentCaption, overlay, frame, { ...currentCaption.style, ...styles[start.id] }, draft.current || start);
      start.rawRotation += pointerRotationDelta(
        { x: start.lastX, y: start.lastY }, { x: e.clientX, y: e.clientY },
        { x: box.left + center.x * box.width, y: box.top + center.y * box.height },
      );
      start.lastX = e.clientX; start.lastY = e.clientY;
      start.snappedAngle = rotationSnap ? snapRotation(start.rawRotation, start.snappedAngle) : undefined;
      rotation = normalizeRotation(start.snappedAngle ?? start.rawRotation);
    }
    let x = start.mode === 'move' ? Math.max(0, Math.min(1, start.x + dx)) : start.x;
    let y = start.mode === 'move' ? Math.max(0, Math.min(1, start.y + dy)) : start.y;
    const guides: Guides = {};
    if (start.mode === 'move') {
      const moving = asset.captions.find(c => c.id === start.id), overlay = preview.overlays.find(o => o.id === start.id);
      if (moving && overlay) {
        const own = geometry(moving, overlay, frame, { ...moving.style, ...styles[start.id] }, { x, y, rotation: start.rotation });
        const mx = safeMargin(preview.width, preview.height) / preview.width, my = safeMargin(preview.width, preview.height) / preview.height;
        const others = asset.captions.filter(c => c.id !== start.id).flatMap(c => {
          const o = preview.overlays.find(item => item.id === c.id);
          return o ? [geometry(c, o, frame, { ...c.style, ...styles[c.id] }, positions[c.id])] : [];
        });
        const sx = snap(x, own.w / 2, [.5, mx, 1 - mx, ...others.flatMap(g => [g.x, g.x - g.w / 2, g.x + g.w / 2])], 4 / box.width);
        const sy = snap(y, own.h / 2, [.5, my, 1 - my, ...others.flatMap(g => [g.y, g.y - g.h / 2, g.y + g.h / 2])], 4 / box.height);
        if (sx) { x = sx.center; guides.x = sx.line; }
        if (sy) { y = sy.center; guides.y = sy.line; }
      }
    }
    draft.current = {
      id: start.id, mode: start.mode, snapped: start.snappedAngle !== undefined, guides,
      x, y,
      width: start.mode.startsWith('width') ? Math.max(.1, Math.min(1, start.width + widthDelta * (start.mode === 'width-left' ? -2 : 2))) : start.width,
      rotation,
    };
    if (animation.current === undefined) animation.current = requestAnimationFrame(() => { animation.current = undefined; setDrag(draft.current); });
    if (start.mode.startsWith('width') && widthTimer.current === undefined) widthTimer.current = setTimeout(() => {
      widthTimer.current = undefined;
      if (draft.current && gesture.current) latestWidth.current(draft.current.id, draft.current.width);
    }, 80);
  };
  const finish = (e: PointerEvent<HTMLDivElement>) => {
    const start = gesture.current, transaction = version.current;
    if (!start || start.pointerId !== e.pointerId) return;
    updateGesture(e);
    if (gesture.current !== start) return;
    const final = draft.current;
    stopScheduled(); gesture.current = undefined; release(start);
    const changed = final && (start.mode === 'rotate' ? normalizeRotation(final.rotation - start.rotation) !== 0
      : start.mode.startsWith('width') ? Math.abs(final.width - start.width) > .000001
      : Math.abs(final.x - start.x) + Math.abs(final.y - start.y) > .000001);
    if (!changed || !final) {
      if (start.mode.startsWith('width')) latestWidth.current(start.id);
      draft.current = undefined; setDrag(undefined); return;
    }
    setDrag(final);
    if (start.mode.startsWith('width')) latestWidth.current(final.id, final.width);
    // Resizing/rotation are anchored to the center the user actually grabbed,
    // which may differ from stored coordinates after safe-edge clamping.
    const patch = start.mode.startsWith('width') ? { x: final.x, y: final.y, maxWidth: final.width }
      : start.mode === 'rotate' ? { x: final.x, y: final.y, rotation: final.rotation } : { x: final.x, y: final.y };
    void onCommit(start.assetId, final.id, patch).catch(() => {}).finally(() => {
      if (version.current === transaction) { setDrag(undefined); draft.current = undefined; }
    });
  };
  const endPan = (e: PointerEvent<HTMLDivElement>) => { if (pan.current?.pointerId === e.pointerId) { pan.current = undefined; setPanning(false); } };
  const transform = (x: number, y: number, rotation: number) => `translate3d(${x * dimensions.width}px, ${y * dimensions.height}px, 0) translate(-50%, -50%) rotate(${-rotation}deg)`;
  const place = (e: PointerEvent<HTMLDivElement>) => {
    const box = stage.current?.getBoundingClientRect();
    if (!box?.width) return;
    onPlace(Math.max(0, Math.min(1, (e.clientX - box.left) / box.width)), Math.max(0, Math.min(1, (e.clientY - box.top) / box.height)));
  };
  return <><div ref={canvas} className={`canvas-area ${zoom !== 'fit' ? 'zoomed' : ''} ${panning ? 'panning' : ''} ${tool === 'text' ? 'placing' : ''}`} data-gesture={gesture.current?.mode} onScroll={() => measureAnchor()}
    onClick={e => { if (e.target === e.currentTarget && !moved.current) onEmpty(); }}
    onPointerDown={e => {
    moved.current = false;
    if (tool === 'text' && e.button === 0 && stage.current?.contains(e.target as Node) && !(e.target as HTMLElement).closest('.caption-box')) { e.preventDefault(); place(e); return; }
    if (gesture.current || pan.current || zoom === 'fit' || (e.target as HTMLElement).closest('.caption-box') || ![0, 1].includes(e.button)) return;
    e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
    pan.current = { x: e.clientX, y: e.clientY, left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop, pointerId: e.pointerId };
    setPanning(true);
  }} onPointerMove={e => { if (pan.current?.pointerId === e.pointerId) { moved.current = true; e.currentTarget.scrollLeft = pan.current.left - e.clientX + pan.current.x; e.currentTarget.scrollTop = pan.current.top - e.clientY + pan.current.y; } }} onPointerUp={endPan} onPointerCancel={endPan} onLostPointerCapture={endPan}>
    <div ref={stage} className={`image-stage layered-stage ${selected ? 'selected' : ''} ${hidden ? 'raw' : ''}`} style={{ ...dimensions, aspectRatio: `${preview.width}/${preview.height}`, ...(zoom !== 'fit' ? { maxWidth: 'none', maxHeight: 'none', flexShrink: 0 } : {}) }} data-interacting={!!gesture.current || undefined}
      onClick={e => { if (!(e.target as HTMLElement).closest('.caption-box') && !moved.current && tool === 'select') onBackground(); }}>
      {label && <div className="stage-label">{label}</div>}
      <img src={frame.background} alt={asset.filename} draggable={false} />
      {asset.captions.map(c => {
        const o = preview.overlays.find(item => item.id === c.id);
        if (!o || !frame.layers[c.id]) return null;
        const style = { ...c.style, ...styles[c.id] };
        const local = drag?.id === c.id ? drag : positions[c.id];
        const g = geometry(c, o, frame, style, local);
        const width = drag?.id === c.id ? drag.width : style.max_width;
        const placement: CSSProperties = { left: 0, top: 0, transform: transform(g.x, g.y, g.rotation) };
        const size = { width: `${o.renderWidth * g.scale * 100}%`, height: `${o.height * g.scale * 100}%` };
        // The frame is the wrap area: as wide as the wrap width, as tall as the text plus 4 px each side (spec 4.8).
        const span = Math.max(width, o.renderWidth * g.scale), W = dimensions.width, H = dimensions.height, half = o.height * g.scale * H / 2 + 4;
        const box: CSSProperties = { ...placement, width: `${span * 100}%`, height: `calc(${o.height * g.scale * 100}% + 8px)` };
        const corners = gesture.current?.id === c.id ? gesture.current.corners
          : chromeCorners({ left: (g.x - span / 2) * W, right: (g.x + span / 2) * W, top: g.y * H - half, bottom: g.y * H + half }, { left: -16, top: -16, right: W + 16, bottom: H + 16 });
        const resizeCursor = ['ew-resize', 'nesw-resize', 'ns-resize', 'nwse-resize'][Math.round(((g.rotation % 180 + 180) % 180) / 45) % 4];
        const active = captionId === c.id, editing = editingId === c.id, number = asset.captions.indexOf(c) + 1;
        const moving = drag?.id === c.id && gesture.current?.moved ? drag : undefined;
        // Without the edge margin, text outside the picture is cut off on export.
        const overflow = !style.safe_edge && (g.x - g.w / 2 < 0 || g.x + g.w / 2 > 1 || g.y - g.h / 2 < 0 || g.y + g.h / 2 > 1);
        return <div className="caption-layer-group" key={c.id}>
          {(() => {
            const raster = <img className="caption-raster" src={frame.layers[c.id]} alt="" draggable={false} style={{ ...placement, ...size, visibility: editing ? 'hidden' : undefined }} />;
            // A changed look or text is drawn in the page until the precise render for it arrives (spec 4.4).
            const look = { ...style, max_width: width }, appearance = (s?: Style) => s && JSON.stringify({ ...s, safe_edge: undefined });
            const stale = (texts[c.id] ?? c.text) !== (frame.texts[c.id] ?? c.text) || appearance(look) !== appearance(frame.styles[c.id]);
            return stale && !editing ? <ApproxCaption text={texts[c.id] ?? c.text} speaker={c.speaker} style={look} edge={Math.min(preview.width, preview.height)} imageWidth={preview.width}
              scale={W / preview.width} transform={placement.transform as string} fallback={raster} /> : raster;
          })()}
          {!readOnly && <>
          {/* One rectangle for hover, selection and typing: the wrap area the side handles change (spec 4.8). */}
          <div className={`caption-box ${active ? 'active' : ''} ${hovered === c.id ? 'hovered' : ''} ${editing ? 'editing' : ''} ${overflow ? 'overflow' : ''}`} role="button" tabIndex={0} aria-label={`选择字幕 ${number}`} data-gesture={gesture.current?.id === c.id ? gesture.current.mode : undefined} style={box}
            onFocus={() => { if (captionId !== c.id) onCaption(c.id); }}
            onPointerEnter={() => onHover(c.id)} onPointerLeave={() => onHover(null)} onDoubleClick={e => onOpenText(c.id, { x: e.clientX, y: e.clientY })}
            onKeyDown={e => { if (e.key === 'Escape' && gesture.current) { e.preventDefault(); e.stopPropagation(); cancel(); } }}
            onPointerDown={e => {
              if (e.button !== 0 || gesture.current || pan.current) return;
              e.preventDefault(); e.stopPropagation(); e.currentTarget.focus({ preventScroll: true });
              if (captionId !== c.id) onCaption(c.id);
              const handle = (e.target as HTMLElement).closest<HTMLElement>('[data-handle]')?.dataset.handle;
              const mode: Mode = handle === 'rotate' || handle === 'width' || handle === 'width-left' ? handle : 'move';
              e.currentTarget.setPointerCapture(e.pointerId); version.current++; draft.current = undefined;
              gesture.current = { id: c.id, x: g.x, y: g.y, width, rotation: g.rotation, px: e.clientX, py: e.clientY, lastX: e.clientX, lastY: e.clientY, mode, assetId: asset.id, pointerId: e.pointerId, target: e.currentTarget, rawRotation: g.rotation, moved: false, corners };
              setDrag({ id: c.id, x: g.x, y: g.y, width, rotation: g.rotation, mode, snapped: false });
            }}
            onPointerMove={updateGesture} onPointerUp={finish}
            onPointerCancel={e => { if (gesture.current?.pointerId === e.pointerId) cancel(); }} onLostPointerCapture={e => { if (gesture.current?.pointerId === e.pointerId) cancel(); }}>
            {active && <>
              {/* Number · speaker, kept level; the move and overflow readouts sit beside it. */}
              <div className={`caption-tags ${corners.tag}`} style={{ rotate: `${g.rotation}deg` }}>
                <span className="caption-tag">{c.speaker ? `${number} · ${c.speaker}` : number}</span>
                {moving?.mode === 'move' && <span className="caption-readout">X {(moving.x * 100).toFixed(1)}% · Y {(moving.y * 100).toFixed(1)}%</span>}
                {overflow && moving?.mode !== 'move' && <span className="caption-readout warn">超出画面，导出时会被裁掉</span>}
              </div>
              {!editing && <>
                <i className="handle w" title="拖动调整换行宽度" data-handle="width-left" style={{ cursor: resizeCursor }} />
                <i className="handle e" title="拖动调整换行宽度" data-handle="width" style={{ cursor: resizeCursor }} />
                <span className={`rotation-handle ${corners.knob}`} data-handle="rotate" title="围绕字幕中心拖动旋转"><RotateCw /></span>
                {moving?.mode.startsWith('width') && <span className={`caption-readout width-readout ${moving.mode === 'width-left' ? 'left' : 'right'}`}>换行宽度 {Math.round(moving.width * 100)}%</span>}
              </>}
            </>}
          </div>
          {editing && <InlineEditor caption={c} style={style} transform={placement.transform as string} maxWidth={width * W}
            unit={(style.reference_edge ? Math.min(preview.width, preview.height) / style.reference_edge : 1) * W / preview.width} />}
          {gesture.current?.id === c.id && gesture.current.mode === 'rotate' && <span className="rotation-pivot" aria-hidden style={{ left: `${g.x * 100}%`, top: `${g.y * 100}%` }} />}
          </>}
        </div>;
      })}
      {showSafe && <div className="safe-guide" aria-hidden style={{ inset: `${safeMargin(preview.width, preview.height) / preview.height * 100}% ${safeMargin(preview.width, preview.height) / preview.width * 100}%` }} />}
      {drag?.guides?.x !== undefined && <span className="snap-guide vertical" aria-hidden style={{ left: `${drag.guides.x * 100}%` }} />}
      {drag?.guides?.y !== undefined && <span className="snap-guide horizontal" aria-hidden style={{ top: `${drag.guides.y * 100}%` }} />}
      {regions.map(([x, y, w, h], i) => <div key={i} className="person-region" style={{ left: `${x / preview.width * 100}%`, top: `${y / preview.height * 100}%`, width: `${w / preview.width * 100}%`, height: `${h / preview.height * 100}%` }} />)}
    </div>
  </div>{drag && gesture.current && drag.mode === 'rotate' && <output className={`rotation-feedback ${drag.snapped ? 'snapped' : ''}`} aria-live="off"><span>{/* Stored angles follow Pillow (counter-clockwise); people read clockwise as positive. */}{-drag.rotation > 0 ? '+' : ''}{(-drag.rotation || 0).toFixed(1).replace(/\.0$/, '')}°</span>{drag.snapped && <small>已吸附</small>}</output>}</>;
}
