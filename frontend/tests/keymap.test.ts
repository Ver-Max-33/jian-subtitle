import { test } from 'node:test';
import assert from 'node:assert/strict';
import { editorKey, shortcutText, type KeyLike } from '../src/keymap.ts';

const key = (k: string, extra: Partial<KeyLike> = {}): KeyLike => ({ key: k, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, isComposing: false, ...extra });

test('typing on the canvas: Enter is a new line, Esc ends, Ctrl/⌘+Enter confirms (spec 4.3)', () => {
  assert.equal(editorKey(key('Enter')), null);
  assert.equal(editorKey(key('Escape')), 'end');
  assert.equal(editorKey(key('Enter', { ctrlKey: true })), 'confirm');
  assert.equal(editorKey(key('Enter', { metaKey: true })), 'confirm');
});

test('nothing fires while the input method is composing', () => {
  assert.equal(editorKey(key('Enter', { ctrlKey: true, isComposing: true })), null);
  assert.equal(editorKey(key('Escape', { isComposing: true })), null);
});

test('shortcut labels follow the platform', () => {
  assert.equal(shortcutText('Ctrl+Enter', true), '⌘Enter');
  assert.equal(shortcutText('Ctrl+Shift+Z', true), '⇧⌘Z');
  assert.equal(shortcutText('Ctrl+Z', false), 'Ctrl+Z');
  assert.equal(shortcutText('V', true), 'V');
});

test('global keys follow the table in spec 4.6', async () => {
  const { globalKey } = await import('../src/keymap.ts');
  type Context = Parameters<typeof globalKey>[1];
  const at = (o: Partial<Context> = {}): Context => ({ target: 'canvas', editing: false, overlay: false, workspace: true, canvasView: true, editTab: true, captionSelected: true, imageSelected: true, ...o });
  assert.equal(globalKey(key('Enter', { isComposing: true }), at()), null);
  assert.equal(globalKey(key('Enter'), at()), 'confirmNext');
  assert.equal(globalKey(key('Enter'), at({ target: 'list' })), null);
  assert.equal(globalKey(key('Enter', { ctrlKey: true }), at({ target: 'text' })), 'confirmNext');
  assert.equal(globalKey(key('Enter', { metaKey: true }), at({ target: 'list' })), 'confirmNext');
  assert.equal(globalKey(key('Enter', { ctrlKey: true }), at({ target: 'text', editing: true })), null);
  assert.equal(globalKey(key('ArrowLeft'), at()), 'prev');
  assert.equal(globalKey(key('ArrowRight'), at({ target: 'other' })), 'next');
  assert.equal(globalKey(key('ArrowLeft'), at({ target: 'text' })), null);
  assert.equal(globalKey(key('T'), at()), 'toolText');
  assert.equal(globalKey(key('v'), at()), 'toolSelect');
  assert.equal(globalKey(key('t'), at({ target: 'text' })), null);
  assert.equal(globalKey(key('t'), at({ overlay: true })), null);
  assert.equal(globalKey(key('z', { ctrlKey: true }), at()), null);
  assert.equal(globalKey(key('Backspace'), at()), 'deleteCaption');
  assert.equal(globalKey(key('Delete'), at({ editing: true })), null);
  assert.equal(globalKey(key('Delete'), at({ captionSelected: false })), null);
  assert.equal(globalKey(key('Delete'), at({ target: 'list' })), null);
});

test('confirming and deleting act only on the edit tab’s canvas view', async () => {
  const { globalKey } = await import('../src/keymap.ts');
  type Context = Parameters<typeof globalKey>[1];
  const at = (o: Partial<Context> = {}): Context => ({ target: 'canvas', editing: false, overlay: false, workspace: true, canvasView: true, editTab: true, captionSelected: true, imageSelected: true, ...o });
  assert.equal(globalKey(key('Enter'), at({ editTab: false })), null);
  assert.equal(globalKey(key('Enter', { ctrlKey: true }), at({ editTab: false })), null);
  assert.equal(globalKey(key('Delete'), at({ editTab: false })), null);
  assert.equal(globalKey(key('Delete'), at({ canvasView: false })), null);
  assert.equal(globalKey(key('ArrowRight'), at({ editTab: false })), 'next');
});
