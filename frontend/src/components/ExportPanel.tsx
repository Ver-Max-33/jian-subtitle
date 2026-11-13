import { useEffect, useState, type CSSProperties } from 'react';
import { Popover } from '@base-ui/react/popover';
import { CheckCircle2, CircleAlert, Folder, LoaderCircle, RefreshCw, TriangleAlert } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Issue } from '../types';
import { count } from '../format';
import { Button, Checkbox, IconButton, NumberField, Section, Segmented, Select, SwitchRow, TextField } from './ui';
import { OutputPreview } from './OutputPreview';

const formats = [{ value: 'original', label: '保持原格式' }, { value: 'png', label: 'PNG · 无损' }, { value: 'jpg', label: 'JPEG' }, { value: 'webp', label: 'WebP' }, { value: 'bmp', label: 'BMP' }];

function WarningDetail({ issue }: { issue: Issue }) {
  const w = useWorkspace();
  const named = issue.assetIds.map(id => w.byId.get(id)).filter(a => !!a);
  return <Popover.Root>
    <Popover.Trigger className="link">查看</Popover.Trigger>
    <Popover.Portal><Popover.Positioner className="positioner" side="left" align="start" sideOffset={16} collisionPadding={12}><Popover.Popup className="popover warning-popover">
      <Popover.Title className="popover-title">{issue.message}</Popover.Title>
      <small className="popover-hint">提示不阻塞导出，但需要勾选「已了解」才能开始。</small>
      {named.slice(0, 100).map(a => <div key={a.id} className="section-line"><span className="truncate">{a.filename}</span><button type="button" className="link" onClick={() => { w.setTab('edit'); w.setReturnToExport(true); w.choose(a.id); }}>定位</button></div>)}
      {named.length > 100 && <small className="popover-hint">还有 {count(named.length - 100)} 张</small>}
    </Popover.Popup></Popover.Positioner></Popover.Portal>
  </Popover.Root>;
}

/** One click for a whole warning: hundreds of images are not confirmed or marked one by one (2026-11-13). */
function IssueFix({ issue }: { issue: Issue }) {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const undo = { label: '撤销', run: () => act(() => mutate('undo')) };
  if (issue.action === 'confirm') return <Button variant="soft" onClick={() => act(async () => {
    const { confirmed, skipped } = await mutate<{ confirmed: string[]; skipped: unknown[] }>('confirm_batch', { assetIds: issue.assetIds });
    w.toast({ text: skipped.length ? `已确认 ${count(confirmed.length)} 张，跳过 ${count(skipped.length)} 张` : `已确认 ${count(confirmed.length)} 张`, action: undo });
  })}>全部标为已确认</Button>;
  if (issue.action === 'no_caption') return <Button variant="soft" onClick={() => act(async () => {
    await mutate('batch', { operation: 'no_caption', assetIds: issue.assetIds });
    w.toast({ text: `已把 ${count(issue.assetIds.length)} 张设为无需字幕`, action: undo });
  })}>设为无需字幕</Button>;
  // Images left out of the export: show exactly those, with a way back to export.
  if (issue.action === 'resolve') return <Button variant="soft" onClick={() => w.resolve(issue.assetIds)}>去处理</Button>;
  return null;
}

function CheckList() {
  const w = useWorkspace();
  const [slow, setSlow] = useState(false);
  useEffect(() => { if (!w.checking) { setSlow(false); return; } const timer = setTimeout(() => setSlow(true), 300); return () => clearTimeout(timer); }, [w.checking]);
  const check = w.check;
  if (!w.output) return <p className="check-row muted"><Folder />先选择保存位置，选好后自动检查</p>;
  if (w.checking && slow || (!check && w.checking)) return <div className="check-loading" role="status"><p className="check-row"><LoaderCircle className="spin" />正在检查…</p><span className="skeleton-bar" /><span className="skeleton-bar short" /></div>;
  if (!check) return <p className="check-row muted">检查没有完成，请点右上角重新检查</p>;
  const errorText = check.errors.map(e => e.message).join('\n');
  // Images left out for a font problem are warnings now; the font line must not claim otherwise.
  const allText = [...check.errors, ...check.warnings].map(e => e.message).join('\n');
  const reviewed = !check.warnings.some(issue => issue.action === 'confirm' || issue.action === 'no_caption' || /空字幕/.test(issue.message));
  const passes = [
    reviewed && `${count(check.count)} 张图片的字幕均已确认`,
    !/字体|字形/.test(allText) && '字体可用，字形完整',
    !/文件夹|输出|写入/.test(errorText) && '输出文件夹可写',
  ].filter((x): x is string => !!x);
  return <div className="check-list">
    {check.errors.map((issue, i) => <div className="check-row" key={`e${i}`}><CircleAlert className="tone-danger" /><span>{issue.message}</span>{issue.assetIds.length > 0 && <Button variant="soft" onClick={() => w.resolve(issue.assetIds)}>去处理</Button>}</div>)}
    {check.warnings.map((issue, i) => <div className="check-row" key={`w${i}`}><TriangleAlert className="tone-warn" /><span>{issue.message}</span>{issue.assetIds.length > 0 && <WarningDetail issue={issue} />}{issue.action && <div className="check-fix"><IssueFix issue={issue} /></div>}</div>)}
    {passes.map(text => <div className="check-row" key={text}><CheckCircle2 className="tone-success" /><span className="muted">{text}</span></div>)}
    {!check.errors.length && check.warnings.length > 0 && <label className="check-row acknowledge"><Checkbox label="已了解上述提示" checked={w.acknowledge} onChange={w.setAcknowledge} /><span>已了解上述提示，继续导出</span></label>}
  </div>;
}

