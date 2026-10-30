// Drawing a caption in the page while it changes (spec 4.4): the same layout rules as RenderService, so the
// approximation lands within a couple of pixels of the precise render that replaces it. Type-only imports.
import type { Style } from './types';

/** RenderService._wrap_text: the longest prefix that fits, broken at the last space in it if there is one. */
export function wrapLines(text: string, maxWidth: number, width: (s: string) => number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split('\n')) {
    let remaining = [...paragraph];
    if (!remaining.length) { lines.push(''); continue; }
    while (remaining.length) {
      if (width(remaining.join('')) <= maxWidth) { lines.push(remaining.join('').trimEnd()); break; }
      let low = 1, high = remaining.length;
      while (low < high) {
        const middle = Math.floor((low + high + 1) / 2);
        if (width(remaining.slice(0, middle).join('')) <= maxWidth) low = middle; else high = middle - 1;
      }
      let cutoff = Math.max(1, low);
      const head = remaining.slice(0, cutoff + 1).join('');
      const space = Math.max(head.lastIndexOf(' '), head.lastIndexOf('\t'));
      if (space > 0) cutoff = [...head.slice(0, space)].length;
      lines.push(remaining.slice(0, cutoff).join('').trimEnd());
      remaining = [...remaining.slice(cutoff).join('').trimStart()];
    }
  }
  return lines;
}

/** The text the renderer draws: 「小林：…」 when the project shows speakers (export_planner.caption_requests). */
export const shownText = (text: string, speaker: string, show: boolean) => speaker && show ? `${speaker}：${text}` : text;

/** Stored sizes in this picture's pixels, and the renderer's fixed minimums scaled the same way. */
export function pictureSizes(style: Style, edge: number) {
  const unit = style.reference_edge ? edge / style.reference_edge : 1;
  return { unit, fontSize: style.font_size * unit, stroke: style.stroke_width * unit, lineSpacing: style.line_spacing * unit, letterSpacing: style.letter_spacing * unit };
}
