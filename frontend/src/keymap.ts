// Keys (spec 4.3, 4.6). Plain functions so `node --experimental-strip-types --test` can run them.

export interface KeyLike { key: string; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean; isComposing: boolean }

/** Typing on the canvas: Enter is a new line (the field's own), Esc ends, Ctrl/⌘ + Enter ends and confirms. */
export function editorKey(e: KeyLike): 'end' | 'confirm' | null {
  if (e.isComposing) return null;
  if (e.key === 'Escape') return 'end';
  return e.key === 'Enter' && (e.ctrlKey || e.metaKey) ? 'confirm' : null;
}

/** Where the key was pressed: a text field, the canvas, a list (left panel, list view), or anywhere else. */
export type KeyTarget = 'text' | 'canvas' | 'list' | 'other';
export interface KeyContext { target: KeyTarget; editing: boolean; overlay: boolean; workspace: boolean; canvasView: boolean; editTab: boolean; captionSelected: boolean; imageSelected: boolean }
export type GlobalAction = 'prev' | 'next' | 'confirmNext' | 'toolText' | 'toolSelect' | 'deleteCaption';

/** The few shortcuts of spec 4.6. Lists keep their own Enter (start editing), text fields their own keys, and
 * system shortcuts (other modifiers) pass through; typing on the canvas handles Ctrl/⌘ + Enter itself. */
export function globalKey(e: KeyLike, at: KeyContext): GlobalAction | null {
  if (e.isComposing || !at.workspace || at.overlay) return null;
  // The export tab's canvas is a read-only preview: it pages, nothing else.
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.altKey) return !at.editing && at.editTab && at.imageSelected ? 'confirmNext' : null;
  if (e.ctrlKey || e.metaKey || e.altKey || at.editing || at.target === 'text') return null;
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') return e.shiftKey ? null : e.key === 'ArrowLeft' ? 'prev' : 'next';
  if (!at.canvasView || !at.editTab) return null;
  if (e.key === 'Enter') return at.target === 'canvas' && at.imageSelected ? 'confirmNext' : null;
  const letter = e.key.toLowerCase();
  if (letter === 't' || letter === 'v') return letter === 't' ? 'toolText' : 'toolSelect';
  if ((e.key === 'Delete' || e.key === 'Backspace') && at.target === 'canvas' && at.captionSelected) return 'deleteCaption';
  return null;
}

/** 「下一张 →」: macOS shows ⌘ and ⇧ in its own order, Windows spells the keys out. */
export function shortcutText(combo: string, mac: boolean): string {
  if (!mac) return combo;
  const keys = combo.split('+');
  return `${keys.includes('Shift') ? '⇧' : ''}${keys.includes('Ctrl') ? '⌘' : ''}${keys.filter(k => k !== 'Ctrl' && k !== 'Shift').join('')}`;
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
