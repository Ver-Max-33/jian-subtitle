import { useEffect } from 'react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import { globalKey, type KeyTarget } from '../keymap';

/** Text fields own their keys; the canvas is the picture area, or nothing focused (a click on the picture). */
function targetOf(element: Element | null): KeyTarget {
  if (!element || element === document.body) return 'canvas';
  if (element.closest('input, textarea, select, [contenteditable="true"]')) return 'text';
  if (element.closest('.canvas-area')) return 'canvas';
  return element.closest('.asset-list, .list-scroll') ? 'list' : 'other';
}

/** The shortcuts of spec 4.6; undo and redo stay in App, typing on the canvas handles its own keys. */
export function Shortcuts() {
  const { state, act, mutate } = useApp();
  const w = useWorkspace();
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      // A control that used the key itself (a list moving its focus, a tab strip) keeps it.
      if (e.defaultPrevented) return;
      const { asset, caption } = w;
      const tasks = [state?.job, state?.batchTask, state?.importTask].map(task => task?.state);
      const action = globalKey(e, {
        target: targetOf(e.target as Element | null),
        editing: !!w.editingId,
        // Open menus, selects and popovers (mounted only while open); tooltips do not count.
        overlay: !!w.dialog || !!document.querySelector('.menu-popup, .popover'),
        workspace: w.page === 'workspace' && !tasks.some(s => s === 'running' || s === 'stopping'),
        canvasView: w.view === 'canvas', editTab: w.tab === 'edit',
        captionSelected: !!caption && !w.batch,
        imageSelected: !!asset && !w.batch && asset.captions.length > 0 && asset.status !== 'unreadable',
      });
      // A held key repeats: paging may, confirming and deleting may not.
      if (!action || (e.repeat && action !== 'prev' && action !== 'next')) return;
      e.preventDefault();
      if (action === 'prev' || action === 'next') w.step(action === 'prev' ? -1 : 1);
      else if (action === 'confirmNext') w.confirmAndNext();
      else if (action === 'toolSelect') w.setTool('select');
      // The same limits as the toolbar's 添加字幕.
      else if (action === 'toolText') { if (asset && !w.batch && asset.captions.length < 20) w.setTool('text'); }
      else if (asset && caption) act(async () => {
        await mutate('caption_delete', { assetId: asset.id, captionId: caption.id });
        w.toast({ text: '已删除字幕', action: { label: '撤销', run: () => act(() => mutate('undo')) } });
      });
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  });
  return null;
}
