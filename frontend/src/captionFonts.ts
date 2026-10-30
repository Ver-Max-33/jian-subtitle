import { captionFontBytes } from './bridge';
import type { Font } from './types';

const families = new Map<string, Promise<string | null>>();

/** The family the page draws a caption font with (spec 4.4): bundled fonts come from the app, once per family
 * (one variable file covers every weight); system fonts are installed and used by name. */
export function loadCaptionFont(font: Font | undefined): Promise<string | null> {
  if (!font) return Promise.resolve(null);
  if (!font.bundled) return Promise.resolve(font.family);
  let pending = families.get(font.family);
  if (!pending) {
    pending = (async () => {
      const bytes = await captionFontBytes(font.id);
      if (!bytes) return null;
      const name = `jian-${font.family.replace(/[^\w-]/g, '_')}`;
      const face = new FontFace(name, bytes, { weight: '100 900' });
      document.fonts.add(await face.load());
      return name;
    })().catch(() => null);
    families.set(font.family, pending);
  }
  return pending;
}
