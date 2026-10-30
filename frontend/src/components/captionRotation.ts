export interface Point { x: number; y: number }

/** Project angles use Pillow's counter-clockwise convention, in [-180, 180]. */
export function normalizeRotation(angle: number) {
  const wrapped = ((angle + 180) % 360 + 360) % 360 - 180;
  return Math.round(wrapped * 10) / 10 || 0;
}

export function pointerRotationDelta(previous: Point, next: Point, center: Point) {
  const ax = previous.x - center.x, ay = previous.y - center.y;
  const bx = next.x - center.x, by = next.y - center.y;
  // Crossing the pivot must not turn a tiny pointer movement into a half-turn.
  if (Math.hypot(ax, ay) < 12 || Math.hypot(bx, by) < 12) return 0;
  return -Math.atan2(ax * by - ay * bx, ax * bx + ay * by) * 180 / Math.PI;
}

export function snapRotation(angle: number, previous?: number) {
  // Separate enter/leave thresholds prevent chatter at the magnetic boundary.
  if (previous !== undefined && Math.abs(angle - previous) <= 4) return previous;
  const nearest = Math.round(angle / 45) * 45;
  return Math.abs(angle - nearest) <= 2 ? nearest : undefined;
}
