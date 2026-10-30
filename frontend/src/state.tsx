import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { AppError, request } from './bridge';
import type { Font, Snapshot } from './types';

interface Draft { assetId: string; captionId: string; text: string; version: number }
function useAppState() {
  const [state, setState] = useState<Snapshot | null>(null);
  const latest = useRef<Snapshot | null>(null);
  const [fonts, setFonts] = useState<Font[]>([]);
  const [error, setError] = useState<AppError | null>(null);
  const [busy, setBusy] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [mediaVersion, setMediaVersion] = useState(0);
  const draft = useRef<Draft | null>(null);
  const composing = useRef(false);
  const compositionWaiters = useRef<(() => void)[]>([]);
  const queue = useRef(Promise.resolve<unknown>(null));
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const version = useRef(0);
  const installedGeneration = useRef(0);
  const refreshing = useRef(false);
  const metadataSignature = useRef('');
  const flushing = useRef<Promise<void> | null>(null);
  const install = useCallback((incoming: Snapshot) => {
    const next = { ...incoming, project: incoming.projectUnchanged ? latest.current?.project || null : incoming.project, projectUnchanged: undefined };
    const signature = JSON.stringify({ ...next, project: undefined });
    if (next.project === latest.current?.project && signature === metadataSignature.current) return;
    metadataSignature.current = signature;
    latest.current = next; installedGeneration.current++; setState(next);
  }, []);
  const refresh = useCallback(async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    const generation = installedGeneration.current;
    const project = latest.current?.project;
    try {
      const r = await request<Snapshot>('state', project ? { knownProjectId: project.id, knownRevision: project.revision, knownPath: project.path } : {});
      if (generation === installedGeneration.current) install(r.result);
    } catch (e) { setError(e as AppError); }
    finally { refreshing.current = false; }
  }, [install]);
  useEffect(() => { void refresh(); request<Font[]>('fonts').then(r => setFonts(r.result)).catch(e => setError(e)); }, [refresh]);
  useEffect(() => { const id = setInterval(() => { if (busy === 0 && !dirty) void refresh(); }, 750); return () => clearInterval(id); }, [busy, dirty, refresh]);
  // `quiet` is bookkeeping the user did not ask for (remembering the open page): no busy flash, no error bar.
  const command = useCallback(<T,>(action: string, payload: Record<string, unknown> = {}, { quiet = false } = {}): Promise<T> => {
    const task = queue.current.catch(() => {}).then(async () => {
      if (!quiet) setBusy(n => n + 1);
      try {
        const response = await request<T>(action, payload, latest.current || undefined);
        if (response.state) install(response.state);
        if (action === 'relocate' || action === 'open_project' || action === 'open_recent') setMediaVersion(n => n + 1);
        if (!quiet) setError(null);
        return response.result;
      } catch (e) { if (!quiet) setError(e as AppError); throw e; }
      finally { if (!quiet) setBusy(n => n - 1); }
    });
    queue.current = task;
    return task;
  }, [install]);
  const flush = useCallback((): Promise<void> => {
    if (flushing.current) return flushing.current;
    const run = async () => {
      clearTimeout(timer.current);
      if (composing.current) await new Promise<void>(resolve => compositionWaiters.current.push(resolve));
      while (draft.current) {
        const d = draft.current;
        await command('caption_text', { assetId: d.assetId, captionId: d.captionId, text: d.text });
        if (draft.current?.version === d.version) { draft.current = null; setDirty(false); }
      }
      await queue.current.catch(() => {});
      const invalid = document.querySelector<HTMLInputElement>('[aria-invalid="true"]');
      if (invalid) { invalid.focus(); throw new AppError('INVALID_INPUT', '请先修正当前输入'); }
    };
    flushing.current = run().finally(() => { flushing.current = null; });
    return flushing.current;
  }, [command]);
  const schedule = useCallback(() => { clearTimeout(timer.current); timer.current = setTimeout(() => { if (!composing.current) void flush().catch(() => {}); }, 500); }, [flush]);
  const editText = useCallback((assetId: string, captionId: string, text: string) => {
    draft.current = { assetId, captionId, text, version: ++version.current };
    setDirty(true); schedule();
  }, [schedule]);
  const compose = useCallback((active: boolean) => {
    composing.current = active;
    if (!active) { compositionWaiters.current.splice(0).forEach(fn => fn()); schedule(); }
  }, [schedule]);
  const act = useCallback((fn: () => Promise<unknown>) => { void fn().catch(e => setError(e as AppError)); }, []);
  const mutate = useCallback(async <T,>(action: string, payload: Record<string, unknown> = {}) => { await flush(); return command<T>(action, payload); }, [flush, command]);
  return { state, fonts, error, busy, dirty, mediaVersion, draft, setError, refresh, command, flush, editText, compose, act, mutate };
}
type AppState = ReturnType<typeof useAppState>;
const Context = createContext<AppState | null>(null);
export function AppProvider({ children }: { children: ReactNode }) { const value = useAppState(); return <Context.Provider value={value}>{children}</Context.Provider>; }
export function useApp() { const context = useContext(Context); if (!context) throw new Error('Missing provider'); return context; }