function Settings() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const o = w.options;
  const set = <K extends keyof typeof o>(key: K) => (value: (typeof o)[K]) => w.setOptions(previous => ({ ...previous, [key]: value }));
  const assets = w.assets;
  const scope = o.collection === 'selected' ? assets.filter(a => w.selection.includes(a.id)) : assets;
  const sample = scope[0];
  const extensionOf = (filename?: string) => o.format === 'original' ? filename?.split('.').pop() ?? 'jpg' : o.format;
  const extension = extensionOf(sample?.filename), lastExtension = extensionOf(scope.at(-1)?.filename);
  const number = (n: number) => String(n).padStart(o.digits, '0');
  const noCaption = assets.filter(a => a.status === 'no_caption').length;
  const last = w.check?.count ?? scope.length;
  return <>
    <Section title="导出前检查" actions={<IconButton label="重新检查" disabled={!w.output || w.checking} onClick={w.runCheck}><RefreshCw /></IconButton>}><CheckList /></Section>
    <Section title="保存位置">
      <div className="field folder-field"><Folder /><span className={`field-value ${w.output ? '' : 'placeholder'}`} title={w.output?.label}>{w.output?.label ?? '还没有选择'}</span>
        <button type="button" className="link" onClick={() => act(async () => { const r = await mutate<{ token: string; label: string; cancelled?: boolean }>('choose_output'); if (!r.cancelled) w.setOutput(r); })}>{w.output ? '更换' : '选择…'}</button></div>
      {!state?.desktop && <small className="section-hint">浏览器预览不能选择文件夹，请在桌面版中导出</small>}
    </Section>
    <Section title="格式">
      <div className="field-grid">
        <Select label="图片格式" value={o.format} options={formats} onChange={set('format')} />
        {(o.format === 'jpg' || o.format === 'webp') && <NumberField label="质量" prefix="质量" value={o.quality} min={1} max={100} unit="%" onCommit={set('quality')} />}
      </div>
      {o.format === 'jpg' && <small className="section-hint">透明区域将填充为白色</small>}
    </Section>
    <Section title="命名">
      <Select label="命名方式" value={o.naming} options={[{ value: 'original', label: '保持原文件名' }, { value: 'sequence', label: '顺序命名' }]}
        onChange={naming => w.setOptions(previous => ({ ...previous, naming, ...(naming === 'original' ? { prefix: '', suffix: '' } : {}) }))} />
      {o.naming === 'sequence' && <div className="field-grid three">
        <TextField label="文件名前缀" prefix="前缀" value={o.prefix} onChange={set('prefix')} />
        <NumberField label="起始序号" prefix="起始" value={o.start} min={0} max={999999} onCommit={set('start')} />
        <NumberField label="序号位数" prefix="位数" value={o.digits} min={1} max={8} onCommit={set('digits')} />
      </div>}
      <small className="section-hint example">示例 <span className="numeric">{o.naming === 'sequence' ? `${o.prefix}${number(o.start)}${o.suffix}.${extension}${last > 1 ? ` … ${o.prefix}${number(o.start + last - 1)}${o.suffix}.${lastExtension}` : ''}` : `${sample?.filename.replace(/\.[^.]+$/, '') ?? '原文件名'}.${extension}`}</span></small>
      <small className="section-hint">顺序按左栏的排序方式，与列表一致</small>
    </Section>
    <Section title="范围">
      <Segmented label="导出范围" value={o.collection} onChange={set('collection')}
        options={[{ value: 'all', label: `全部图片 ${count(assets.length)}` }, { value: 'selected', label: `已选 ${count(w.selection.length)}`, disabled: !w.selection.length }]} />
      <SwitchRow label="保留图片元数据" checked={o.metadata} onChange={set('metadata')} />
      {noCaption > 0 && <SwitchRow label={`包括无需字幕的图片（${count(noCaption)} 张）`} checked={o.includeNoCaption} onChange={set('includeNoCaption')} />}
      <small className="section-hint">保持原始尺寸 · 同名文件自动编号，不覆盖</small>
    </Section>
  </>;
}

