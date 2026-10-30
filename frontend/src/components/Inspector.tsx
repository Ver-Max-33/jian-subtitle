import { useEffect, useRef, useState } from 'react';
import { Check, FolderOpen, Info, MoreHorizontal, Plus, Sparkles, Type, X } from 'lucide-react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import type { Asset, Caption } from '../types';
import { count, formatName, shortTime, sourceName, speakerHint, statusNames, two } from '../format';
import { Button, IconButton, Menu, Section, Select, SwitchRow, TextField, Tip, type MenuEntry } from './ui';
import { SpeakerPicker, wearsPreset } from './Pickers';
import { percentOfReference } from '../styleModel';
import { StyleSections, useBatchTarget, useSingleTarget } from './StyleSections';
import { statusIcon } from './LeftPanel';
import { focusRequest, RenderedPreview } from './Canvas';

function StatusRow({ asset }: { asset: Asset }) {
  const { busy } = useApp();
  const w = useWorkspace();
  const confirmable = asset.captions.length > 0 && asset.status !== 'unreadable';
  return <div className="status-row">
    <span className={`status-label ${asset.status}`}><span className="filter-icon">{statusIcon(asset.status)}</span>{statusNames[asset.status]}</span>
    {confirmable && <Tip label="确认并下一张" shortcut="Enter"><Button variant="soft" disabled={busy > 0} onClick={() => w.confirmAndNext(asset)}><Check />确认并下一张</Button></Tip>}
  </div>;
}

function CaptionText({ asset, caption }: { asset: Asset; caption: Caption }) {
  const { editText, compose, draft } = useApp();
  const w = useWorkspace();
  const [text, setText] = useState(caption.text);
  const composing = useRef(false);
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (!draft.current || draft.current.captionId !== caption.id) setText(caption.text); }, [caption.id, caption.text]);
  useEffect(() => { if (focusRequest.pending) { focusRequest.pending = false; field.current?.focus(); } }, [caption.id]);
  // Typing on the picture writes the same draft (spec 4.3).
  useEffect(() => { if (!composing.current && w.liveText?.captionId === caption.id && w.liveText.text !== text) setText(w.liveText.text); }, [w.liveText]);
  const lines = Math.min(6, Math.max(2, text.split('\n').length));
  return <div className="caption-text">
    <textarea ref={field} data-caption-text rows={lines} aria-label="字幕文字" value={text} maxLength={10000} placeholder="填写这条字幕…"
      onCompositionStart={() => { composing.current = true; compose(true); }}
      onCompositionEnd={e => { composing.current = false; compose(false); w.setLiveText({ captionId: caption.id, text: e.currentTarget.value }); }}
      onChange={e => { setText(e.target.value); editText(asset.id, caption.id, e.target.value); if (!composing.current) w.setLiveText({ captionId: caption.id, text: e.target.value }); }}
      onKeyDown={e => { if (e.key === 'Escape') e.currentTarget.blur(); }} />
    <div className="caption-text-foot"><span>{sourceName(caption.source)}</span><span className="numeric">{Array.from(text).length} 字</span></div>
  </div>;
}

function captionMenu(asset: Asset, caption: Caption, w: ReturnType<typeof useWorkspace>, act: (fn: () => Promise<unknown>) => void, mutate: (action: string, payload?: Record<string, unknown>) => Promise<unknown>): MenuEntry[] {
  const scope = { assetId: asset.id, captionId: caption.id };
  const at = asset.captions.indexOf(caption);
  return [
    { label: '上移一条', disabled: at <= 0, action: () => act(() => mutate('caption_move', { ...scope, delta: -1 })) },
    { label: '下移一条', disabled: at >= asset.captions.length - 1, action: () => act(() => mutate('caption_move', { ...scope, delta: 1 })) },
    { separator: true },
    { label: '恢复默认位置…', action: () => w.openDialog('reset', { scope: 'position' }) },
    { label: '恢复默认样式…', action: () => w.openDialog('reset', { scope: 'style' }) },
    { separator: true },
    { label: '设为无需字幕…', action: () => w.openDialog('batch', { operation: 'no_caption', assetIds: [asset.id] }) },
    { label: '删除这条字幕…', danger: true, action: () => w.openDialog('delete-caption') },
  ];
}

