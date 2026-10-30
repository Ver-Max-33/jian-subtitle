import { useEffect, useRef, useState } from 'react';
import { ArrowUpDown, Check, ChevronDown, Circle, CircleAlert, ImageOff, Images, Minus, Plus, Search, X } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { CaptionStatus, OrderMode } from '../types';
import { count, filterNames, filterOrder, orderNames, sameAspect, type Filter } from '../format';
import { AppMark, IconButton, Menu, type MenuEntry } from './ui';
import { AssetList } from './AssetList';

export const statusIcon = (status: Filter) => status === 'all' ? <Images /> : status === 'issue' ? <CircleAlert className="tone-danger" /> : status === 'ready' ? <Check className="tone-success" /> : status === 'missing' ? <Circle className="tone-muted" />
  : status === 'needs_review' ? <span className="dot warn" /> : status === 'no_caption' ? <Minus className="tone-muted" /> : <ImageOff className="tone-danger" />;

/** Quick saves stay "已保存"; the words change only when a write is slow enough to notice (>300 ms). */
function SaveStatus() {
  const { state, busy, dirty, act, flush, command } = useApp();
  const [slow, setSlow] = useState(false);
  useEffect(() => { if (!busy) { setSlow(false); return; } const timer = setTimeout(() => setSlow(true), 300); return () => clearTimeout(timer); }, [busy > 0]);
  if (state?.saveError) return <span className="save-status failed">保存失败 · <button type="button" className="link" onClick={() => act(async () => { await flush(); await command('retry_save'); })}>重试</button></span>;
  return <span className="save-status">{slow ? '正在保存…' : dirty ? '等待保存…' : '已保存'}</span>;
}

/** The 幕 ▾ menu, shared by the home page and the workspace. */
export function useAppMenu(): MenuEntry[] {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const open = (action: string, payload: Record<string, unknown> = {}) => act(async () => {
    const result = await mutate<{ cancelled?: boolean }>(action, payload);
    if (!result?.cancelled) w.setPage('workspace');
  });
  const recents = state?.recents ?? [];
  const update = state?.update;
  return [
    { label: '新建项目…', action: () => w.openDialog('new-project', { importAction: 'choose_images' }) },
    { label: '打开项目…', action: () => open('open_project') },
    { label: '最近项目', disabled: !recents.length, children: [...recents.slice(0, 3).map(r => ({ label: r.name, hint: `${count(r.count)} 张`, action: () => open('open_recent', { index: r.index }) })), ...(recents.length > 3 ? [{ separator: true }, { label: `查看全部 ${recents.length} 个…`, action: () => w.openDialog('recents') }] : [])] },
    { separator: true },
    { label: '导入说话人名单…', disabled: !state?.project || w.page !== 'workspace', action: () => act(() => mutate('import_speakers')) },
    ...(update?.supported ? [{ label: update.version ? `更新到 ${update.version}…` : '检查更新…', action: () => w.openDialog('update') }] : []),
    { label: '关于简幕', action: () => w.openDialog('about') },
    { separator: true },
    { label: '退出简幕', action: () => w.openDialog('close') },
  ];
}

function ProjectTitle({ onHome }: { onHome: () => void }) {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const project = w.project!;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) { setName(project.name); requestAnimationFrame(() => input.current?.select()); } }, [editing]);
  const save = () => { setEditing(false); const next = name.trim(); if (next && next !== project.name) act(() => mutate('rename', { name: next })); };
  const task = state?.importTask;
  const importing = task && (task.state === 'running' || task.state === 'stopping');
  if (editing) return <div className="project-title"><input ref={input} className="rename-input" aria-label="项目名称" value={name} maxLength={100}
    onChange={e => setName(e.target.value)} onBlur={save}
    onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) save(); if (e.key === 'Escape') { e.stopPropagation(); setEditing(false); } }} /></div>;
  return <div className="project-title">
    <Menu label="项目菜单" className="project-name" items={[
      { label: '重命名', action: () => setEditing(true) },
      { label: '另存项目副本…', action: () => act(() => mutate('save_as')) },
      { label: '重新定位源图片…', action: () => w.openDialog('relocate') },
      { label: '查看导出任务', disabled: !state?.job, action: () => w.setTab('export') },
      { separator: true },
      { label: '返回所有项目', action: onHome },
    ]}><strong onDoubleClick={e => { e.preventDefault(); setEditing(true); }}>{project.name}</strong><ChevronDown /></Menu>
    <small className="project-sub">{importing ? <>正在导入 {count(task.completed)} / {count(task.total)} 张</> : <>{count(project.assets.length)} 张图片 · <SaveStatus /></>}</small>
  </div>;
}

function SearchBox() {
  const w = useWorkspace();
  const [text, setText] = useState(w.query);
  const [open, setOpen] = useState(!!w.query);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { const timer = setTimeout(() => w.setQuery(text), 150); return () => clearTimeout(timer); }, [text]);
  useEffect(() => { if (!w.query) setText(''); }, [w.query]);
  const close = () => { setText(''); w.setQuery(''); setOpen(false); };
  if (!open) return <IconButton label="搜索图片" onClick={() => { setOpen(true); requestAnimationFrame(() => field.current?.focus()); }}><Search /></IconButton>;
  return <label className="search-box"><Search /><input ref={field} aria-label="搜索字幕、文件名或说话人" placeholder="搜索字幕、文件名、说话人" value={text}
    onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } }} onBlur={() => { if (!text) setOpen(false); }} />
    <IconButton label="清除搜索" tip={false} onMouseDown={e => e.preventDefault()} onClick={close}><X /></IconButton></label>;
}

