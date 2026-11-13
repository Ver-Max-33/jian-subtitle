import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Popover } from '@base-ui/react/popover';
import { ChevronLeft, ChevronRight, CircleAlert, FolderOpen, ImageIcon, ImageOff, Images, List, MousePointer2, ScanFace, SearchX, Sparkles, Type, X } from 'lucide-react';
import { mediaUrl, request } from '../bridge';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Asset, Preview } from '../types';
import { count, formatName, fullTime, megabytes, shortTime, sourceName, timeSourceNames, two } from '../format';
import { Button, IconButton, Switch } from './ui';
import { CaptionCanvas } from './CaptionCanvas';
import { cachedPreview } from './ImagePreview';
import { useEditorPreview } from './useEditorPreview';
import { ListView } from './ListView';

/** Set before a caption is created from the canvas or the + button; the caption editor takes focus once it renders. */
export const focusRequest = { pending: false };

function ImageInfo({ asset, preview, open, setOpen }: { asset: Asset; preview?: Preview; open: boolean; setOpen: (open: boolean) => void }) {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const source = asset.captions.some(c => c.source === 'manual') ? '手动填写' : asset.captions.length ? sourceName(asset.captions[0].source) : '未填写';
  const index = w.assets.indexOf(asset) + 1;
  return <Popover.Root open={open} onOpenChange={next => { setOpen(next); if (!next) w.setRawView(false); }}>
    <Popover.Trigger className="stage-name"><span className="numeric">{two(index)}</span>{asset.filename}</Popover.Trigger>
    <Popover.Portal><Popover.Positioner className="positioner" side="bottom" align="start" sideOffset={6} collisionPadding={12}><Popover.Popup className="popover image-info">
      <Popover.Title className="info-name">{asset.filename}</Popover.Title>
      <dl>
        <dt>尺寸</dt><dd>{preview ? `${preview.width} × ${preview.height} · ${formatName(asset.filename)} · ${megabytes(preview.bytes)}` : asset.width ? `${asset.width} × ${asset.height} · ${formatName(asset.filename)}` : formatName(asset.filename)}</dd>
        <dt>拍摄时间</dt><dd>{fullTime(asset.captureTime)}<small>{timeSourceNames[asset.timeSource]}{asset.timeTie ? '；与其他图片相同' : ''}</small></dd>
        <dt>创建时间</dt><dd>{fullTime(asset.createdAt)}</dd>
        <dt>修改时间</dt><dd>{fullTime(asset.modifiedAt)}</dd>
        <dt>字幕来源</dt><dd className="info-action">{source}<button type="button" className="link" onClick={() => { setOpen(false); w.openDialog('extract-one', { assetId: asset.id }); }}>重新提取…</button></dd>
        <dt>位置</dt><dd className="info-path" title={asset.sourcePath}>{asset.sourcePath}</dd>
      </dl>
      <Button className="full-width" disabled={!state?.desktop} onClick={() => act(() => mutate('open_source', { assetId: asset.id }))}><FolderOpen />在文件夹中显示</Button>
      <div className="switch-row"><span>画布显示原图（隐藏字幕）</span><Switch label="画布显示原图" checked={w.rawView} onChange={w.setRawView} /></div>
    </Popover.Popup></Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}