export function CaptionBlock({ asset, caption }: { asset: Asset; caption: Caption }) {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const add = () => act(async () => { const r = await mutate<{ captionId: string }>('caption_add', { assetId: asset.id }); focusRequest.pending = true; w.chooseCaption(r.captionId); });
  return <Section title={<>字幕<span className="ordinal-chips" role="group" aria-label="选择字幕">{asset.captions.map((c, i) => <button type="button" key={c.id} aria-pressed={c.id === caption.id} className={`${c.id === caption.id ? 'selected' : ''} ${w.hovered === c.id ? 'hovered' : ''}`} onClick={() => w.chooseCaption(c.id)} onPointerEnter={() => w.setHovered(c.id)} onPointerLeave={() => w.setHovered(null)}>{i + 1}</button>)}</span></>}
    actions={<><IconButton label="添加字幕" disabled={asset.captions.length >= 20} onClick={add}><Plus /></IconButton>
      <Menu label="字幕操作" tip align="end" items={captionMenu(asset, caption, w, act, mutate)}><MoreHorizontal /></Menu></>}>
    <CaptionText asset={asset} caption={caption} />
    <div className="labelled-row"><span>说话人</span><SpeakerPicker value={caption.speaker} speakers={state!.project!.speakers} onImport={() => act(() => mutate('import_speakers'))}
      onChange={speaker => act(() => mutate('caption_speaker', { assetId: asset.id, captionId: caption.id, speaker }))} /></div>
    {caption.speaker && <div className="section-line"><small className="section-hint">{speakerHint(state!.project!.showSpeaker, caption.speaker)}</small>
      <button type="button" className="link" onClick={() => { w.setFocused(false); requestAnimationFrame(() => document.querySelector<HTMLElement>('[role="switch"][aria-label="在字幕前显示说话人"]')?.focus()); }}>更改</button></div>}
    <StatusRow asset={asset} />
  </Section>;
}

function NoCaptions({ asset }: { asset: Asset }) {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  const add = () => act(async () => { const r = await mutate<{ captionId: string }>('caption_add', { assetId: asset.id }); focusRequest.pending = true; w.chooseCaption(r.captionId); });
  const stem = asset.filename.replace(/\.[^.]+$/, '');
  const none = asset.status === 'no_caption';
  return <Section title="字幕" actions={<IconButton label="添加字幕" onClick={add}><Plus /></IconButton>}>
    <div className="empty-block">
      <strong>{none ? '已设为无需字幕' : '这张图片还没有字幕'}</strong>
      <small>{none ? '导出时按原图复制，可在导出设置里关闭' : asset.kind === 'timestamp_or_sequence' ? `文件名「${stem}」是时间、序号或相机编号，不会当作字幕` : '删除最后一条字幕后，不会从文件名自动恢复'}</small>
      {none ? <Button className="full-width" onClick={() => act(() => mutate('batch', { operation: 'clear', assetIds: [asset.id] }))}>改为需要字幕</Button>
        : <div className="button-row"><Button onClick={add}><Plus />添加字幕</Button><Button variant="ghost" onClick={() => act(() => mutate('batch', { operation: 'no_caption', assetIds: [asset.id] }))}>设为无需字幕</Button></div>}
    </div>
    <StatusRow asset={asset} />
  </Section>;
}

function imageMenu(asset: Asset, w: ReturnType<typeof useWorkspace>, act: (fn: () => Promise<unknown>) => void, mutate: (action: string, payload?: Record<string, unknown>) => Promise<unknown>): MenuEntry[] {
  return [
    { label: '查看图片信息', action: () => window.dispatchEvent(new CustomEvent('jian:image-info')) },
    { label: '从文件名重新提取…', action: () => w.openDialog('extract-one', { assetId: asset.id }) },
    { label: '设为无需字幕', disabled: asset.status === 'no_caption', action: () => act(() => mutate('batch', { operation: 'no_caption', assetIds: [asset.id] })) },
    { separator: true },
    { label: '移除图片…', danger: true, action: () => w.openDialog('batch', { operation: 'remove', assetIds: [asset.id] }) },
  ];
}