function SelectionMenu() {
  const w = useWorkspace();
  const visibleIds = w.visible.map(a => a.id);
  const chosen = new Set(w.selection);
  const current = w.asset;
  const add = (ids: string[]) => w.setSelection(list => [...new Set([...list, ...ids])]);
  return <Menu label="选择工具" className="selection-trigger" items={[
    { label: '全选当前筛选', hint: `${count(visibleIds.length)} 张`, action: () => add(visibleIds) },
    { label: '选择同宽高比的图片', disabled: !current?.width, action: () => current && add(w.assets.filter(a => sameAspect(a, current)).map(a => a.id)) },
    { label: '选择同状态的图片', disabled: !current, action: () => current && add(w.assets.filter(a => a.status === current.status).map(a => a.id)) },
    { label: '反选当前筛选', action: () => w.setSelection(list => [...list.filter(id => !visibleIds.includes(id)), ...visibleIds.filter(id => !chosen.has(id))]) },
    { separator: true },
    { label: '取消全部选择', hint: `${count(w.selection.length)} 张`, action: () => w.setSelection([]) },
  ]}><span className={`checkbox-visual ${w.selection.length >= w.visible.length && w.visible.length ? 'checked' : 'mixed'}`} aria-hidden>{w.selection.length >= w.visible.length && w.visible.length ? <Check /> : <Minus />}</span>已选 {count(w.selection.length)} 张<ChevronDown /></Menu>;
}

export function LeftPanel({ onHome, floating = false }: { onHome: () => void; floating?: boolean }) {
  const { state, act, mutate, command } = useApp();
  const w = useWorkspace();
  const project = w.project!;
  const counts = project.assets.reduce<Record<string, number>>((n, a) => ({ ...n, [a.status]: (n[a.status] || 0) + 1 }), {});
  const issueCount = w.issueIds.filter(id => w.byId.has(id)).length;
  const shown: Filter[] = [...(w.issueIds.length ? ['issue' as const] : []), ...filterOrder.filter(f => f !== 'unreadable' || counts.unreadable || w.filter === 'unreadable')];
  const menu = useAppMenu();
  const setOrder = (mode: OrderMode) => act(() => mode === 'manual' ? mutate('reorder_assets', { assetIds: project.assets.map(a => a.id) }) : mutate('set_order', { mode }));
  const ties = project.orderMode.startsWith('time') ? project.assets.filter(a => a.timeTie).length : 0;
  const task = state?.importTask;
  const importing = task && (task.state === 'running' || task.state === 'stopping');
  const add = (action: string, payload: Record<string, unknown> = {}) => act(() => mutate(action, payload));
  return <aside className={`left-panel ${floating ? 'floating' : ''}`} aria-label="项目与图片">
    <div className="left-top">
      <Menu label="应用菜单" className="app-menu-trigger" items={menu}><AppMark /><ChevronDown /></Menu>
      <ProjectTitle onHome={onHome} />
    </div>
    <section className="left-section" aria-label="按状态筛选">
      <header className="left-head"><h3>状态</h3>
        <Menu label="排序方式" tip align="end" items={[
          { heading: '排序方式' },
          ...(Object.keys(orderNames) as OrderMode[]).map(mode => ({ label: orderNames[mode], checked: project.orderMode === mode, action: () => { if (project.orderMode !== mode) setOrder(mode); } })),
          { separator: true },
          { heading: '没有拍摄记录时，按文件创建与修改时间中较早的一个；复制过的文件也能排对。' },
        ]}><ArrowUpDown /></Menu>
      </header>
      <div className="filter-list" role="radiogroup" aria-label="图片状态">{shown.map(f => {
        const n = f === 'all' ? project.assets.length : f === 'issue' ? issueCount : counts[f as CaptionStatus] || 0;
        const row = <button key={f} type="button" role="radio" aria-checked={w.filter === f} className={`filter-row ${w.filter === f ? 'selected' : ''}`} onClick={() => w.setFilter(f)}>
          <span className="filter-icon">{statusIcon(f)}</span><span className="filter-label">{f === 'issue' ? w.issueLabel : filterNames[f]}</span><span className="filter-count">{count(n)}</span>
        </button>;
        return f === 'issue' ? <div key={f} className="filter-item">{row}
          <button type="button" className="filter-clear" aria-label={`清除${w.issueLabel}筛选`} onClick={() => { w.setIssueIds([]); w.setFilter('all'); }}><X /></button></div> : row;
      })}</div>
    </section>
    <section className="left-section images" aria-label="图片">
      <header className="left-head">{w.batch ? <SelectionMenu /> : <h3>图片</h3>}<div className="left-head-actions"><SearchBox />
        <Menu label="添加图片" tip align="end" disabled={!!importing} items={[
          { label: '选择图片…', action: () => add('choose_images') },
          { label: '选择文件夹…', action: () => add('choose_folder') },
          { label: '选择文件夹（含子文件夹）…', action: () => add('choose_folder', { recursive: true }) },
          { separator: true },
          { label: '导入说话人名单…', action: () => add('import_speakers') },
        ]}><Plus /></Menu></div>
      </header>
      {importing && <div className="import-progress" role="status"><div className="section-line"><small>{task.state === 'stopping' ? '正在停止，已读取的图片会保留…' : '正在读取文件信息…'}</small>
        <small className="numeric">{Math.round(task.completed / Math.max(1, task.total) * 100)}%{task.state === 'running' && <> · <button type="button" className="link" onClick={() => act(() => command('cancel_import', { taskId: task.id }))}>停止</button></>}</small></div>
        <progress max={task.total} value={task.completed} aria-label="导入进度" /></div>}
      {ties > 0 && !importing && <p className="tie-note"><span className="dot warn" />{ties} 张图片时间相同，已按文件名排在一起<button type="button" className="link" onClick={() => setOrder('manual')}>改为手动顺序</button></p>}
      <AssetList />
    </section>
  </aside>;
}
