import { useEffect, useRef, useState, type DragEvent } from 'react';
import { Tooltip } from '@base-ui/react/tooltip';
import { PanelLeft } from 'lucide-react';
import { useApp } from './state';
import { useWorkspace } from './workspace';
import { count } from './format';
import { AppMark, Button, IconButton } from './components/ui';
import { LeftPanel } from './components/LeftPanel';
import { Center, Toasts } from './components/Canvas';
import { RightPanel } from './components/RightPanel';
import { AppDialogs } from './components/AppDialogs';
import { Shortcuts } from './components/Shortcuts';
import { Home } from './pages/Home';

function useNarrow() {
  const query = '(max-width: 1199px)';
  const [narrow, setNarrow] = useState(() => matchMedia(query).matches);
  useEffect(() => { const media = matchMedia(query), change = () => setNarrow(media.matches); media.addEventListener('change', change); return () => media.removeEventListener('change', change); }, []);
  return narrow;
}

/** I1 → I2: only the mark and the current step; past 8 seconds it becomes an error with a way out. */
function Connection() {
  const { error, refresh } = useApp();
  const [late, setLate] = useState(false);
  useEffect(() => { const timer = setTimeout(() => setLate(true), 8000); return () => clearTimeout(timer); }, []);
  const failed = !!error || late;
  return <div className="connection"><AppMark size={40} />
    {failed ? <><h2>简幕没有启动成功</h2><p>{error?.message ?? '本地服务没有响应。'}项目文件没有受到影响。</p><Button variant="primary" onClick={() => { setLate(false); void refresh(); }}>重试</Button></>
      : <><h2>正在打开简幕</h2><span className="connection-bar" role="progressbar" aria-label="正在打开" /></>}
  </div>;
}

