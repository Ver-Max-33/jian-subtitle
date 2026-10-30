# UI source and dependency record

The UI uses locally adapted **shadcn/ui Base UI** component composition, with the approved Pen R2 tokens implemented as local CSS. No remote registry CLI was executed. Button/Field are local elements; popup focus, positioning, selection, dismissal and modal semantics use Base UI.

Reviewed upstream commit: `c257f688cf4de7ec10cc1be84cad29cd4631182c`.

- [Dialog source](https://github.com/shadcn-ui/ui/blob/c257f688cf4de7ec10cc1be84cad29cd4631182c/apps/v4/registry/bases/base/ui/dialog.tsx)
- [Combobox source](https://github.com/shadcn-ui/ui/blob/c257f688cf4de7ec10cc1be84cad29cd4631182c/apps/v4/registry/bases/base/ui/combobox.tsx)
- [shadcn/ui license](https://github.com/shadcn-ui/ui/blob/c257f688cf4de7ec10cc1be84cad29cd4631182c/LICENSE.md)

shadcn/ui: MIT License, Copyright (c) 2023 shadcn.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

React, React DOM, Base UI, Floating UI: MIT. Lucide: ISC. TypeScript: Apache-2.0. esbuild: MIT. Full package licenses remain in the fixed npm packages; `scripts/dependency-guard.mjs` enumerates the installed license metadata.

No runtime CDN, analytics, online fonts or network image source is used. The application preview image is user-provided and is not included in dependency audit uploads.

## Offline interface font

Noto Sans SC (SIL Open Font License 1.1) is bundled, not installed into the OS. It is the Pen R2 interface font; the selected subtitle export font remains independent.

- Official source: [google/fonts, fixed commit](https://github.com/google/fonts/tree/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc)
- File: `public/fonts/NotoSansSC.ttf`
- SHA-256: `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`
- Full license: `public/fonts/OFL.txt`, also copied into the built app.
