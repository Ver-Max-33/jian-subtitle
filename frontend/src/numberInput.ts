/**
 * What a number field keeps when editing ends: a number outside the range becomes the nearest allowed value,
 * anything that is not a number returns null so the field goes back to its old value. Either way the field
 * stops being invalid, so a mistyped value never blocks the rest of the panel.
 */
export function settleNumber(text: string, { min, max, step, digits }: { min: number; max: number; step: number; digits: number }): number | null {
  const n = Number(text);
  if (text.trim() === '' || !Number.isFinite(n)) return null;
  const rounded = step >= 1 ? Math.round(n) : Number(n.toFixed(Math.max(digits, 1)));
  return Math.min(max, Math.max(min, rounded));
}