function SingleCanvas({ readOnly }: { readOnly: boolean }) {
  const { act, mutate, mediaVersion } = useApp();
  const w = useWorkspace();
  const project = w.project!, asset = w.asset!;
  const [reload, setReload] = useState(0);
  const [info, setInfo] = useState(false);
  useEffect(() => { const show = () => setInfo(true); window.addEventListener('jian:image-info', show); return () => window.removeEventListener('jian:image-info', show); }, []);
  const live = w.liveText && asset.captions.find(c => c.id === w.liveText!.captionId);
  const texts = live && live.text !== w.liveText!.text ? { [live.id]: w.liveText!.text } : {};
  // Rendered as large as it shows on screen (device pixels), not always 2048 (spec 4.4).
  const shown = Math.max(asset.width ?? 0, asset.height ?? 0) * (w.scale || 100) / 100 * (window.devicePixelRatio || 1);
  const { frame, error, pending } = useEditorPreview(project, asset, w.styleDrafts, texts, mediaVersion, reload, shown ? Math.min(2048, Math.max(160, Math.ceil(shown))) : 2048);
  const placeholder = w.zoom === 'fit' ? cachedPreview(project.id, asset, mediaVersion) : undefined;
  const output = w.tab === 'export' ? w.check?.outputs.find(o => o.assetId === asset.id)?.file : undefined;
  const extension = w.options.format === 'original' ? formatName(asset.filename) : w.options.format === 'jpg' ? 'JPEG' : w.options.format.toUpperCase();
  const label = <>{w.tab === 'export' ? <span className="stage-name static"><span className="numeric">{two(w.assets.indexOf(asset) + 1)}</span>{output ? `导出为 ${output}` : asset.filename}</span>
    : <ImageInfo asset={asset} preview={frame?.preview} open={info} setOpen={setInfo} />}
    <span className="stage-meta numeric">{w.tab === 'export' && frame ? `${frame.preview.width} × ${frame.preview.height} · ${extension}` : shortTime(asset.captureTime)}</span></>;
  const place = (x: number, y: number) => act(async () => {
    const created = await mutate<{ captionId: string }>('caption_add', { assetId: asset.id });
    await mutate('caption_position', { assetId: asset.id, captionId: created.captionId, x, y });
    // Type right where it was placed (spec 4.3); left empty, it goes away when typing ends.
    w.setTool('select'); w.setFresh(created.captionId);
    w.startEditing(created.captionId);
  });
  if (!frame && error) {
    const missing = /源文件|授权|定位/.test(error);
    return <div className="canvas-message"><div className="message-card">{missing ? <ImageOff /> : <CircleAlert />}<h3>{missing ? '源图片找不到' : '图片暂不可用'}</h3>
      <p>{missing ? `上次的位置：${asset.sourcePath}` : error}</p><small>字幕仍保留，可以继续编辑文字。</small>
      <div className="message-actions">{missing ? <Button variant="primary" onClick={() => w.openDialog('relocate')}>重新定位…</Button> : null}<Button onClick={() => setReload(n => n + 1)}>重试</Button></div></div></div>;
  }
  return <div className="single-canvas">
    {frame ? <CaptionCanvas key={frame.identity} frame={frame} asset={asset} captionId={w.caption?.id} styles={w.styleDrafts} positions={w.positionDrafts}
      zoom={w.zoom} onZoom={w.setZoom} onScale={w.setScale} showSafe={w.safeGuide && !!w.caption} rotationSnap={w.rotationSnap}
      regions={w.showRegions ? w.regions[asset.id] ?? [] : []} onCaption={id => w.chooseCaption(id)}
      onWidth={(id, width) => w.previewStyle('max_width', width, id)}
      onCommit={(assetId, captionId, patch) => mutate('caption_position', { assetId, captionId, ...patch }).finally(() => { if (patch.maxWidth !== undefined) w.previewStyle('max_width', undefined, captionId); })}
      label={label} selected={w.focused && !w.caption && !w.batch} hidden={w.rawView} tool={readOnly ? 'select' : w.tool} onPlace={place}
      onBackground={() => { w.chooseCaption(null); }} onEmpty={() => { if (!readOnly) w.setFocused(false); }}
      hovered={w.hovered} onHover={w.setHovered} onOpenText={(id, at) => w.startEditing(id, at)} editingId={w.editingId} texts={texts} readOnly={readOnly} />
      : <div className="canvas-area">{placeholder ? <img className="canvas-placeholder" src={placeholder.url} alt="" /> : <div className="preview-loading" role="status">正在读取图片…</div>}</div>}
    {frame && error && <div className="preview-warning" role="alert"><CircleAlert /><span>字幕预览未更新：{error}</span><Button variant="link" onClick={() => setReload(n => n + 1)}>重试</Button></div>}
    <span className="sr-only" role="status">{frame && pending ? '正在更新字幕图层' : ''}</span>
  </div>;
}

