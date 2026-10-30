import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { useApp } from '../state';
import { loadCaptionFont } from '../captionFonts';
import { pictureSizes, shownText, wrapLines } from '../approx';
import type { Style } from '../types';

const rgba = (c: number[]) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${c[3] / 255})`;

/** A caption drawn in the page while it changes (spec 4.4), laid out like RenderService._text_layout (ink boxes,
 * outline both sides, padding) so the precise render that replaces it moments later lands within a pixel or two.
 * `scale` is CSS pixels per picture pixel. Without the font it draws nothing and says so; the scaled render stays. */
export function ApproxCaption({ text: typed, speaker, style, edge, imageWidth, scale, transform, fallback }: { text: string; speaker: string; style: Style; edge: number; imageWidth: number; scale: number; transform: string; fallback: ReactNode }) {
  const { fonts, state } = useApp();
  const text = shownText(typed, speaker, state?.project?.showSpeaker ?? true);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [family, setFamily] = useState<string | null>();
  useEffect(() => {
    let live = true;
    void loadCaptionFont(fonts.find(f => f.id === style.font_id)).then(name => { if (live) setFamily(name); });
    return () => { live = false; };
  }, [style.font_id, fonts]);
  useLayoutEffect(() => {
    const element = canvas.current, context = element?.getContext('2d');
    if (!element || !context || !family) return;
    const size = pictureSizes(style, edge), ratio = window.devicePixelRatio || 1;
    const setFont = () => { context.font = `${style.font_weight ?? 400} ${size.fontSize}px "${family}"`; context.letterSpacing = `${size.letterSpacing}px`; };
    setFont();
    const { fontBoundingBoxAscent: ascent, fontBoundingBoxDescent: descent } = context.measureText('A');
    const slope = Math.tan(style.skew * Math.PI / 180), stroke = size.stroke;
    const lines = wrapLines(text, Math.max(24, Math.round(imageWidth * style.max_width)), s => context.measureText(s).width + 2 * stroke + slope * (ascent + descent));
    const pitch = ascent + 2 * stroke + size.lineSpacing;
    const widths = lines.map(line => context.measureText(line).width), block = Math.max(0, ...widths);
    // Ink box of every line, relative to its left-ascender origin, as Pillow measures it.
    let box: number[] | undefined;
    const origins = lines.map((line, i) => {
      const x = style.alignment === 'left' ? 0 : style.alignment === 'right' ? block - widths[i] : (block - widths[i]) / 2, y = i * pitch;
      if (line.trim()) {
        // Pillow's box is the glyphs' ink vertically but their advance horizontally (ink only where it overhangs).
        const m = context.measureText(line), top = ascent - m.actualBoundingBoxAscent, bottom = ascent + m.actualBoundingBoxDescent;
        const left = Math.min(0, -m.actualBoundingBoxLeft), right = Math.max(m.width, m.actualBoundingBoxRight);
        const ink = [x + left + slope * (ascent - bottom) - stroke, y + top - stroke, x + right + slope * (ascent - top) + stroke, y + bottom + stroke];
        box = box ? [Math.min(box[0], ink[0]), Math.min(box[1], ink[1]), Math.max(box[2], ink[2]), Math.max(box[3], ink[3])] : ink;
      }
      return [x, y];
    });
    box ??= [0, 0, 1, ascent + descent];
    const textWidth = Math.max(1, box[2] - box[0]), textHeight = Math.max(1, box[3] - box[1]);
    const background = style.show_background ? Math.max(8 * size.unit, size.fontSize * .18) : 0;
    const padding = Math.max(background, style.effect !== 'none' ? Math.max(4 * size.unit, size.fontSize * .2) : 2 * size.unit) + 2 * size.unit;
    const width = Math.ceil(textWidth + 2 * padding), height = Math.ceil(textHeight + 2 * padding);
    element.width = Math.ceil(width * scale * ratio); element.height = Math.ceil(height * scale * ratio);
    Object.assign(element.style, { width: `${width * scale}px`, height: `${height * scale}px` });
    Object.assign(element.dataset, { approxWidth: String(width), approxHeight: String(height) });
    context.setTransform(scale * ratio, 0, 0, scale * ratio, 0, 0);
    setFont();
    if (style.show_background) {
      context.fillStyle = rgba(style.background_color);
      context.beginPath();
      context.roundRect(padding - background, padding - background, textWidth + 2 * background, textHeight + 2 * background, Math.max(6 * size.unit, background / 2));
      context.fill();
    }
    const dx = padding - box[0], dy = padding - box[1], offset = Math.max(2 * size.unit, size.fontSize * .06);
    context.lineJoin = 'round';
    lines.forEach((line, i) => {
      context.save();
      // Shear about the baseline: the top of each line leans right.
      context.translate(origins[i][0] + dx, origins[i][1] + dy + ascent);
      context.transform(1, 0, -slope, 1, 0, 0);
      if (style.effect === 'shadow') { context.shadowColor = 'rgba(0, 0, 0, .67)'; context.shadowOffsetX = context.shadowOffsetY = offset * scale * ratio; }
      if (style.effect === 'glow') { context.shadowColor = rgba(style.stroke_color); context.shadowBlur = Math.max(2 * size.unit, offset) * scale * ratio * 2; }
      if (stroke > 0 || style.effect === 'outline') {
        context.lineWidth = 2 * Math.max(stroke, style.effect === 'outline' ? stroke + offset / 2 : 0);
        context.strokeStyle = rgba(style.stroke_color);
        context.strokeText(line, 0, 0);
        context.shadowColor = 'transparent';
      }
      context.fillStyle = rgba(style.text_color);
      context.fillText(line, 0, 0);
      context.restore();
    });
  }, [family, text, style, edge, imageWidth, scale]);
  // Loading, the scaled render stands in; if the font cannot load, it stays until the precise render arrives.
  if (family === undefined) return fallback;
  if (family === null) return <>{fallback}<output className="caption-updating" style={{ left: 0, top: 0, transform }}>正在更新…</output></>;
  return <canvas ref={canvas} className="caption-approx" style={{ left: 0, top: 0, transform }} aria-hidden />;
}
