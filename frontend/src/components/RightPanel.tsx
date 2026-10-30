import type { CSSProperties } from 'react';
import { Tabs } from '@base-ui/react/tabs';
import { ChevronDown, FolderOpen, Redo2, Undo2, X } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace, type Tab } from '../workspace';
import { count } from '../format';
import { Button, IconButton, Menu } from './ui';
import { Inspector } from './Inspector';
import { ExportPanel, useExportAction } from './ExportPanel';

const zoomSteps = [10, 25, 50, 75, 100, 150, 200, 300, 400];

function ZoomMenu() {
  const w = useWorkspace();
  const current = w.zoom === 'fit' ? w.scale : Number(w.zoom);
  const by = (direction: 1 | -1) => {
    const next = direction > 0 ? zoomSteps.find(s => s > current * 1.02) : [...zoomSteps].reverse().find(s => s < current * .98);
    if (next) w.setZoom(String(next));
  };
  return <Menu label="缩放" tip align="end" className="zoom-trigger" disabled={!w.asset || w.view === 'list' || w.batch} items={[
    { label: '放大', hint: 'Ctrl + 滚轮', disabled: current >= 400, action: () => by(1), keepOpen: true },
    { label: '缩小', disabled: current <= 10, action: () => by(-1), keepOpen: true },
    { separator: true },
    { label: '适应画布', checked: w.zoom === 'fit', action: () => w.setZoom('fit') },
    ...[50, 100, 200].map(n => ({ label: `${n}%`, checked: w.zoom === String(n), action: () => w.setZoom(String(n)) })),
  ]}><span className="numeric">{current ? `${Math.round(current)}%` : '—'}</span><ChevronDown /></Menu>;
}

/** The import runs as one step behind the list; editing waits for it so no edit interleaves with its batches. */
function ImportBlock() {
  const { state } = useApp();
  const task = state?.importTask;
  if (!task || (task.state !== 'running' && task.state !== 'stopping')) return null;
  return <section className="task-block running" role="status" aria-live="polite">
    <div className="section-line"><strong>{task.state === 'stopping' ? '正在停止导入…' : '正在导入图片'}</strong><small className="numeric">{count(task.completed)} / {count(task.total)} 张</small></div>
    <div className="progress"><span style={{ '--progress': task.total ? task.completed / task.total : 0 } as CSSProperties} /></div>
    <small className="section-hint">导入结束后可以编辑；现在可以浏览和预览。整次导入是一步，可以一次撤销。</small>
  </section>;
}

function BatchTaskBlock() {
  const { state, act, command } = useApp();
  const w = useWorkspace();
  const task = state?.batchTask;
  if (!task) return null;
  const running = task.state === 'running' || task.state === 'stopping';
  return <section className={`task-block ${running ? 'running' : task.state}`} role="status" aria-live="polite">
    <div className="section-line"><strong>{running ? task.state === 'stopping' ? '正在取消…' : '批量处理中' : task.state === 'complete' ? `已应用到 ${count(task.result?.updated ?? 0)} 张图片` : task.state === 'cancelled' ? '已取消，项目未改变' : '批量处理失败，项目未改变'}</strong>
      {!running && <IconButton label="收起摘要" onClick={() => act(() => command('dismiss_batch', { taskId: task.id }))}><X /></IconButton>}</div>
    {running ? <>
      <div className="progress"><span style={{ '--progress': task.total ? task.completed / task.total : 0 } as CSSProperties} /></div>
      <div className="section-line"><small className="numeric">{count(task.completed)} / {count(task.total)} 张 · {task.filename}</small><Button disabled={task.state === 'stopping'} onClick={() => act(() => command('cancel_batch', { taskId: task.id }))}>取消本次操作</Button></div>
      <small className="section-hint">整批作为一次修改，取消即回到开始前</small>
    </> : <>
      {task.error && <small className="section-hint tone-danger">{task.error}</small>}
      {!!task.result?.warnings && <div className="task-warnings">{task.result.warningAssets.map(item => <div key={item.assetId} className="section-line"><small className="truncate">{w.byId.get(item.assetId)?.filename}：{item.message}</small><button type="button" className="link" onClick={() => w.choose(item.assetId)}>定位</button></div>)}</div>}
      {!!task.result?.skipped && <small className="section-hint">跳过 {count(task.result.skipped)} 张没有对应字幕的图片</small>}
    </>}
  </section>;
}

export function RightPanel() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const job = state?.job;
  const running = job?.state === 'running' || job?.state === 'stopping';
  const batchRunning = state?.batchTask?.state === 'running' || state?.batchTask?.state === 'stopping';
  const importing = state?.importTask?.state === 'running' || state?.importTask?.state === 'stopping';
  const exportAction = useExportAction();
  const none = !w.assets.length;
  return <aside className="right-panel" aria-label="属性">
    <header className="right-top">
      <IconButton label="撤销" shortcut="Ctrl+Z" disabled={!state?.canUndo || running || batchRunning || importing} onClick={() => act(() => mutate('undo'))}><Undo2 /></IconButton>
      <IconButton label="重做" shortcut="Ctrl+Shift+Z" disabled={!state?.canRedo || running || batchRunning || importing} onClick={() => act(() => mutate('redo'))}><Redo2 /></IconButton>
      <span className="spacer" />
      {w.tab === 'edit' ? <>{w.returnToExport && <Button variant="ghost" onClick={w.backToExport}>回到导出</Button>}
        <Button variant="primary" disabled={none || batchRunning || importing} onClick={() => w.setTab('export')}>导出</Button></>
        : <Button variant={exportAction.variant} disabled={exportAction.disabled || none} onClick={exportAction.run}>{'folder' in exportAction && <FolderOpen />}{exportAction.label}</Button>}
    </header>
    <Tabs.Root value={w.tab} onValueChange={value => { if (value === 'export') w.backToExport(); else w.setTab(value as Tab); }} className="right-tabs">
      <Tabs.List className="tab-list" aria-label="右栏">
        <Tabs.Tab value="edit" className="tab" disabled={running}>编辑</Tabs.Tab>
        <Tabs.Tab value="export" className="tab" disabled={none || batchRunning || importing}>导出</Tabs.Tab>
        <Tabs.Indicator className="tab-indicator" />
      </Tabs.List>
      <ZoomMenu />
    </Tabs.Root>
    <div className="right-scroll" key={w.tab}>
      <ImportBlock />
      <BatchTaskBlock />
      <div className={`right-content ${importing ? 'paused' : ''}`} inert={batchRunning || importing}>{w.tab === 'edit' ? <Inspector /> : <ExportPanel />}</div>
    </div>
  </aside>;
}