export function App() {
  const { state, error, act, mutate, command, flush } = useApp();
  const w = useWorkspace();
  const narrow = useNarrow();
  const [leftOpen, setLeftOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const project = state?.project;
  const running = state?.job?.state === 'running' || state?.job?.state === 'stopping';
  const batchRunning = state?.batchTask?.state === 'running' || state?.batchTask?.state === 'stopping';

  useEffect(() => { if (project && w.page === 'home' && !state?.recents.length) w.setPage('workspace'); }, [project?.id]);
  useEffect(() => { if (!project && w.page === 'workspace') w.setPage('home'); }, [project?.id]);
  useEffect(() => { if (state?.pendingDrop) w.openDialog('drop', { ...state.pendingDrop, newProject: w.page === 'home' || !project }); }, [state?.pendingDrop?.id]);
  useEffect(() => { if (error?.code === 'BACKUP_AVAILABLE') w.openDialog('recover-project'); }, [error]);
  useEffect(() => { if (state?.closeRequested) w.openDialog('close'); }, [state?.closeRequested]);
  useEffect(() => { if (running || state?.job?.recovered) { w.setPage('workspace'); w.setTab('export'); w.setJobVisible(true); } }, [state?.job?.id, running]);
  useEffect(() => { if (!narrow) setLeftOpen(false); }, [narrow]);
  // A background check that finds a release, or a download finished behind a closed dialog, becomes one toast.
  useEffect(() => {
    const update = state?.update;
    if (!update?.version || w.dialog?.type === 'update') return;
    if (update.state === 'available') w.toast({ text: `简幕 ${update.version} 可以更新`, sticky: true, action: { label: '查看', run: () => w.openDialog('update') } });
    if (update.state === 'ready') w.toast({ text: `简幕 ${update.version} 已下载好`, sticky: true, action: { label: '重启并更新…', run: () => w.openDialog('update') } });
  }, [state?.update.state, state?.update.version]);
  // A dialog shows its own errors; elsewhere they become a toast that waits to be closed.
  useEffect(() => {
    if (!error || w.dialog || error.code === 'BACKUP_AVAILABLE' || error.code === 'CONNECTION_ERROR') return;
    w.toast({ text: error.code === 'SAVE_FAILED' ? `保存失败：${state?.saveError ?? error.message}` : error.message, tone: 'danger', sticky: true,
      action: error.code === 'SAVE_FAILED' ? { label: '重试保存', run: () => act(async () => { await flush(); await command('retry_save'); }) } : undefined });
  }, [error]);

  // Import progress lives in the left panel; its end becomes one toast (I7) and the first new picture becomes current (I9).
  const importStart = useRef<{ id: string; known: Set<string> } | null>(null);
  useEffect(() => {
    const task = state?.importTask;
    if (!task) return;
    if (task.state === 'running' || task.state === 'stopping') {
      if (importStart.current?.id !== task.id) importStart.current = { id: task.id, known: new Set(project?.assets.map(a => a.id)) };
      return;
    }
    const known = importStart.current?.id === task.id ? importStart.current.known : null;
    importStart.current = null;
    const r = task.result ?? { imported: 0, duplicates: 0, issues: 0 };
    const text = task.state === 'failed' ? `导入中断：${task.error}` : task.state === 'cancelled' ? `已停止导入，保留已读取的 ${count(r.imported)} 张`
      : r.imported ? `已导入 ${count(r.imported)} 张${r.issues ? `，${count(r.issues)} 个文件没有导入` : ''}${r.duplicates ? `，跳过 ${count(r.duplicates)} 张重复` : ''}`
      : r.duplicates ? `没有新图片：${count(r.duplicates)} 张已经在项目里` : '没有找到可以导入的图片';
    w.toast({ text, tone: r.issues || task.state === 'failed' ? 'warn' : undefined, sticky: !!r.issues || task.state === 'failed', action: r.issues ? { label: '查看记录', run: () => w.openDialog('import-issues') } : undefined });
    const fresh = known && project?.assets.find(a => !known.has(a.id));
    if (fresh) w.choose(fresh.id);
    act(() => command('dismiss_import', { taskId: task.id }));
  }, [state?.importTask?.state, state?.importTask?.id]);

  // System undo / redo when no text field owns the keystroke; typing keeps the field's own undo.
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (!(e.ctrlKey || e.metaKey) || e.altKey || e.isComposing || (key !== 'z' && key !== 'y')) return;
      if (w.dialog || w.page !== 'workspace' || running || batchRunning || (e.target as HTMLElement).closest('input, textarea, [contenteditable="true"]')) return;
      const redo = key === 'y' || e.shiftKey;
      if (!(redo ? state?.canRedo : state?.canUndo)) return;
      e.preventDefault();
      act(() => mutate(redo ? 'redo' : 'undo'));
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  });

  if (!state) return <Connection />;
  // The whole window accepts files; the desktop host reads the real paths (I4, I9).
  const drop = {
    onDragEnter: (e: DragEvent) => { if (e.dataTransfer.types.includes('Files')) { depth.current++; setDragging(true); } },
    onDragLeave: () => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); },
    onDragOver: (e: DragEvent) => e.preventDefault(),
    onDrop: (e: DragEvent) => {
      e.preventDefault(); depth.current = 0; setDragging(false);
      const host = (window as unknown as { chrome?: { webview?: { postMessageWithAdditionalObjects: (message: string, objects: FileList) => void } } }).chrome?.webview;
      if (host && e.dataTransfer.files.length) host.postMessageWithAdditionalObjects('FilesDropped', e.dataTransfer.files);
      else if (!state.desktop) w.toast({ text: '浏览器预览不能读取拖入的文件，请在桌面版中拖入', tone: 'warn' });
    },
  };
  const accepting = !running && !batchRunning;
  return <Tooltip.Provider delay={500} closeDelay={0}>
    {w.page === 'home' || !project ? <div className="home-shell" {...drop}><Home dragging={dragging && accepting} /><div className="home-toasts"><Toasts /></div></div>
      : <div className={`shell ${narrow ? 'narrow' : ''} ${batchRunning ? 'locked' : ''}`} aria-busy={batchRunning || undefined} {...drop}>
        {narrow ? <div className="mini-panel"><AppMark /><strong className="truncate">{project.name}</strong>
          <span className="numeric">{Math.max(0, w.assets.findIndex(a => a.id === w.activeId) + 1)} / {w.assets.length}</span>
          <IconButton label={leftOpen ? '收起左栏' : '展开左栏'} side="bottom" toggled={leftOpen} onClick={() => setLeftOpen(open => !open)}><PanelLeft /></IconButton></div> : null}
        {(!narrow || leftOpen) && <div className="left-slot" inert={running || batchRunning}><LeftPanel floating={narrow} onHome={() => act(async () => { await flush(); w.setPage('home'); })} /></div>}
        <div className="center-slot" inert={batchRunning} onPointerDown={() => { if (narrow && leftOpen) setLeftOpen(false); }}><Center dragging={dragging && accepting} /></div>
        <RightPanel />
      </div>}
    <AppDialogs />
    <Shortcuts />
  </Tooltip.Provider>;
}
