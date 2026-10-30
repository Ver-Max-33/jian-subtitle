import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { Asset } from '../src/types.ts';
import { imagesOverriding, overriddenRows, percentOfReference, pxOnImage, rowOfKey, storedFromImagePx, storedFromPercent } from '../src/styleModel.ts';

const image = (id: string, captions: [string, string[]][]) =>
  ({ id, width: 1920, height: 1080, captions: captions.map(([cid, overrides]) => ({ id: cid, overrides })) }) as unknown as Asset;

test('fields map to the rows the panel shows', () => {
  assert.equal(rowOfKey('font_weight'), 'font');
  assert.equal(rowOfKey('font_id'), 'font');
  assert.equal(rowOfKey('stroke_width'), 'stroke');
  assert.equal(rowOfKey('max_width'), undefined);
  assert.deepEqual(overriddenRows(['stroke_width', 'font_size']), ['font_size', 'stroke']);
});

test('images with their own value are counted once each, except the caption being edited', () => {
  const assets = [image('a', [['a1', []], ['a2', ['font_size']]]), image('b', [['b1', ['font_size']], ['b2', ['font_size']]]), image('c', [['c1', ['text_color']]])];
  assert.equal(imagesOverriding(assets, 'font_size', { assetId: 'a', captionId: 'a1' }), 2);
  assert.equal(imagesOverriding(assets, 'font_size', { assetId: 'a', captionId: 'a2' }), 1);
});

test('sizes convert between the reference edge and this picture', () => {
  assert.equal(percentOfReference(54, 1080), 5);
  assert.equal(storedFromPercent(5.1, 1080), 55.08);
  assert.equal(pxOnImage(54, 1080, 720), 36);
  assert.equal(storedFromImagePx(6, 1080, 2160), 3);
  assert.equal(storedFromImagePx(5, 1080, 720), 7.5);
  assert.equal(pxOnImage(54, null, 720), 54);
  assert.equal(pxOnImage(54, 1080, null), 54);
  assert.equal(storedFromImagePx(5, 1080, null), 5);
});

test('the unified value is shown the way the field shows it', async () => {
  const { unifiedValueText } = await import('../src/styleModel.ts');
  const style = { font_size: 54, stroke_width: 2, stroke_color: [30, 30, 30, 255], text_color: [255, 255, 255, 255], show_background: false, background_color: [0, 0, 0, 160],
    effect: 'shadow', line_spacing: 10, letter_spacing: -2, skew: 19 } as unknown as import('../src/types.ts').Style;
  const at = (reference: number | null, edge: number | null = null) => ({ fontLabel: '思源黑体', reference, edge });
  assert.equal(unifiedValueText('font_size', style, at(1080)), '5.0%');
  assert.equal(unifiedValueText('font_size', style, at(null)), '54 px');
  assert.equal(unifiedValueText('stroke', style, at(1080)), '2 px · 1E1E1E');
  assert.equal(unifiedValueText('stroke', style, at(1080, 720)), '1.3 px · 1E1E1E');
  assert.equal(unifiedValueText('text_color', style, at(1080)), 'FFFFFF');
  assert.equal(unifiedValueText('background', style, at(1080)), '关');
  assert.equal(unifiedValueText('effect', style, at(1080)), '阴影');
  assert.equal(unifiedValueText('font', style, at(1080)), '思源黑体');
  assert.equal(unifiedValueText('letter_spacing', style, at(1080)), '-2 px');
  assert.equal(unifiedValueText('skew', style, at(1080)), '19°');
});

test('the rotate knob and the tag go where the canvas has room', async () => {
  const { chromeCorners } = await import('../src/styleModel.ts');
  const viewport = { left: 0, top: 0, right: 1000, bottom: 600 };
  assert.deepEqual(chromeCorners({ left: 200, top: 300, right: 800, bottom: 350 }, viewport), { knob: 'top-right', tag: 'above' });
  assert.deepEqual(chromeCorners({ left: 200, top: 5, right: 800, bottom: 55 }, viewport), { knob: 'bottom-right', tag: 'below' });
  assert.deepEqual(chromeCorners({ left: 200, top: 300, right: 990, bottom: 350 }, viewport), { knob: 'top-left', tag: 'above' });
  assert.deepEqual(chromeCorners({ left: 200, top: 5, right: 990, bottom: 55 }, viewport), { knob: 'bottom-left', tag: 'below' });
});
