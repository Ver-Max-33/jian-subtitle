import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';
await mkdir('dist/assets', { recursive: true });
await mkdir('dist/fonts', { recursive: true });
await build({
  entryPoints: ['src/main.tsx'], outfile: 'dist/assets/app.js', bundle: true,
  minify: true, sourcemap: false, format: 'esm', target: ['es2022'],
  define: { 'process.env.NODE_ENV': '"production"' },
  legalComments: 'eof', metafile: false, logLevel: 'info',
  external: ['/fonts/*'],
});
await copyFile('index.html', 'dist/index.html');
await copyFile('public/fonts/NotoSansSC.ttf', 'dist/fonts/NotoSansSC.ttf');
await copyFile('public/fonts/OFL.txt', 'dist/fonts/OFL.txt');
await copyFile('security/THIRD_PARTY_LICENSES.txt', 'dist/THIRD_PARTY_LICENSES.txt');
