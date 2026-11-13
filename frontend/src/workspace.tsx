import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useApp } from './state';
import type { Asset, Caption, Preflight, Style } from './types';
import type { PositionDraft, PositionDrafts } from './components/CaptionCanvas';
import type { StyleDrafts } from './components/useEditorPreview';
import { defaultExportOptions, filterNames, inView, isUnresolved, type ExportOptions, type Filter } from './format';
import { overriddenRows, POSITION_KEYS, rowOfKey, type Row, type Scope } from './styleModel';

export type Page = 'home' | 'workspace';
export type View = 'canvas' | 'list';
export type Tab = 'edit' | 'export';
export type Tool = 'select' | 'text';
export interface Toast { id: number; text: string; tone?: 'danger' | 'warn'; action?: { label: string; run: () => void }; sticky?: boolean }
export type DialogState = { type: string; data: Record<string, unknown> } | null;
interface Drafts { assetId: string; styles: StyleDrafts; positions: PositionDrafts }

function useWorkspaceState() {
  const { state, act, mutate, command, flush } = useApp();
  const project = state?.project;
  const assets = project?.assets ?? [];
  const byId = useMemo(() => new Map(assets.map(a => [a.id, a])), [assets]);
  const [page, setPage] = useState<Page>('home');
  const [view, setView] = useState<View>('canvas');
  const [tab, setTab] = useState<Tab>('edit');
  const [tool, setTool] = useState<Tool>('select');
  const [activeId, setActiveId] = useState('');
  // null: the image itself is selected (E1); otherwise one caption is.
  const [captionId, setCaptionId] = useState<string | null>(null);
  // Nothing selected: the inspector shows project properties (I8).
  const [focused, setFocused] = useState(true);
  const [selection, setSelection] = useState<string[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [issueIds, setIssueIds] = useState<string[]>([]);
  // What the 'issue' row is called: 「导出问题」 from export, 「跳过的图片」 after 标为已确认.
  const [issueLabel, setIssueLabel] = useState(filterNames.issue);
  const [zoom, setZoom] = useState('fit');
  const [scale, setScale] = useState(0);
  const [showRegions, setShowRegions] = useState(false);
  const [regions, setRegions] = useState<Record<string, number[][]>>({});
  const [rawView, setRawView] = useState(false);
  const [rotationSnap, setRotationSnap] = useState(true);
  const [safeGuide, setSafeGuide] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  // A caption placed with the T tool that is still empty: it goes away if left empty (E3).
  const [fresh, setFresh] = useState<string | null>(null);
  // List mode keeps the style blocks folded; one opens at a time (列表校对).
  const [openSection, setOpenSection] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [drafts, setDrafts] = useState<Drafts>({ assetId: '', styles: {}, positions: {} });
  // 「应用到」 (spec 4.1) stays as chosen across images and captions (2026-11-13; it used to jump back to 「全部图片」,
  // so a change meant for one caption hit every image). A new project starts at 「全部图片」.
  const [scope, setScope] = useState<Scope>('all');
  const [lastUnified, setLastUnified] = useState<Row | null>(null);
  // The caption being typed on the picture, and where it was double-clicked (spec 4.3).
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editAt, setEditAt] = useState<{ x: number; y: number }>();
  const ending = useRef<string | null>(null);
  const [liveText, setLiveText] = useState<{ captionId: string; text: string }>();
  const [options, setOptions] = useState<ExportOptions>(defaultExportOptions);
  const [output, setOutput] = useState<{ token: string; label: string }>();
  const [check, setCheck] = useState<Preflight>();
  const [checking, setChecking] = useState(false);
  const [acknowledge, setAcknowledge] = useState(false);
  const [returnToExport, setReturnToExport] = useState(false);
  // The export tab shows the last job (progress, results) until the user goes back to settings.
  const [jobVisible, setJobVisible] = useState(false);
  const toastId = useRef(0);

  const asset = byId.get(activeId);
  const caption = captionId ? asset?.captions.find(c => c.id === captionId) : undefined;
  const issues = useMemo(() => new Set(issueIds), [issueIds]);
  const visible = useMemo(() => assets.filter(a => inView(a, filter, query, issues)), [assets, filter, query, issues]);
  const batch = selection.length > 0;

  const toast = useCallback((value: Omit<Toast, 'id'>) => {
    const id = ++toastId.current;
    // One message at a time above the toolbar; a newer one replaces the older (E6, I7).
    setToasts([{ ...value, id }]);
    return id;
  }, []);
  const dismiss = useCallback((id: number) => setToasts(list => list.filter(t => t.id !== id)), []);
  const openDialog = useCallback((type: string, data: Record<string, unknown> = {}) => setDialog({ type, data }), []);

  // Keep the current image and the ticks pointing at images that still exist.
  useEffect(() => {
    if (!assets.length) { setActiveId(''); return; }
    if (!byId.has(activeId)) { setActiveId(assets[0].id); setCaptionId(assets[0].captions[0]?.id ?? null); }
    setSelection(list => list.every(id => byId.has(id)) ? list : list.filter(id => byId.has(id)));
  }, [project?.id, project?.revision]);
  useEffect(() => {
    setSelection([]); setFilter('all'); setIssueIds([]); setQuery(''); setOutput(undefined); setOptions(defaultExportOptions); setCheck(undefined);
    setToasts([]); setRegions({}); setShowRegions(false); setTab('edit'); setReturnToExport(false); setFocused(true);
  }, [project?.id]);
  useEffect(() => { if (captionId && asset && !asset.captions.some(c => c.id === captionId)) setCaptionId(asset.captions[0]?.id ?? null); }, [asset?.captions.length, captionId]);
  useEffect(() => { setRawView(false); setTool('select'); setLiveText(undefined); }, [activeId]);
  useEffect(() => { setLastUnified(null); }, [activeId, captionId]);
  useEffect(() => { setScope('all'); }, [project?.id]);
  useEffect(() => { if (editingId && !asset?.captions.some(c => c.id === editingId)) setEditingId(null); }, [asset, editingId]);

  const choose = useCallback((id: string, { caption: wanted }: { caption?: string | null } = {}) => act(async () => {
    await flush();
    const target = byId.get(id);
    setActiveId(id); setFocused(true);
    setCaptionId(wanted !== undefined ? wanted : target?.captions[0]?.id ?? null);
  }), [act, flush, byId]);
  const chooseCaption = useCallback((id: string | null) => act(async () => { await flush(); setCaptionId(id); setFocused(true); }), [act, flush]);
  const step = useCallback((delta: number) => {
    const list = visible.length ? visible : assets;
    const index = list.findIndex(a => a.id === activeId);
    // From an image the list no longer shows: the first one forward, the last one back.
    const next = index < 0 ? list.at(delta > 0 ? 0 : -1) : list[Math.min(list.length - 1, Math.max(0, index + delta))];
    if (next && next.id !== activeId) choose(next.id);
  }, [visible, assets, activeId, choose]);
  // A filter or search that hides the current image opens the first one it shows (it used to stay on the hidden one:
  // 「0 / 11」, no row highlighted). An edit that moves the image out of the filter keeps it, mid-edit.
  useEffect(() => { if (visible.length && !visible.some(a => a.id === activeId)) choose(visible[0].id); }, [filter, query, issueIds]);

  /** 「确认并下一张」: confirm every caption here, then the next unresolved image in the order on screen. */
  const confirmAndNext = useCallback((target?: Asset) => act(async () => {
    const current = target ?? asset;
    if (!current) return;
    const order = visible.map(a => a.id);
    const at = Math.max(0, order.indexOf(current.id));
    await mutate('confirm', { assetId: current.id });
    const following = [...order.slice(at + 1), ...order.slice(0, at)].map(id => byId.get(id)).find((a): a is Asset => !!a && a.id !== current.id && isUnresolved(a));
    if (!following) {
      toast({ text: filter === 'all' && !query ? '全部图片都已校对' : '当前筛选已校对完成', action: { label: '去导出', run: () => setTab('export') } });
      return;
    }
    choose(following.id);
    const position = assets.findIndex(a => a.id === following.id) + 1;
    toast({ text: `已确认，转到第 ${position} 张`, action: { label: '撤销', run: () => act(async () => { await mutate('undo'); choose(current.id); }) } });
  }), [act, asset, visible, byId, mutate, toast, filter, query, choose, assets]);

  const startEditing = useCallback((id: string, at?: { x: number; y: number }) => { setCaptionId(id); setFocused(true); setEditAt(at); setEditingId(id); }, []);
  /** Ends typing on the picture (Esc, a click elsewhere, Ctrl/⌘ + Enter). Blur after Esc must not end it twice. */
  const endEditing = useCallback(({ confirm = false }: { confirm?: boolean } = {}) => act(async () => {
    const id = editingId, target = asset;
    if (!id || ending.current === id) return;
    ending.current = id;
    try {
      setEditingId(null);
      await flush();
      const text = liveText?.captionId === id ? liveText.text : target?.captions.find(c => c.id === id)?.text ?? '';
      // A caption placed with the T tool and left empty goes away (spec 4.3, E3).
      if (fresh === id) { setFresh(null); if (!text.trim() && target) await mutate('caption_delete', { assetId: target.id, captionId: id }); }
      if (confirm && target) confirmAndNext(target);
    } finally { ending.current = null; }
  }), [act, editingId, asset, flush, liveText, fresh, mutate, confirmAndNext]);

  // Drafts preview on the real raster before one undoable commit; they belong to one image.
  const scoped = (previous: Drafts, assetId: string) => previous.assetId === assetId ? previous : { assetId, styles: {}, positions: {} };
  // 「全部图片」 previews on every caption of this image that follows the unified value, not only the one being edited.
  const followers = (key: string, id: string, target: Scope) => {
    const row = rowOfKey(key);
    if (target !== 'all' || !asset || !row || POSITION_KEYS.includes(key)) return [id];
    return asset.captions.filter(c => c.id === id || !overriddenRows(c.overrides).includes(row)).map(c => c.id);
  };
  const previewStyle = useCallback(<K extends keyof Style>(key: K, value: Style[K] | undefined, id: string, target: Scope = 'caption') => {
    if (!asset) return;
    const ids = followers(key, id, target);
    setDrafts(previous => {
      const base = scoped(previous, asset.id), styles = { ...base.styles };
      for (const each of ids) {
        const changed = { ...styles[each] };
        if (value === undefined) delete changed[key]; else changed[key] = value;
        styles[each] = changed;
      }
      return { ...base, styles };
    });
  }, [asset]);
  const previewPosition = useCallback((key: keyof PositionDraft, value: number | undefined, id: string) => {
    if (!asset) return;
    setDrafts(previous => {
      const base = scoped(previous, asset.id), changed = { ...base.positions[id] };
      if (value === undefined) delete changed[key]; else changed[key] = value;
      return { ...base, positions: { ...base.positions, [id]: changed } };
    });
  }, [asset?.id]);
  const settle = (assetId: string, id: string, field: 'styles' | 'positions', committed: object) => setDrafts(previous => {
    const values = committed as Record<string, unknown>;
    if (previous.assetId !== assetId) return previous;
    const remaining: Record<string, unknown> = { ...previous[field][id] };
    for (const key of Object.keys(values)) if (JSON.stringify(remaining[key]) === JSON.stringify(values[key])) delete remaining[key];
    return { ...previous, [field]: { ...previous[field], [id]: remaining } };
  });
  const applyStyle = useCallback((style: Partial<Style>, target: Caption | undefined = caption, scopeOf: Scope = 'caption') => act(async () => {
    if (!asset || !target) return;
    const assetId = asset.id, keys = Object.keys(style);
    // Position fields always stay with the caption (spec 4.1).
    const unified = scopeOf === 'all' && !keys.every(key => POSITION_KEYS.includes(key));
    const ids = unified ? followers(keys[0], target.id, 'all') : [target.id];
    setDrafts(previous => {
      const base = scoped(previous, assetId), styles = { ...base.styles };
      for (const id of ids) styles[id] = { ...styles[id], ...style };
      return { ...base, styles };
    });
    try { await mutate('caption_style', { assetId, captionId: target.id, style, scope: unified ? 'all' : 'caption' }); }
    finally { for (const id of ids) settle(assetId, id, 'styles', style); }
    if (unified) setLastUnified(rowOfKey(keys[0]) ?? null);
  }), [act, asset, caption, mutate]);
  const applyPosition = useCallback((values: PositionDraft & { maxWidth?: number }, target: Caption | undefined = caption) => act(async () => {
    if (!asset || !target) return;
    const assetId = asset.id;
    for (const [key, value] of Object.entries(values)) if (key !== 'maxWidth') previewPosition(key as keyof PositionDraft, value, target.id);
    try { await mutate('caption_position', { assetId, captionId: target.id, ...values }); }
    finally { settle(assetId, target.id, 'positions', values); if (values.maxWidth !== undefined) settle(assetId, target.id, 'styles', { max_width: values.maxWidth }); }
  }), [act, asset?.id, caption, mutate, previewPosition]);
  const styleDrafts = drafts.assetId === activeId ? drafts.styles : {};
  const positionDrafts = drafts.assetId === activeId ? drafts.positions : {};

  const loadRegions = useCallback((assetId: string) => act(async () => {
    if (regions[assetId]) return;
    const result = await mutate<{ regions: number[][] }>('detect_regions', { assetId });
    setRegions(previous => ({ ...previous, [assetId]: result.regions }));
  }), [act, mutate, regions]);
  const rearrange = useCallback(() => act(async () => {
    if (!asset) return;
    const target = caption ?? asset.captions[0];
    if (!target) return;
    const result = await mutate<{ regions: number[][]; count: number; warning: string | null }>('smart_layout', { assetId: asset.id, captionId: target.id });
    setRegions(previous => ({ ...previous, [asset.id]: result.regions }));
    if (result.warning) toast({ text: result.warning, tone: 'warn', sticky: true, action: result.warning.startsWith('空间不足') ? { label: '调小字号', run: () => document.querySelector<HTMLInputElement>('input[aria-label="字号"]')?.focus() } : undefined });
    else toast({ text: `已排列 ${result.count} 条字幕，其他手动字幕保持不变` });
  }), [act, asset, caption, mutate, toast]);

  // Preflight reruns 300 ms after any change while the export tab is open; a stale answer is dropped (X1, X2).
  const checkGeneration = useRef(0);
  const runCheck = useCallback(() => {
    const generation = ++checkGeneration.current;
    if (!project || !output) { setCheck(undefined); setChecking(false); return; }
    setChecking(true);
    const scope = options.collection === 'selected' ? { assetIds: selection } : {};
    command<Preflight>('preflight', { ...options, outputToken: output.token, ...scope }, { quiet: true })
      .then(result => { if (generation === checkGeneration.current) { setCheck(result); setAcknowledge(false); } })
      .catch(() => { if (generation === checkGeneration.current) setCheck(undefined); })
      .finally(() => { if (generation === checkGeneration.current) setChecking(false); });
  }, [project?.id, project?.revision, output, options, selection, command]);
  const exportRunning = state?.job?.state === 'running' || state?.job?.state === 'stopping';
  useEffect(() => {
    // While a finished job is on screen its own plan stays; checking again would rename against the new outputs.
    if (tab !== 'export' || exportRunning || jobVisible) return;
    setCheck(previous => previous && previous.revision === project?.revision ? previous : undefined);
    const timer = setTimeout(runCheck, 300);
    return () => clearTimeout(timer);
  }, [tab, runCheck, exportRunning, jobVisible]);

  /** 「去处理」: show exactly these images, keep a way back to export (X6). */
  const resolve = useCallback((assetIds: string[]) => act(async () => {
    await flush();
    // The list shows exactly these images (「导出问题」), to work through one by one; 回到导出 clears it.
    setIssueIds(assetIds); setIssueLabel(filterNames.issue); setFilter('issue'); setQuery(''); setSelection([]); setTab('edit'); setView('canvas'); setReturnToExport(true);
    if (assetIds[0]) choose(assetIds[0]);
  }), [act, flush, choose]);
  /** 「查看」 after 标为已确认: the skipped images through the same filter row, without a way back to export (spec 4.5). */
  const showSkipped = useCallback((assetIds: string[]) => {
    setIssueIds(assetIds); setIssueLabel('跳过的图片'); setFilter('issue'); setQuery(''); setSelection([]);
    if (assetIds[0]) choose(assetIds[0]);
  }, [choose]);
  const backToExport = useCallback(() => { setReturnToExport(false); setIssueIds([]); setFilter(current => current === 'issue' ? 'all' : current); setTab('export'); }, []);

  return {
    page, setPage, project, assets, byId, asset, caption, visible, batch, view, setView, tab, setTab, tool, setTool, activeId, captionId, focused, setFocused,
    selection, setSelection, filter, setFilter, query, setQuery, issueIds, setIssueIds, issueLabel, showSkipped, backToExport, zoom, setZoom, scale, setScale, showRegions, setShowRegions, regions, loadRegions, rearrange,
    rawView, setRawView, rotationSnap, setRotationSnap, safeGuide, setSafeGuide, hovered, setHovered, fresh, setFresh, openSection, setOpenSection, toasts, toast, dismiss, dialog, setDialog, openDialog, choose, chooseCaption, step, confirmAndNext,
    styleDrafts, positionDrafts, previewStyle, previewPosition, applyStyle, applyPosition, liveText, setLiveText, scope, setScope, lastUnified, setLastUnified,
    editingId, editAt, startEditing, endEditing,
    options, setOptions, output, setOutput, check, checking, acknowledge, setAcknowledge, runCheck, resolve, returnToExport, setReturnToExport, jobVisible, setJobVisible,
  };
}

type Workspace = ReturnType<typeof useWorkspaceState>;
const Context = createContext<Workspace | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) { const value = useWorkspaceState(); return <Context.Provider value={value}>{children}</Context.Provider>; }
export function useWorkspace() { const context = useContext(Context); if (!context) throw new Error('Missing workspace'); return context; }
