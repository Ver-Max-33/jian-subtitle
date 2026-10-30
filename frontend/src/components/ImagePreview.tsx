import { useEffect, useRef, useState } from 'react';
import { ImageOff } from 'lucide-react';
import { mediaUrl, request } from '../bridge';
import { useApp } from '../state';
import type { Asset, Preview } from '../types';

const rawCache = new Map<string, { url: string; meta: Preview; estimatedBytes: number }>();
const cacheKey = (projectId: string | undefined, assetId: string, source: Asset | undefined, mediaVersion: number, size: number) => `${projectId}:${assetId}:${source?.sourcePath}:${source?.modifiedAt}:${mediaVersion}:${size}`;
/** Any already-decoded thumbnail of this image, largest first: an instant stand-in while the editor frame loads. */
export function cachedPreview(projectId: string, asset: Asset, mediaVersion: number) {
  return [480, 240].map(size => rawCache.get(cacheKey(projectId, asset.id, asset, mediaVersion, size))).find(Boolean);
}
// The Python server is threaded; a few parallel decodes fill a screen of thumbnails without starving edits.
let active = 0;
const waiting: (() => void)[] = [];
function limited(task: () => Promise<void>) {
  const run = () => task().finally(() => { const next = waiting.shift(); if (next) next(); else active--; });
  if (active < 3) { active++; void run(); } else waiting.push(() => void run());
}
export function ImagePreview({ assetId, className = '', onClick, size = 480, onMeta }: { assetId: string; className?: string; onClick?: () => void; size?: number; onMeta?: (meta: Preview) => void }) {
  const { state, mediaVersion } = useApp();
  const project = state?.project;
  const source = project?.assets.find(a => a.id === assetId);
  const key = cacheKey(project?.id, assetId, source, mediaVersion, size);
  const [url, setUrl] = useState(rawCache.get(key)?.url);
  const callback = useRef(onMeta); callback.current = onMeta;
  const [failed, setFailed] = useState(false);
  const element = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(size >= 1440);
  useEffect(() => {
    if (visible || !element.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: '160px' });
    observer.observe(element.current);
    return () => observer.disconnect();
  }, [visible]);
  useEffect(() => {
    let alive = true;
    const cached = rawCache.get(key);
    setFailed(false); setUrl(cached?.url);
    if (cached) callback.current?.(cached.meta);
    if (!project || cached || !visible) return;
    const load = async () => {
      if (!alive) return;
      try {
        const r = await request<Preview>('preview', { assetId, projectId: project.id, revision: project.revision, size, raw: true });
        const next = await mediaUrl(r.result.token);
        if (!alive) { URL.revokeObjectURL(next); return; }
        const scale = Math.min(1, size / Math.max(r.result.width, r.result.height));
        rawCache.set(key, { url: next, meta: r.result, estimatedBytes: r.result.width * r.result.height * scale * scale * 4 });
        while (rawCache.size > 240 || [...rawCache.values()].reduce((sum, entry) => sum + entry.estimatedBytes, 0) > 64 * 1024 * 1024) { const oldest = rawCache.keys().next().value!; URL.revokeObjectURL(rawCache.get(oldest)!.url); rawCache.delete(oldest); }
        setUrl(next);
        callback.current?.(r.result);
      } catch { if (alive) setFailed(true); }
    };
    if (size >= 1440) void load();
    else limited(load);
    return () => { alive = false; };
  }, [key, project?.revision, visible]);
  return <div ref={element} className={`image-preview ${className}`} onClick={onClick}>{url ? <img src={url} alt="图片预览" draggable={false} /> : failed ? <ImageOff aria-label="无法读取图片" /> : <span className="image-loading" aria-label="正在加载图片" />}</div>;
}
