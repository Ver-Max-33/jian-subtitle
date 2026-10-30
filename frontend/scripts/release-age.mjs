// Reads public npm metadata only. Does not import or execute installed packages.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const lockBytes = await readFile('package-lock.json');
const lock = JSON.parse(lockBytes);
const now = new Date();
const rows = [];
for (const [location, item] of Object.entries(lock.packages)) {
  if (!location) continue;
  const name = location.split('node_modules/').at(-1);
  const response = await fetch(`https://registry.npmjs.org/${encodeURIComponent(name)}`, { signal: AbortSignal.timeout(20000) });
  if (!response.ok) throw new Error(`${name}: metadata ${response.status}`);
  const metadata = await response.json();
  const published = metadata.time?.[item.version];
  if (!published) throw new Error(`${name}: missing publication timestamp`);
  const release = metadata.versions[item.version];
  if (release.dist.integrity !== item.integrity) throw new Error(`${name}: integrity mismatch`);
  const ageDays = Math.floor((now - new Date(published)) / 86400000);
  rows.push({ name, version: item.version, published, ageDays, integrity: item.integrity, license: release.license, scripts: release.scripts || {}, repository: release.repository, deprecated: release.deprecated || null });
}
await mkdir('security', { recursive: true });
await writeFile('security/release-review.json', JSON.stringify({ checkedAt: now.toISOString(), lockSha256: createHash('sha256').update(lockBytes).digest('hex'), minimumAgeDays: 14, rows }, null, 2));
const young = rows.filter(row => row.ageDays < 14);
console.log(JSON.stringify({ reviewed: rows.length, young: young.map(({ name, version, ageDays }) => ({ name, version, ageDays })) }));
if (young.length) process.exitCode = 1;