/** A composed thumbnail (picture + captions) for the batch canvas; re-rendered only when this picture's captions change. */
const composed = new Map<string, string>();
export function RenderedPreview({ asset }: { asset: Asset }) {
  const { state } = useApp();
  const project = state!.project!;
  const key = JSON.stringify([project.id, asset.id, asset.modifiedAt, project.showSpeaker, asset.captions]);
  const [url, setUrl] = useState(composed.get(key));
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    if (composed.has(key)) { setUrl(composed.get(key)); return; }
    setFailed(false);
    request<Preview>('preview', { assetId: asset.id, projectId: project.id, revision: project.revision, size: 720 })
      .then(r => mediaUrl(r.result.token)).then(next => {
        if (!alive) { URL.revokeObjectURL(next); return; }
        composed.set(key, next);
        while (composed.size > 48) { const oldest = composed.keys().next().value!; URL.revokeObjectURL(composed.get(oldest)!); composed.delete(oldest); }
        setUrl(next);
      }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [key]);
  return <div className="image-preview composed">{url ? <img src={url} alt={asset.filename} /> : failed ? <ImageOff aria-label="无法读取图片" /> : <span className="image-loading" />}</div>;
}

function BatchCanvas() {
  const w = useWorkspace();
  const chosen = w.assets.filter(a => w.selection.includes(a.id));
  const visible = new Set(w.visible.map(a => a.id));
  const shown = chosen.slice(0, 12);
  const columns = shown.length <= 3 ? shown.length : shown.length <= 8 ? 4 : 5;
  return <div className="canvas-area batch-canvas" onClick={e => { if (e.target === e.currentTarget) w.setFocused(false); }}>
    <div className="batch-grid" style={{ '--columns': columns } as CSSProperties}>
      {shown.map(a => <figure key={a.id} className={`batch-tile ${a.id === w.activeId ? 'current' : ''}`} onClick={() => w.choose(a.id)}>
        <figcaption><span className="numeric">{two(w.assets.indexOf(a) + 1)}</span><span className="truncate">{a.filename}</span>{!visible.has(a.id) && <span className="badge">筛选外</span>}</figcaption>
        <RenderedPreview asset={a} />
      </figure>)}
    </div>
    {chosen.length > shown.length && <p className="batch-more">另有 {count(chosen.length - shown.length)} 张已选图片未在画布上显示，修改同样会应用到它们</p>}
  </div>;
}

export function EmptyProject() {
  const { state, act, mutate } = useApp();
  const task = state?.importTask;
  if (task && (task.state === 'running' || task.state === 'stopping')) return <div className="canvas-message"><div className="message-card" role="status"><span className="message-icon"><Images /></span><h3>正在导入图片</h3><p className="numeric">已读取 {count(task.completed)} / {count(task.total)} 张，读好的图片会先出现在左栏</p></div></div>;
  return <div className="canvas-message"><div className="message-card"><span className="message-icon"><Images /></span><h3>还没有图片</h3><p>把图片或文件夹拖到这里，或者</p>
    <div className="message-actions"><Button variant="primary" onClick={() => act(() => mutate('choose_images'))}>选择图片</Button><Button onClick={() => act(() => mutate('choose_folder'))}>选择文件夹</Button></div></div></div>;
}

function NoResults() {
  const w = useWorkspace();
  return <div className="canvas-message"><div className="message-card"><SearchX /><h3>没有符合条件的图片</h3><p>{w.query ? `搜索「${w.query}」` : ''}{w.query && w.filter !== 'all' ? '，' : ''}{w.filter !== 'all' ? '当前筛选' : ''}没有结果</p>
    <div className="message-actions">{w.query && <Button onClick={() => w.setQuery('')}>清除搜索</Button>}<Button onClick={() => { w.setQuery(''); w.setFilter('all'); }}>查看全部图片</Button></div></div></div>;
}

