import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { ArrowRight, FolderOpen, MoreHorizontal, Plus } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import { count, dayTime } from '../format';
import { AppMark, Button, Checkbox, Menu, Modal, TextField } from './ui';

interface View { title: string; body?: ReactNode; footer?: ReactNode; className?: string }
type Replace = { matches: { before: string; after: string }[]; images: number; revision: number };

export function AppDialogs() {
  const { state, mutate, command, act, flush, busy, setError } = useApp();
  const w = useWorkspace();
  const dialog = w.dialog;
  // The last dialog keeps rendering while it animates out; one mounted Modal lets Base UI play enter and exit.
  const [shown, setShown] = useState(dialog);
  const [text, setText] = useState('');
  const [replacement, setReplacement] = useState('');
  const [flag, setFlag] = useState(false);
  const [preview, setPreview] = useState<Replace>();
  const [renaming, setRenaming] = useState<string | null>(null);
  // 「立即更新」 waits in the dialog: once the download is verified it installs; closing the dialog lets it finish in the background.
  const installing = useRef(false);
  const project = state?.project;
  useEffect(() => {
    setError(null);
    if (!dialog) return;
    setShown(dialog);
    const data = dialog.data;
    setText(dialog.type === 'new-project' || dialog.type === 'drop' ? '新字幕项目' : '');
    setReplacement(''); setFlag(false); setPreview(undefined); setRenaming(null);
    if (dialog.type === 'preset-rename') setText(String(data.name));
    if (dialog.type === 'update') {
      installing.current = false;
      const update = state?.update;
      if (update?.supported && (update.state === 'idle' || update.state === 'latest' || (update.state === 'failed' && !update.version))) act(() => command('update_check'));
    }
  }, [dialog]);
  const updateState = state?.update.state;
  useEffect(() => {
    const busyTask = [state?.job, state?.batchTask, state?.importTask].some(task => task && (task.state === 'running' || task.state === 'stopping'));
    if (updateState !== 'ready' || !installing.current || w.dialog?.type !== 'update' || busyTask) return;
    installing.current = false;
    act(() => mutate('update_install'));
  }, [updateState]);
  useEffect(() => { setPreview(undefined); }, [text, replacement, project?.revision]);
  if (!state) return null;
  const close = () => {
    if (dialog?.type === 'close') act(() => command('cancel_close'));
    if (dialog?.type === 'drop' && state.pendingDrop) act(() => command('dismiss_drop', { dropId: dialog.data.id }));
    installing.current = false;
    w.setDialog(null);
  };
  const done = async <T,>(action: string, payload: Record<string, unknown> = {}) => { const result = await mutate<T>(action, payload); w.setDialog(null); return result; };
  const cancel = <Button onClick={close}>取消</Button>;
  const current = dialog ?? shown;
  const caption = w.caption, asset = w.asset;
  const scope = { assetId: asset?.id, captionId: caption?.id };
  const view = (): View | null => {
    if (!current) return null;
    const data = current.data;
    const ids = Array.isArray(data.assetIds) ? data.assetIds as string[] : w.selection;
    const visible = new Set(w.visible.map(a => a.id));
    const outside = Array.isArray(data.assetIds) ? 0 : ids.filter(id => !visible.has(id)).length;
    const reach = <p className="dialog-scope"><span>作用范围</span><strong>{count(ids.length)} 张图片{outside ? `（含筛选外 ${outside} 张）` : ''}</strong></p>;
    switch (current.type) {
      case 'new-project': {
        const folder = data.importAction === 'choose_folder';
        return { title: '创建字幕项目', body: <>
          <label className="dialog-field"><span>项目名称</span><input aria-label="项目名称" value={text} maxLength={100} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && text.trim()) (document.querySelector('.dialog-footer .button.primary') as HTMLElement | null)?.click(); }} /></label>
          {folder && <label className="check-label"><Checkbox label="包含子文件夹" checked={flag} onChange={setFlag} />包含子文件夹</label>}
          <small className="muted">项目会自动保存；之后可以在项目菜单里另存副本</small>
        </>, footer: <>{cancel}<Button variant="primary" disabled={!text.trim() || !!busy} onClick={() => act(async () => {
          const r = await mutate<{ cancelled?: boolean }>(String(data.importAction), { newProjectName: text.trim(), ...(folder ? { recursive: flag } : {}) });
          if (!r?.cancelled) { w.setDialog(null); w.setPage('workspace'); }
        })}>{folder ? '选择文件夹并创建' : '选择图片并创建'}</Button></> };
      }
      case 'drop': return { title: '导入拖入的图片', body: <>
        {data.newProject === true && <label className="dialog-field"><span>项目名称</span><input aria-label="项目名称" value={text} maxLength={100} onChange={e => setText(e.target.value)} /></label>}
        <p>已拖入 {count(Number(data.count))} 个文件或文件夹。</p>
        {data.folders === true && <label className="check-label"><Checkbox label="包含子文件夹" checked={flag} onChange={setFlag} />包含子文件夹</label>}
        <small className="muted">损坏、无权限或重复的文件不会中断导入，结束后统一报告</small>
      </>, footer: <>{cancel}<Button variant="primary" disabled={!!busy || (data.newProject === true && !text.trim())} onClick={() => act(async () => {
        await mutate('accept_drop', { dropId: data.id, recursive: flag, ...(data.newProject ? { newProjectName: text.trim() } : {}) });
        w.setDialog(null); w.setPage('workspace');
      })}>导入图片</Button></> };
      case 'recover-project': return { title: '恢复项目备份？', body: <><p>项目文件无法读取，找到一份自动备份。</p><p className="muted">原项目文件会保留，恢复内容另存为新的项目副本，不会覆盖。</p></>,
        footer: <>{cancel}<Button variant="primary" onClick={() => act(async () => { await done('recover_project'); w.setPage('workspace'); })}>恢复为副本</Button></> };
      case 'about': return { title: '关于简幕', className: 'about-dialog', body: <div className="about"><AppMark size={48} /><strong>简幕 {state.update.current}</strong><span>图片字幕编辑器</span><p>选择图片、校对文字、调整样式，再导出带字幕的图片。</p><small className="muted">界面字体：思源黑体（SIL OFL）· 内置字幕字体与第三方许可见安装目录</small></div>,
        footer: <Button variant="primary" onClick={close}>知道了</Button> };
      case 'reset': return { title: data.scope === 'position' ? '恢复当前字幕的位置？' : '恢复当前字幕的样式？', body: <p>只影响当前字幕，不改变文字和其他图片。恢复后仍可撤销。</p>,
        footer: <>{cancel}<Button variant="primary" disabled={!caption} onClick={() => act(() => done('caption_reset', { ...scope, scope: data.scope }))}>恢复默认</Button></> };
      case 'smart': return { title: '启用智能避让？', body: <p>当前字幕改为自动位置，并与本图其他自动字幕一起排列。其他手动字幕保持不变；空间不足时保留原位置。可以撤销。</p>,
        footer: <>{cancel}<Button variant="primary" onClick={() => { w.setDialog(null); w.rearrange(); }}>重新排列</Button></> };
      case 'delete-caption': return { title: '删除这条字幕？', body: <p>只删除当前字幕。删除最后一条后，图片会变为待补字幕。可以撤销。</p>,
        footer: <>{cancel}<Button variant="danger" disabled={!caption} onClick={() => act(() => done('caption_delete', scope))}>删除字幕</Button></> };
      case 'batch-speaker': return { title: '设置说话人', body: <>{reach}
        <label className="dialog-field"><span>姓名</span><input aria-label="说话人姓名" list="speaker-names" value={text} maxLength={80} placeholder="留空表示清除" onChange={e => setText(e.target.value)} /></label>
        <datalist id="speaker-names">{project?.speakers.map(s => <option key={s} value={s} />)}</datalist>
        <small className="muted">应用到这 {count(ids.length)} 张图片的所有字幕；已确认的图片会回到需检查。</small></>,
        footer: <>{cancel}<Button variant="primary" disabled={!ids.length || !!busy} onClick={() => act(() => done('batch', { operation: 'speaker', assetIds: ids, speaker: text.trim() }))}>应用到 {count(ids.length)} 张</Button></> };
      case 'batch': {
        const operation = String(data.operation);
        const n = count(ids.length);
        const copy: Record<string, [string, string, string]> = {
          extract: ['重新提取字幕？', '从原文件名重新识别。时间、序号和相机编号型文件名不会作为字幕。', `重新提取 ${n} 张`],
          no_caption: ['设为无需字幕？', '已有字幕文字会被清空；导出时按设置复制原图。可以撤销。', `设为无需字幕 ${n} 张`],
          clear: ['清空字幕？', `这 ${n} 张图片的字幕文字会被清空，图片变为待补字幕。可以撤销。`, `清空 ${n} 张`],
          remove: [`移除 ${n} 张图片？`, '只从项目中移除，源图片不会被删除。可以撤销。', `移除 ${n} 张`],
        };
        const [title, body, action] = copy[operation];
        return { title, body: <>{reach}<p>{body}</p>{operation === 'extract' && <label className="check-label"><Checkbox label="覆盖手动修改过的字幕" checked={flag} onChange={setFlag} /><span>覆盖手动修改过的字幕<small>不勾选时，手动改过的字幕保持不变</small></span></label>}</>,
          footer: <>{cancel}<Button variant={operation === 'remove' || operation === 'clear' ? 'danger' : 'primary'} disabled={!ids.length || !!busy} onClick={() => act(async () => {
            await done('batch', { operation, assetIds: ids, overwrite: flag });
            if (operation === 'remove') w.setSelection(list => list.filter(id => !ids.includes(id)));
          })}>{action}</Button></> };
      }
      case 'extract-one': {
        const target = w.byId.get(String(data.assetId));
        return { title: '重新提取这张图的字幕？', body: <><p>从文件名「{target?.filename}」重新识别字幕。时间、序号和相机编号型文件名不会作为字幕。</p>
          <label className="check-label"><Checkbox label="覆盖手动修改过的字幕" checked={flag} onChange={setFlag} /><span>覆盖手动修改过的字幕<small>不勾选时，手动改过的字幕保持不变</small></span></label></>,
          footer: <>{cancel}<Button variant="primary" disabled={!target || !!busy} onClick={() => act(() => done('batch', { operation: 'extract', assetIds: [target!.id], overwrite: flag }))}>重新提取</Button></> };
      }
      case 'replace': return { title: '替换文字', body: <>
        <p className="muted">已选 {count(ids.length)} 张。替换后这些字幕需要重新确认，可整体撤销。</p>
        <label className="dialog-field"><span>查找</span><input aria-label="查找文字" value={text} maxLength={1000} onChange={e => setText(e.target.value)} /></label>
        <label className="dialog-field"><span>替换为</span><input aria-label="替换为" value={replacement} maxLength={1000} onChange={e => setReplacement(e.target.value)} /></label>
        {preview && <div className="replace-preview"><strong>{count(preview.images)} 张图片，{count(preview.matches.length)} 条字幕命中</strong>
          {preview.matches.slice(0, 6).map((m, i) => <div key={i} className="replace-row"><del>{m.before}</del><ArrowRight /><span>{m.after || '（清空）'}</span></div>)}
          {preview.matches.length > 6 && <small className="muted">… 另有 {count(preview.matches.length - 6)} 条</small>}</div>}
      </>, footer: <>{cancel}{preview
        ? <Button variant="primary" disabled={!preview.matches.length || preview.revision !== project?.revision || !!busy} onClick={() => act(() => done('replace', { assetIds: ids, search: text, replacement }))}>替换 {count(preview.matches.length)} 条</Button>
        : <Button variant="primary" disabled={!text || !ids.length || !!busy} onClick={() => act(async () => setPreview(await mutate<Replace>('replace_preview', { assetIds: ids, search: text, replacement })))}>预览替换结果</Button>}</> };
      case 'presets': return { title: '我的预设', className: 'presets-dialog', body: <>
        <div className="preset-rows">
          {state.builtinPresets.map(card => <div key={card.name} className="preset-row"><span>{card.name}</span><small className="muted">内置{card.fontLabel ? ` · ${card.fontLabel}` : ''}</small></div>)}
          {state.presets.map(name => <div key={name} className="preset-row">
            {renaming === name ? <input className="field inline-input" autoFocus aria-label="预设名称" defaultValue={name} maxLength={64}
              onBlur={e => { const next = e.currentTarget.value.trim(); setRenaming(null); if (next && next !== name) act(() => mutate('preset', { operation: 'rename', name, newName: next })); }}
              onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { e.stopPropagation(); setRenaming(null); } }} />
              : <span onDoubleClick={() => setRenaming(name)}>{name}</span>}
            <small className="muted">{state.defaultPreset === name ? '新项目默认' : ''}</small>
            <Menu label={`${name} 的操作`} align="end" items={[
              { label: '重命名', action: () => setRenaming(name) },
              { label: '用当前样式覆盖', disabled: !caption, action: () => w.openDialog('preset-overwrite', { name }) },
              { label: '设为新项目默认', disabled: state.defaultPreset === name, action: () => act(() => mutate('preset', { operation: 'default', name })) },
              { separator: true },
              { label: '删除预设…', danger: true, action: () => w.openDialog('preset-delete', { name }) },
            ]}><MoreHorizontal /></Menu>
          </div>)}
        </div>
        <div className="dialog-inline"><TextField label="新预设名称" placeholder="新预设名称" value={text} maxLength={64} onChange={setText} />
          <Button disabled={!text.trim() || !caption || !!busy} onClick={() => act(async () => { await mutate('preset', { ...scope, operation: 'save', name: text.trim() }); setText(''); })}><Plus />保存当前样式</Button></div>
        {!caption && <small className="muted">选中一条字幕后，可以把它的样式存为预设</small>}
      </>, footer: <Button onClick={close}>关闭</Button> };
      case 'preset-save': return { title: '存为新预设', body: <label className="dialog-field"><span>预设名称</span><input aria-label="预设名称" value={text} maxLength={64} onChange={e => setText(e.target.value)} /></label>,
        footer: <>{cancel}<Button variant="primary" disabled={!text.trim() || !caption || !!busy} onClick={() => act(() => done('preset', { ...scope, operation: 'save', name: text.trim() }))}>保存</Button></> };
      case 'preset-overwrite': return { title: '覆盖这个预设？', body: <p>用当前字幕的样式覆盖「{String(data.name)}」。不会改变其他图片。</p>,
        footer: <><Button onClick={() => w.openDialog('presets')}>返回</Button><Button variant="primary" onClick={() => act(async () => { await mutate('preset', { ...scope, operation: 'save', name: data.name, overwrite: true }); w.openDialog('presets'); })}>覆盖预设</Button></> };
      case 'preset-delete': return { title: '删除这个预设？', body: <p>「{String(data.name)}」会从自定义预设中移除，已经应用到图片上的样式不受影响。</p>,
        footer: <><Button onClick={() => w.openDialog('presets')}>返回</Button><Button variant="danger" onClick={() => act(async () => { await mutate('preset', { operation: 'delete', name: data.name }); w.openDialog('presets'); })}>删除预设</Button></> };
      case 'relocate': return { title: '重新定位源图片', body: <><p>选择源图片现在所在的文件夹，简幕会按文件名、大小和修改时间匹配。</p><p className="muted">不会删除或移动源图；同名冲突不会自动猜测。</p></>,
        footer: <>{cancel}<Button variant="primary" onClick={() => act(async () => {
          const r = await mutate<{ relocated: number; unresolved: number; ambiguous: number; cancelled?: boolean }>('relocate');
          if (r.cancelled) return;
          w.setDialog(null);
          w.toast({ text: `恢复 ${count(r.relocated)} 张，未找到 ${count(r.unresolved)} 张，同名冲突 ${count(r.ambiguous)} 张`, tone: r.unresolved || r.ambiguous ? 'warn' : undefined, sticky: !!(r.unresolved || r.ambiguous) });
        })}><FolderOpen />选择文件夹…</Button></> };
      case 'import-issues': {
        const groups = new Map<string, string[]>();
        for (const issue of state.issues) groups.set(issue.message, [...(groups.get(issue.message) ?? []), issue.file]);
        return { title: '导入记录', body: state.issues.length ? <><strong>{count(state.issues.length)} 个文件没有导入</strong>{[...groups.entries()].map(([reason, files]) => <div key={reason} className="issue-group">
          <div className="section-line"><span>{reason}</span><small className="numeric">{files.length}</small></div>{files.slice(0, 20).map(f => <small key={f} className="muted truncate">{f}</small>)}{files.length > 20 && <small className="muted">… 另有 {files.length - 20} 个</small>}</div>)}</> : <p>这次导入没有问题。</p>,
          footer: <Button onClick={close}>关闭</Button> };
      }
      case 'recents': return { title: '最近项目', body: <><div className="recent-rows">{state.recents.map(r => <div key={r.path} className="recent-row-line">
        <div><strong>{r.name}</strong><small className="muted">{count(r.count)} 张 · {dayTime(r.updatedAt)}</small></div>
        <Button onClick={() => act(async () => { await done('open_recent', { index: r.index }); w.setPage('workspace'); })}>打开</Button>
        <Menu label={`${r.name} 的更多操作`} align="end" items={[{ label: '移除记录…', action: () => w.openDialog('remove-recent', { path: r.path, name: r.name }) }]}><MoreHorizontal /></Menu>
      </div>)}</div><small className="muted">从列表移除不会删除项目文件</small></>, footer: <Button onClick={close}>关闭</Button> };
      case 'remove-recent': return { title: '移除最近记录？', body: <p>只移除「{String(data.name)}」的最近记录，不删除项目文件。</p>,
        footer: <>{cancel}<Button variant="danger" onClick={() => act(() => done('remove_recent', { path: data.path }))}>移除记录</Button></> };
      case 'stop': return { title: '停止导出？', body: <p>当前图片写完后停止。已经成功的文件会保留，之后可以继续未完成的部分。</p>,
        footer: <><Button onClick={close}>继续导出</Button><Button variant="danger" onClick={() => act(() => done('stop_export', { jobId: state.job?.id }))}>安全停止</Button></> };
      case 'close': {
        const back = <Button onClick={close}>返回编辑</Button>;
        const task = state.batchTask;
        if (task && (task.state === 'running' || task.state === 'stopping')) return { title: '批量处理仍在进行', body: <p>请等待完成，或取消本次操作后再关闭。取消不会改变项目。</p>,
          footer: <><Button onClick={close}>返回处理</Button><Button disabled={task.state === 'stopping'} onClick={() => act(() => command('cancel_batch', { taskId: task.id }))}>取消本次操作</Button></> };
        const job = state.job;
        if (job && (job.state === 'running' || job.state === 'stopping')) return { title: '导出仍在进行', body: <p>请先停止导出。已成功的文件会保留，下次打开可以继续。</p>,
          footer: <><Button onClick={close}>返回</Button><Button variant="danger" disabled={job.state === 'stopping'} onClick={() => act(() => command('stop_export', { jobId: job.id }))}>安全停止</Button></> };
        if (state.saveError) return { title: '还有未保存的修改', body: <><p>无法保存「{project?.name}」：{state.saveError}</p><p className="muted">可以另存到其他位置；放弃会丢失最近一次保存之后的修改。</p></>,
          footer: <><Button variant="danger" onClick={() => act(() => command('close_app'))}>放弃修改</Button><Button onClick={() => act(() => mutate('save_as'))}>另存为…</Button>{back}</> };
        return { title: '关闭简幕？', body: <p>关闭前会保存当前输入；保存失败时会留在编辑器，不会丢失。</p>,
          footer: <>{back}<Button variant="primary" onClick={() => act(async () => { await flush(); await command('close_app'); })}>关闭</Button></> };
      }
      case 'update': {
        const u = state.update;
        const busyTask = [state.job, state.batchTask, state.importTask].some(task => task && (task.state === 'running' || task.state === 'stopping'));
        const mb = (bytes: number) => (bytes / 1048576).toFixed(1);
        const auto = <label className="check-label"><Checkbox label="启动时自动检查更新" checked={u.auto} onChange={value => act(() => command('update_auto', { enabled: value }))} />启动时自动检查更新</label>;
        const github = <Button onClick={() => act(() => command('open_releases'))}>到 GitHub 下载</Button>;
        if (!u.version) {
          const failed = u.state === 'failed', latest = u.state === 'latest';
          return { title: '检查更新', body: <><p className={failed ? 'dialog-error' : latest ? undefined : 'muted'}>{failed ? u.error : latest ? `简幕 ${u.current} 已是最新版本。` : '正在检查更新…'}</p>{auto}</>,
            footer: failed ? <>{github}<Button variant="primary" onClick={() => act(() => command('update_check'))}>重试</Button></> : <Button variant={latest ? 'primary' : 'secondary'} onClick={close}>{latest ? '好' : '关闭'}</Button> };
        }
        const ready = u.state === 'ready';
        const start = () => { installing.current = true; act(() => command('update_download')); };
        return { title: `更新到 ${u.version}`, body: <>
          <p className="muted">当前版本 {u.current}</p>
          {u.notes && <div className="update-notes">{u.notes}</div>}
          {u.state === 'downloading' && <div className="update-progress"><div className="progress"><span style={{ '--progress': u.total ? u.received / u.total : 0 } as CSSProperties} /></div><small className="muted numeric">正在下载 {mb(u.received)} / {mb(u.total)} MB</small></div>}
          {u.state === 'failed' && <p className="dialog-error">{u.error}</p>}
          {u.state === 'installing' ? <p>正在启动安装程序…</p> : <small className="muted">{ready ? '已下载并校验。' : ''}更新时简幕会关闭，装好后自动重新打开；项目都已保存。</small>}
          {ready && busyTask && <small className="dialog-error">导出、批量处理或导入结束后才能更新。</small>}
          {auto}
        </>, footer: u.state === 'downloading' ? <Button onClick={close}>后台下载</Button>
          : u.state === 'installing' ? null
          : u.state === 'failed' ? <>{github}<Button variant="primary" onClick={start}>重试</Button></>
          : <><Button onClick={close}>以后再说</Button><Button variant="primary" disabled={ready && busyTask} onClick={ready ? () => act(() => mutate('update_install')) : start}>{ready ? '重启并更新' : '立即更新'}</Button></> };
      }
      default: return null;
    }
  };
  const v = view();
  return <Modal open={!!dialog && !!v} onClose={close} onClosed={() => setShown(null)} title={v?.title ?? ''} footer={v?.footer} className={v?.className}>{v?.body}</Modal>;
}