function ImageInspector({ asset }: { asset: Asset }) {
  const { act, mutate } = useApp();
  const w = useWorkspace();
  if (!asset.captions.length) return <NoCaptions asset={asset} />;
  const manual = asset.captions.filter(c => c.manual).length;
  return <>
    <Section title={`图片 ${two(w.assets.indexOf(asset) + 1)}`} actions={<Menu label="图片操作" tip align="end" items={imageMenu(asset, w, act, mutate)}><MoreHorizontal /></Menu>}>
      <StatusRow asset={asset} />
      <small className="section-hint numeric">拍摄于 {shortTime(asset.captureTime)}{asset.width ? ` · ${asset.width} × ${asset.height}` : ''} · {formatName(asset.filename)}</small>
    </Section>
    <Section title="字幕" actions={<IconButton label="添加字幕" disabled={asset.captions.length >= 20} onClick={() => act(async () => { const r = await mutate<{ captionId: string }>('caption_add', { assetId: asset.id }); focusRequest.pending = true; w.chooseCaption(r.captionId); })}><Plus /></IconButton>}>
      <div className="caption-rows">{asset.captions.map(c => <button type="button" key={c.id} className={`caption-row ${w.hovered === c.id ? 'hovered' : ''}`} onClick={() => w.chooseCaption(c.id)} onPointerEnter={() => w.setHovered(c.id)} onPointerLeave={() => w.setHovered(null)}>
        <Type /><span className="truncate">{c.text || '（空字幕）'}</span><small>{c.speaker}</small>
      </button>)}</div>
    </Section>
    <Section title="位置">
      <small className="section-hint">{manual === 0 ? `${asset.captions.length} 条字幕都使用智能避让` : manual === asset.captions.length ? `${manual} 条字幕都是手动位置` : `${manual} 条手动，${asset.captions.length - manual} 条智能避让`}</small>
      <Button className="full-width" onClick={w.rearrange}><Sparkles />重新排列本图字幕</Button>
    </Section>
    <Section title="文字样式"><small className="section-hint">选中一条字幕后编辑样式；同时改多张，请在左栏勾选图片</small></Section>
  </>;
}

function SingleCaption({ asset, caption, collapsible }: { asset: Asset; caption: Caption; collapsible?: boolean }) {
  const w = useWorkspace();
  const target = useSingleTarget(asset, caption);
  return <><CaptionBlock asset={asset} caption={caption} /><StyleSections target={target} collapsible={collapsible} onSavePreset={() => w.openDialog('preset-save')} /></>;
}

function ListInspector({ asset }: { asset: Asset }) {
  const w = useWorkspace();
  const caption = w.caption ?? asset.captions[0];
  return <>
    <Section title="预览" actions={<span className="section-meta numeric">{two(w.assets.indexOf(asset) + 1)} / {two(w.assets.length)}</span>}><RenderedPreview asset={asset} /></Section>
    {caption ? <SingleCaption asset={asset} caption={caption} collapsible /> : <NoCaptions asset={asset} />}
  </>;
}