function Progress({ value, max, done = false }: { value: number; max: number; done?: boolean }) {
  // Linear between updates, never backwards (导出进度).
  return <div className={`progress ${done ? 'done' : ''}`} role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}><span style={{ '--progress': max ? value / max : 0 } as CSSProperties} /></div>;
}

function JobView() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const job = state!.job!;
  const running = job.state === 'running' || job.state === 'stopping';
  const done = job.items.filter(i => i.status === 'success').length;
  const failed = job.items.filter(i => i.status === 'failed');
  const unfinished = job.items.length - done;
  const current = job.items.find(i => i.status === 'running');
  const back = () => { w.setJobVisible(false); w.setTab('edit'); };
  return <>
    {running ? <Section title={job.state === 'stopping' ? '正在安全停止' : '正在导出'}>
      <p className="job-count numeric"><strong>{count(done + failed.length)}</strong> / {count(job.items.length)} 张</p>
      <Progress value={done + failed.length} max={job.items.length} />
      <small className="section-hint truncate">{job.state === 'stopping' ? '当前文件写完后停止，不再领取新图片' : current ? `正在写入 ${current.file}` : '正在准备…'}</small>
      <small className="section-hint">不显示预计剩余时间；进度来自真实完成数</small>
    </Section> : <Section title={job.state === 'complete' ? '导出完成' : job.state === 'stopped' ? '导出已停止' : '部分图片没有完成'}>
      <p className="job-result">{job.state === 'complete' ? <CheckCircle2 className="tone-success draw" /> : <CircleAlert className={job.state === 'stopped' ? 'tone-muted' : 'tone-danger'} />}
        <strong>{failed.length || unfinished ? `已导出 ${count(done)} 张，${failed.length ? `${count(failed.length)} 张失败` : `${count(unfinished)} 张未处理`}` : `全部 ${count(done)} 张已导出`}</strong></p>
      <small className="section-hint truncate" title={job.outputDir}>{job.outputDir}</small>
      {done > 0 && <div className="output-thumbs">{job.items.filter(i => i.status === 'success').slice(0, 4).map(i => <OutputPreview key={i.index} jobId={job.id} index={i.index} />)}</div>}
      {unfinished > 0 && <Button className="full-width" onClick={() => act(() => mutate('retry_export', { jobId: job.id }))}>{failed.length ? `重试失败的 ${count(failed.length)} 张` : `继续处理 ${count(unfinished)} 张`}</Button>}
      <Button variant="ghost" className="full-width" onClick={back}>回到编辑</Button>
    </Section>}
    {failed.length > 0 && <Section title={`失败 ${count(failed.length)}`}>
      {failed.slice(0, 50).map(item => <div key={item.index} className="failure-row"><CircleAlert className="tone-danger" /><div><strong>{item.file}</strong><small>{item.error}</small></div></div>)}
    </Section>}
    {job.error && <p className="section-hint tone-danger">{job.error}</p>}
    {!running && <Section title="任务记录"><div className="section-line"><span>导出记录与清单</span><button type="button" className="link" onClick={() => act(() => mutate('export_log'))}>保存…</button></div></Section>}
  </>;
}

export function ExportPanel() {
  const { state } = useApp();
  const w = useWorkspace();
  const job = state?.job;
  const running = job?.state === 'running' || job?.state === 'stopping';
  return job && (running || w.jobVisible) ? <JobView /> : <Settings />;
}

/** The single blue button: its words always say the next step (导出任务). */
export function useExportAction() {
  const { state, act, mutate, busy } = useApp();
  const w = useWorkspace();
  const job = state?.job;
  const running = job?.state === 'running' || job?.state === 'stopping';
  if (running) return { label: '停止…', variant: 'secondary' as const, disabled: job!.state === 'stopping', run: () => w.openDialog('stop') };
  if (job && w.jobVisible) return { label: '打开文件夹', variant: 'primary' as const, disabled: false, folder: true, run: () => act(() => mutate('open_output', { jobId: job.id })) };
  const check = w.check;
  const ready = !!check && !check.errors.length && (!check.warnings.length || w.acknowledge) && check.revision === w.project?.revision && !w.checking;
  return { label: check && !check.errors.length ? `开始导出 ${count(check.count)} 张` : '开始导出', variant: 'primary' as const, disabled: !ready || busy > 0,
    run: () => act(async () => { await mutate('start_export', { preflightId: check!.id, acknowledge: w.acknowledge }); w.setJobVisible(true); }) };
}

