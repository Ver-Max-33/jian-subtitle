import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { useApp } from '../state';
import { useWorkspace } from '../workspace';
import { loadCaptionFont } from '../captionFonts';
import { editorKey, isMac, shortcutText } from '../keymap';
import type { Caption, Style } from '../types';

const rgba = (c: number[]) => `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${c[3] / 255})`;

/** CSS that draws a caption the way RenderService lays it out; `unit` is CSS pixels per stored pixel (spec 4.3, 4.4). */
export function captionCss(style: Style, unit: number, family: string | null): CSSProperties {
  const padding = style.show_background ? Math.max(8, style.font_size * .18) : 2;
  return {
    fontFamily: `${family ? `"${family}", ` : ''}"Noto Sans SC", sans-serif`,
    fontWeight: style.font_weight ?? 400,
    fontSize: style.font_size * unit,
    letterSpacing: style.letter_spacing * unit,
    // Pillow's line pitch: the ascender (about 1.16 em in the bundled CJK faces), the outline both sides, the spacing.
    lineHeight: `${(style.font_size * 1.16 + 2 * style.stroke_width + style.line_spacing) * unit}px`,
    color: rgba(style.text_color),
    textAlign: style.alignment as CSSProperties['textAlign'],
    WebkitTextStroke: style.stroke_width > 0 ? `${2 * style.stroke_width * unit}px ${rgba(style.stroke_color)}` : undefined,
    paintOrder: 'stroke fill',
    background: style.show_background ? rgba(style.background_color) : 'transparent',
    padding: padding * unit,
    borderRadius: style.show_background ? Math.max(6, padding / 2) * unit : 0,
  };
}

/** Where a click lands in the text: lay a same-styled copy over the field and pick the nearest character on the
 * clicked line (measured, since hit-testing a just-mounted copy is unreliable). */
function offsetAt(field: HTMLTextAreaElement, x: number, y: number): number {
  const mirror = document.createElement('div'), css = getComputedStyle(field);
  for (const name of ['fontFamily', 'fontSize', 'fontWeight', 'letterSpacing', 'lineHeight', 'padding', 'textAlign', 'boxSizing', 'transform'] as const) mirror.style[name] = css[name];
  Object.assign(mirror.style, { position: 'absolute', left: `${field.offsetLeft}px`, top: `${field.offsetTop}px`, width: `${field.clientWidth}px`, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', visibility: 'hidden' });
  mirror.textContent = field.value;
  field.parentElement!.append(mirror);
  const text = mirror.firstChild, range = document.createRange();
  let best = field.value.length, distance = Infinity;
  for (let i = 0; text && i < field.value.length; i++) {
    range.setStart(text, i); range.setEnd(text, i + 1);
    const box = range.getBoundingClientRect();
    if (!box.width && !box.height) continue;
    const off = (value: number, low: number, high: number) => (value < low ? low - value : value > high ? value - high : 0);
    const score = off(y, box.top, box.bottom) * 1e4 + off(x, box.left, box.right);
    if (score < distance) { distance = score; best = x < box.left + box.width / 2 ? i : i + 1; }
  }
  mirror.remove();
  return best;
}

/** Typing on the picture (spec 4.3): the caption's own font, size, outline and slant, sharing one draft with the panel. */
export function InlineEditor({ caption, style, transform, maxWidth, unit }: { caption: Caption; style: Style; transform: string; maxWidth: number; unit: number }) {
  const { editText, compose, fonts } = useApp();
  const w = useWorkspace();
  const field = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const [text, setText] = useState(w.liveText?.captionId === caption.id ? w.liveText.text : caption.text);
  const [family, setFamily] = useState<string | null>(null);
  useEffect(() => { void loadCaptionFont(fonts.find(f => f.id === style.font_id)).then(setFamily); }, [style.font_id, fonts]);
  // The panel's field may type into the same caption.
  useEffect(() => { if (!composing.current && w.liveText?.captionId === caption.id && w.liveText.text !== text) setText(w.liveText.text); }, [w.liveText]);
  useLayoutEffect(() => {
    field.current?.focus({ preventScroll: true });
    // After the double click has finished with the page; earlier, the browser moves the caret back to the end.
    const frame = requestAnimationFrame(() => {
      const element = field.current;
      if (!element) return;
      const offset = w.editAt ? offsetAt(element, w.editAt.x, w.editAt.y) : element.value.length;
      element.setSelectionRange(offset, offset);
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  const end = (confirm: boolean) => void w.endEditing({ confirm });
  return <div className="inline-editor-anchor" style={{ left: 0, top: 0, transform }}>
    <textarea ref={field} className="inline-editor" value={text} rows={1} spellCheck={false} placeholder="输入字幕…" aria-label="字幕文字"
      style={{ ...captionCss(style, unit, family), maxWidth, transform: style.skew ? `skewX(${-style.skew}deg)` : undefined }}
      onCompositionStart={() => { composing.current = true; compose(true); }}
      onCompositionEnd={e => { composing.current = false; compose(false); w.setLiveText({ captionId: caption.id, text: e.currentTarget.value }); }}
      onChange={e => { setText(e.target.value); editText(w.asset!.id, caption.id, e.target.value); if (!composing.current) w.setLiveText({ captionId: caption.id, text: e.target.value }); }}
      onKeyDown={e => {
        const action = editorKey({ key: e.key, ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, altKey: e.altKey, isComposing: e.nativeEvent.isComposing });
        if (action) { e.preventDefault(); e.stopPropagation(); end(action === 'confirm'); }
      }}
      onBlur={() => end(false)} />
    <div className="inline-hint" aria-hidden>Enter 换行 · Esc 结束 · {shortcutText('Ctrl+Enter', isMac)} 确认并下一张</div>
  </div>;
}
