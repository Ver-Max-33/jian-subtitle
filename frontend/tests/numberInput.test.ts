import { test } from 'node:test';
import assert from 'node:assert/strict';
import { settleNumber } from '../src/numberInput.ts';

const percent = { min: 0.8, max: 47.4, step: 0.1, digits: 1 };
const whole = { min: 0, max: 100, step: 1, digits: 0 };

test('a number outside the range becomes the nearest allowed value instead of locking the panel', () => {
  assert.equal(settleNumber('999', percent), 47.4);
  assert.equal(settleNumber('-5', percent), 0.8);
  assert.equal(settleNumber('150', whole), 100);
});

test('something that is not a number goes back to the old value', () => {
  assert.equal(settleNumber('', percent), null);
  assert.equal(settleNumber('  ', percent), null);
  assert.equal(settleNumber('abc', percent), null);
  assert.equal(settleNumber('1e999', percent), null);
});

test('values round to what the field shows', () => {
  assert.equal(settleNumber('6.25', percent), 6.3);
  assert.equal(settleNumber('5.5', whole), 6);
  assert.equal(settleNumber('7', percent), 7);
});