function BatchInspector() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  const [scope, setScope] = useState<number | 'all'>(0);
  const chosen = w.assets.filter(a => w.selection.includes(a.id));
  const visible = new Set(w.visible.map(a => a.id));
  const outside = chosen.filter(a => !visible.has(a.id)).length;
  const most = Math.max(1, ...chosen.map(a => a.captions.length));
  useEffect(() => { if (scope !== 'all' && scope >= most) setScope(0); }, [most]);
  const target = useBatchTarget(scope);
  const captions = chosen.flatMap(a => scope === 'all' ? a.captions : a.captions.slice(scope, scope + 1));
  const speaker = captions.length && captions.every(c => c.speaker === captions[0].speaker) ? captions[0].speaker : undefined;
  const n = count(chosen.length);
  return <>
    <Section title={`已选 ${n} 张`} actions={<><Menu label="批量操作" tip align="end" items={[
      { label: `标为已确认（${n} 张）`, action: () => act(async () => {
        const { confirmed, skipped } = await mutate<{ confirmed: string[]; skipped: { id: string; reason: string }[] }>('confirm_batch', { assetIds: w.selection });
        if (!skipped.length) { w.toast({ text: `已确认 ${count(confirmed.length)} 张`, action: { label: '撤销', run: () => act(() => mutate('undo')) } }); return; }
        // The reason most of them share.
        const tally = new Map<string, number>();
        for (const s of skipped) tally.set(s.reason, (tally.get(s.reason) ?? 0) + 1);
        const reason = [...tally].sort((a, b) => b[1] - a[1])[0][0];
        w.toast({ text: `已确认 ${count(confirmed.length)} 张，跳过 ${count(skipped.length)} 张（${reason}）`, tone: 'warn', sticky: true, action: { label: '查看', run: () => w.showSkipped(skipped.map(s => s.id)) } });
      }) },
      { label: '恢复统一样式', action: () => act(async () => {
        const result = await mutate<{ restored: number }>('style_restore', { scope: 'selection', assetIds: w.selection, captions: scope });
        w.toast({ text: `已恢复 ${count(result.restored)} 条字幕` });
      }) },
      { separator: true },
      { label: '设置说话人…', action: () => w.openDialog('batch-speaker') },
      { label: '从文件名重新提取…', action: () => w.openDialog('batch', { operation: 'extract' }) },
      { label: '设为无需字幕…', action: () => w.openDialog('batch', { operation: 'no_caption' }) },
      { label: '清空字幕…', action: () => w.openDialog('batch', { operation: 'clear' }) },
      { separator: true },
      { label: `移除 ${n} 张图片…`, danger: true, action: () => w.openDialog('batch', { operation: 'remove' }) },
    ]}><MoreHorizontal /></Menu><IconButton label="取消选择" onClick={() => w.setSelection([])}><X /></IconButton></>}>
      <small className="section-hint">修改会应用到这 {n} 张图片，可一次撤销</small>
      {outside > 0 && <div className="section-line"><small className="section-hint">其中 {outside} 张在当前筛选外</small><button type="button" className="link" onClick={() => w.setSelection(list => list.filter(id => visible.has(id)))}>只保留可见的</button></div>}
    </Section>
    <Section title="字幕">
      <div className="labelled-row"><span>范围</span><Select label="字幕范围" value={String(scope)} onChange={v => setScope(v === 'all' ? 'all' : Number(v))}
        options={[...Array.from({ length: most }, (_, i) => ({ value: String(i), label: `每张第 ${i + 1} 条字幕` })), { value: 'all', label: '所有字幕' }]} /></div>
      <div className="labelled-row"><span>说话人</span><SpeakerPicker value={speaker ?? ''} mixed={speaker === undefined} speakers={state!.project!.speakers} onImport={() => act(() => mutate('import_speakers'))}
        onChange={value => act(() => mutate('batch_set', { assetIds: w.selection, captions: scope, speaker: value }))} /></div>
      <Button className="full-width" onClick={() => w.openDialog('replace')}>替换文字…</Button>
    </Section>
    <StyleSections target={target} />
  </>;
}

