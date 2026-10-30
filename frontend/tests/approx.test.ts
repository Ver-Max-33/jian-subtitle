import { test } from 'node:test';
import assert from 'node:assert/strict';
import { wrapLines } from '../src/approx.ts';

// Same rules as RenderService._wrap_text, measured with a fixed advance per character.
const width = (s: string) => 10 * [...s].length;

test('lines break where the Python renderer breaks them', () => {
  assert.deepEqual(wrapLines('你平时常来这条街吗', 45, width), ['你平时常', '来这条街', '吗']);
  assert.deepEqual(wrapLines('hello world again', 60, width), ['hello', 'world', 'again']);
  assert.deepEqual(wrapLines('a\n\nb', 100, width), ['a', '', 'b']);
  assert.deepEqual(wrapLines('abc', 5, width), ['a', 'b', 'c']);
  assert.deepEqual(wrapLines('短句', 100, width), ['短句']);
});

test('the speaker prefix is drawn the way the renderer adds it (export_planner.caption_requests)', async () => {
  const { shownText } = await import('../src/approx.ts');
  assert.equal(shownText('早上六点就出发了', '小林', true), '小林：早上六点就出发了');
  assert.equal(shownText('早上六点就出发了', '小林', false), '早上六点就出发了');
  assert.equal(shownText('早上六点就出发了', '', true), '早上六点就出发了');
});