export function Toolbar() {
  const w = useWorkspace();
  const { state } = useApp();
  const total = w.visible.length || w.assets.length;
  const list = w.visible.length ? w.visible : w.assets;
  const index = list.findIndex(a => a.id === w.activeId);
  const editing = w.tab === 'edit' && w.view === 'canvas';
  const none = !w.assets.length;
  const busy = state?.batchTask?.state === 'running';
  const importing = state?.importTask?.state === 'running' || state?.importTask?.state === 'stopping';
  const toolIndex = w.tool === 'text' ? 1 : 0;
  // The canvas tools keep their place, disabled, outside the canvas: when they disappeared the centred toolbar moved
  // 75 px between views, and a click where 下一张 had been landed on 上一张 (2026-11-13).
  const off = !editing || importing;
  useEffect(() => {
    if (w.tool !== 'text') return;
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') w.setTool('select'); };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [w.tool]);
  return <div className="toolbar" role="toolbar" aria-label="画布工具" inert={busy}>
    <div className={`tool-group tools ${off ? 'off' : ''}`} style={{ '--tool': toolIndex } as CSSProperties}>
      <IconButton label="选择" shortcut="V" active={!off && w.tool === 'select'} disabled={off || none} onClick={() => w.setTool('select')}><MousePointer2 /></IconButton>
      <IconButton label="添加字幕" shortcut="T" active={!off && w.tool === 'text'} disabled={off || none || w.batch || !w.asset || (w.asset.captions.length >= 20)} onClick={() => w.setTool(w.tool === 'text' ? 'select' : 'text')}><Type /></IconButton>
      <IconButton label="人物区域" toggled={!off && w.showRegions} disabled={off || none || w.batch} onClick={() => { const next = !w.showRegions; w.setShowRegions(next); if (next && w.asset) w.loadRegions(w.asset.id); }}><ScanFace /></IconButton>
      <IconButton label="重新排列" disabled={off || none || w.batch || !w.asset?.captions.length} onClick={w.rearrange}><Sparkles /></IconButton>
    </div><span className="tool-divider" />
    <div className="tool-group">
      <IconButton label="上一张" shortcut="←" disabled={index <= 0} onClick={() => w.step(-1)}><ChevronLeft /></IconButton>
      <span className="tool-count numeric">{index >= 0 ? index + 1 : 0} / {total}</span>
      <IconButton label="下一张" shortcut="→" disabled={index < 0 || index >= list.length - 1} onClick={() => w.step(1)}><ChevronRight /></IconButton>
    </div>
    <span className="tool-divider" />
    <div className="tool-group">
      <IconButton label="画布视图" toggled={w.view === 'canvas'} onClick={() => w.setView('canvas')}><ImageIcon /></IconButton>
      <IconButton label="列表视图" toggled={w.view === 'list'} disabled={w.tab === 'export'} onClick={() => w.setView('list')}><List /></IconButton>
    </div>
  </div>;
}

export function Toasts() {
  const w = useWorkspace();
  const [hold, setHold] = useState(false);
  const current = w.toasts[0];
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(timer.current);
    if (!current || current.sticky || hold) return;
    timer.current = setTimeout(() => w.dismiss(current.id), Math.max(4000, current.text.length * 120));
    return () => clearTimeout(timer.current);
  }, [current?.id, hold]);
  if (!current) return null;
  return <div className="toasts" aria-live="polite" onMouseEnter={() => setHold(true)} onMouseLeave={() => setHold(false)}>
    <div key={current.id} className={`toast ${current.tone ?? ''}`} role={current.tone === 'danger' ? 'alert' : 'status'}>
      {current.tone && <CircleAlert />}<span>{current.text}</span>
      {current.action && <button type="button" className="toast-action" onClick={() => { current.action!.run(); w.dismiss(current.id); }}>{current.action.label}</button>}
      <button type="button" className="toast-close" aria-label="关闭提示" onClick={() => w.dismiss(current.id)}><X /></button>
    </div>
  </div>;
}

export function Center({ dragging }: { dragging: boolean }) {
  const { state } = useApp();
  const w = useWorkspace();
  const project = w.project!;
  const running = state?.job?.state === 'running' || state?.job?.state === 'stopping';
  const importing = state?.importTask?.state === 'running' || state?.importTask?.state === 'stopping';
  const body = !project.assets.length ? <EmptyProject />
    : w.view === 'list' && w.tab === 'edit' ? <ListView />
    : w.batch && w.tab === 'edit' ? <BatchCanvas />
    : !w.visible.length && w.tab === 'edit' ? <NoResults />
    : w.asset ? <SingleCanvas readOnly={w.tab === 'export' || running || importing} /> : <EmptyProject />;
  return <main className="center" aria-label="画布">
    {body}
    <Toasts />
    <Toolbar />
    {dragging && <div className="drop-overlay" aria-hidden><Images /><strong>松开以添加到「{project.name}」</strong></div>}
  </main>;
}