function ProjectInspector() {
  const { state, fonts, act, mutate } = useApp();
  const w = useWorkspace();
  const project = w.project!;
  // 统一样式 (spec 4.1, 4.2; I8, I8b): what every caption follows, how many keep their own look, fixed pixels in old projects.
  const unified = project.style, reference = project.referenceEdge;
  const look = state!.builtinPresets.find(card => wearsPreset(card, unified, (reference ?? 1080) / 1080))?.name ?? '自定义';
  const size = reference ? `${percentOfReference(unified.font_size, reference).toFixed(1)}%` : `${Math.round(unified.font_size)} px`;
  const exceptions = project.assets.reduce((n, a) => n + a.captions.filter(c => c.overrides.length).length, 0);
  const toProportional = () => act(async () => {
    await mutate('style_to_proportional');
    w.toast({ text: '已改为按画面比例', action: { label: '撤销', run: () => act(() => mutate('undo')) } });
  });
  const [name, setName] = useState(project.name);
  const [adding, setAdding] = useState(false);
  const [speaker, setSpeaker] = useState('');
  useEffect(() => setName(project.name), [project.name]);
  const rename = () => { const next = name.trim(); if (next && next !== project.name) act(() => mutate('rename', { name: next })); else setName(project.name); };
  const addSpeaker = () => { const next = speaker.trim(); setAdding(false); setSpeaker(''); if (next) act(() => mutate('speakers', { operation: 'add', name: next })); };
  return <>
    <Section title="项目">
      <div className="labelled-row" onBlur={rename} onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLElement).blur(); if (e.key === 'Escape') setName(project.name); }}><span>名称</span><TextField label="项目名称" value={name} onChange={setName} /></div>
      <div className="labelled-row"><span>新项目样式</span><Select label="新项目样式" value={state!.defaultPreset ?? '经典'} onChange={v => act(() => mutate('preset', { operation: 'default', name: v }))}
        options={[{ value: '经典', label: '经典', hint: '内置' }, ...state!.presets.map(p => ({ value: p, label: p }))]} /></div>
      <small className="section-hint">新建项目时使用这个样式；不改已有项目和图片</small>
    </Section>
    <Section title="统一样式">
      <div className="unified-summary">{look} · {fonts.find(f => f.id === unified.font_id)?.label ?? '原字体'} · 字号 {size}</div>
      <small className="section-hint">{project.assets.length ? '选中任意字幕，在「全部图片」下修改' : '新导入的图片、新加的字幕都用它；选中任意字幕，在「全部图片」下修改'}</small>
      {exceptions > 0 && <div className="section-line"><small className="section-hint"><Info />{exceptions} 条字幕单独改过样式</small>
        <button type="button" className="link" onClick={() => act(() => mutate('style_restore', { scope: 'project' }))}>全部恢复</button></div>}
      {reference === null && <div className="legacy-size"><strong>字号是固定像素</strong>
        <small>不同尺寸的图片上，字幕看起来大小不一。改为按画面比例后，最常见尺寸的图片外观不变。</small>
        <Button className="full-width" onClick={toProportional}>改为按画面比例</Button></div>}
    </Section>
    <Section title="说话人" actions={<IconButton label="添加说话人" onClick={() => setAdding(true)}><Plus /></IconButton>}>
      {adding && <input className="field inline-input" autoFocus aria-label="说话人姓名" placeholder="输入姓名，回车添加" maxLength={80} value={speaker} onChange={e => setSpeaker(e.target.value)}
        onBlur={addSpeaker} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) addSpeaker(); if (e.key === 'Escape') { e.stopPropagation(); setAdding(false); setSpeaker(''); } }} />}
      {project.speakers.length ? <div className="speaker-rows">{project.speakers.map(s => <div key={s} className="speaker-row"><span>{s}</span><IconButton label={`从名单移除 ${s}`} onClick={() => act(() => mutate('speakers', { operation: 'remove', name: s }))}><X /></IconButton></div>)}</div>
        : !adding && <small className="section-hint">还没有说话人</small>}
      <Button className="full-width" onClick={() => act(() => mutate('import_speakers'))}><FolderOpen />从 TXT 导入名单…</Button>
      <SwitchRow label="在字幕前显示说话人" checked={project.showSpeaker} onChange={value => act(() => mutate('project_settings', { showSpeaker: value }))} />
      <small className="section-hint">{speakerHint(project.showSpeaker, project.speakers[0])}</small>
    </Section>
  </>;
}

export function Inspector() {
  const w = useWorkspace();
  if (!w.project?.assets.length) return <ProjectInspector />;
  if (w.batch) return <BatchInspector />;
  if (!w.focused || !w.asset) return <ProjectInspector />;
  if (w.view === 'list') return <ListInspector asset={w.asset} />;
  if (!w.caption) return <ImageInspector asset={w.asset} />;
  return <SingleCaption asset={w.asset} caption={w.caption} />;
}
