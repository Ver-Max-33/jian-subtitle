import type { Reply, Snapshot } from './types';

const session = new URLSearchParams(location.hash.slice(1)).get('session') || sessionStorage.getItem('jian-session') || '';
if (session) sessionStorage.setItem('jian-session', session);
history.replaceState(null, '', location.pathname);

export class AppError extends Error {
  constructor(public code: string, message: string, public affectedIds: string[] = []) { super(message); }
}
export async function request<T>(action: string, payload: Record<string, unknown> = {}, state?: Snapshot, requestId = crypto.randomUUID()): Promise<Reply<T>> {
  const response = await fetch('./api', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Jian-Token': session },
    body: JSON.stringify({ action, payload, projectId: state?.project?.id, expectedRevision: state?.project?.revision, requestId }),
    credentials: 'omit', cache: 'no-store',
  });
  if (!response.ok) throw new AppError('CONNECTION_ERROR', '无法连接桌面服务，请关闭后重新启动简幕。');
  const result = await response.json() as Reply<T>;
  if (!result.ok) throw new AppError(result.error?.code || 'UNKNOWN', result.error?.message || '操作失败', result.error?.affectedIds);
  return result;
}
export async function mediaUrl(token: string) {
  const response = await fetch(`./media/${encodeURIComponent(token)}`, { headers: { 'X-Jian-Token': session }, credentials: 'omit' });
  if (!response.ok) throw new AppError('PREVIEW_EXPIRED', '预览已过期，请重试');
  return URL.createObjectURL(await response.blob());
}
/** A bundled caption font for drawing previews in the page (spec 4.4); null when it is not one of ours. */
export async function captionFontBytes(fontId: string): Promise<ArrayBuffer | null> {
  const response = await fetch(`./caption-fonts/${encodeURIComponent(fontId)}`, { headers: { 'X-Jian-Token': session }, credentials: 'omit' });
  return response.ok ? response.arrayBuffer() : null;
}
