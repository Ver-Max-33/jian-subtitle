// Read package metadata and license text only. Never import dependency code.
import { readFile, readdir, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const lockText = await readFile('package-lock.json', 'utf8');
const lock = JSON.parse(lockText);
const records = [];
const notices = [await readFile('THIRD_PARTY.md', 'utf8')];
for (const [location, pkg] of Object.entries(lock.packages)) {
  if (!location) continue;
  const record = { location, name: location.split('node_modules/').at(-1), version: pkg.version, integrity: pkg.integrity, resolved: pkg.resolved, license: pkg.license, installed: false };
  try {
    const actual = JSON.parse(await readFile(`${location}/package.json`, 'utf8'));
    record.installed = true;
    record.license = actual.license;
    const files = (await readdir(location)).filter(name => /^(license|licence|notice|copyright)(\.|$)/i.test(name));
    if (!files.length && record.name.startsWith('@esbuild/')) {
      const parent = JSON.parse(await readFile('node_modules/esbuild/package.json', 'utf8'));
      if (parent.version !== pkg.version || actual.license !== 'MIT') throw new Error('esbuild platform license mismatch');
      notices.push(`\n\n=== ${record.name} ${pkg.version}: shared esbuild license ===\n\n${await readFile('node_modules/esbuild/LICENSE.md', 'utf8')}`);
    } else if (!files.length) throw new Error(`No license file: ${location}`);
    for (const name of files) notices.push(`\n\n=== ${record.name} ${pkg.version}: ${name} ===\n\n${await readFile(`${location}/${name}`, 'utf8')}`);
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  records.push(record);
}
notices.push(`\n\n=== Noto Sans SC: OFL-1.1 ===\n\n${await readFile('public/fonts/OFL.txt', 'utf8')}`);
await mkdir('security', { recursive: true });
await writeFile('security/dependency-inventory.json', JSON.stringify({ lockSha256: createHash('sha256').update(lockText).digest('hex'), packages: records }, null, 2));
await writeFile('security/THIRD_PARTY_LICENSES.txt', notices.join('\n'));
console.log(`Recorded ${records.length} locked packages and bundled license notices.`);
