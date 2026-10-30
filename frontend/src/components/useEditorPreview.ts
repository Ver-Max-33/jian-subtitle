import { useEffect, useRef, useState } from 'react';
import { AppError, mediaUrl, request } from '../bridge';
import type { Asset, Preview, Project, Style } from '../types';

export type StyleDrafts = Record<string, Partial<Style>>;
export interface EditorFrame {
  identity: string;
  key: string;
  preview: Preview;
  background: string;
  layers: Record<string, string>;
  styles: Record<string, Style>;
  /** The caption text each layer was drawn with, unsaved typing included. */
  texts: Record<string, string>;
}

async function decodedMedia(token: string): Promise<string> {
  const url = await mediaUrl(token);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return url;
  } catch (error) { URL.revokeObjectURL(url); throw error; }
}

function urls(frame?: EditorFrame) {
  return frame ? [frame.background, ...Object.values(frame.layers)] : [];
}

/** One in-flight raster request, latest draft wins; the displayed frame never clears on edit. */
export function useEditorPreview(project: Project, asset: Asset, drafts: StyleDrafts, texts: Record<string, string>, mediaVersion: number, reload: number, size = 2048) {
  const identity = `${project.id}:${asset.id}:${asset.sourcePath}:${asset.modifiedAt}:${mediaVersion}`;
  const styles = Object.fromEntries(asset.captions.map(c => [c.id, { ...c.style, ...drafts[c.id] }]));
  // Position, rotation, confirmation and other images do not change the text raster; unsaved text and the speaker prefix do.
  const key = JSON.stringify([identity, reload, size, project.showSpeaker, asset.captions.map(c => ({ id: c.id, text: texts[c.id] ?? c.text, speaker: c.speaker, style: { ...styles[c.id], safe_edge: undefined } }))]);
  const latest = useRef({ project, asset, drafts, texts, styles, identity, key, size });
  latest.current = { project, asset, drafts, texts, styles, identity, key, size };
  const [frame, setFrame] = useState<EditorFrame>();
  const current = useRef<EditorFrame | undefined>(undefined);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const owned = useRef(new Set<string>());
  const pump = useRef<() => Promise<void>>(async () => {});

  pump.current = async () => {
    if (inFlight.current || !mounted.current) return;
    const input = latest.current;
    if (current.current?.key === input.key) { setPending(false); return; }
    inFlight.current = true;
    const allocated: string[] = [];
    const previous = current.current?.identity === input.identity ? current.current : undefined;
    try {
      // Drafts can outlive their caption (deleted, undone); the server rejects ids it no longer has.
      const drafts = Object.fromEntries(input.asset.captions.filter(c => Object.keys(input.drafts[c.id] ?? {}).length).map(c => [c.id, input.drafts[c.id]]));
      const payload = { assetId: input.asset.id, projectId: input.project.id, revision: input.project.revision, size: input.size, editable: true, layersOnly: true, styles: drafts, texts: input.texts, backgroundKey: previous?.preview.sourceKey };
      let response;
      try { response = await request<Preview>('preview', payload); }
      catch (failure) {
        if (!(failure instanceof AppError) || failure.code !== 'REVISION_CONFLICT' || !mounted.current || latest.current.key !== input.key) throw failure;
        // A concurrent save can advance revision without changing this caption's raster.
        const snapshot = await request<{ project: Project | null }>('state');
        if (snapshot.result.project?.id !== input.project.id) throw failure;
        response = await request<Preview>('preview', { ...payload, revision: snapshot.result.project.revision });
      }
      if (!mounted.current || latest.current.key !== input.key) return;
      const result = response.result;
      const next: Record<string, string> = {};
      const tokens = [result.backgroundToken, ...result.overlays.map(o => o.layerToken)].filter((token): token is string => !!token);
      // Wait for all decodes before adopting or revoking any URLs.
      const loaded = await Promise.allSettled(tokens.map(async token => {
        const url = await decodedMedia(token);
        allocated.push(url);
        next[token] = url;
      }));
      const failed = loaded.find(r => r.status === 'rejected');
      if (failed?.status === 'rejected') throw failed.reason;
      if (!mounted.current || latest.current.key !== input.key) return;
      const background = result.backgroundToken ? next[result.backgroundToken] : previous?.background;
      if (!background) throw new Error('原图预览已过期，请重试');
      const fresh: EditorFrame = { identity: input.identity, key: input.key, preview: result, background, layers: Object.fromEntries(result.overlays.filter(o => o.layerToken).map(o => [o.id, next[o.layerToken!]])), styles: input.styles,
        texts: Object.fromEntries(input.asset.captions.map(c => [c.id, input.texts[c.id] ?? c.text])) };
      const old = current.current;
      allocated.forEach(url => owned.current.add(url));
      allocated.length = 0;
      current.current = fresh;
      setFrame(fresh); setError(''); setPending(false);
      requestAnimationFrame(() => {
        const keep = new Set(urls(current.current));
        urls(old).forEach(url => { if (!keep.has(url)) { URL.revokeObjectURL(url); owned.current.delete(url); } });
      });
    } catch (failure) {
      if (mounted.current && latest.current.key === input.key) {
        setError((failure as Error).message || '字幕预览更新失败'); setPending(false);
      }
    } finally {
      allocated.forEach(URL.revokeObjectURL);
      inFlight.current = false;
      if (mounted.current && latest.current.key !== input.key) void pump.current();
    }
  };

  useEffect(() => {
    setError(''); setPending(true);
    clearTimeout(timer.current);
    // The page draws an approximation meanwhile; the precise render waits until changes pause (spec 4.4: 150–200 ms).
    timer.current = setTimeout(() => void pump.current(), current.current?.identity === identity ? 180 : 0);
    return () => clearTimeout(timer.current);
  }, [key]);
  useEffect(() => () => {
    mounted.current = false;
    clearTimeout(timer.current);
    owned.current.forEach(URL.revokeObjectURL);
    owned.current.clear();
  }, []);
  return { frame: frame?.identity === identity ? frame : undefined, error, pending };
}
