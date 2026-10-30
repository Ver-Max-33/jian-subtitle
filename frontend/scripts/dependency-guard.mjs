import fs from 'node:fs';
import assert from 'node:assert/strict';
const manifest = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const lock = JSON.parse(fs.readFileSync('package-lock.json', 'utf8'));
assert.equal(lock.lockfileVersion, 3);
for (const [name, version] of Object.entries({ ...manifest.dependencies, ...manifest.devDependencies })) {
  assert.match(version, /^\d+\.\d+\.\d+$/, `${name}: exact version required`);
  assert.equal(lock.packages[`node_modules/${name}`]?.version, version, `${name}: lock drift`);
}
const result = [];
for (const [key, entry] of Object.entries(lock.packages)) {
  if (!key) continue;
  assert(!entry.link, `${key}: links forbidden`);
  assert.equal(new URL(entry.resolved).origin, 'https://registry.npmjs.org', `${key}: registry`);
  assert.match(entry.integrity, /^sha512-/, `${key}: integrity required`);
  const packagePath = `${key}/package.json`;
  if (!fs.existsSync(packagePath)) continue; // Other OS optional binaries are locked, not installed.
  const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  const hooks = Object.keys(pkg.scripts || {}).filter(x => /^(preinstall|install|postinstall|prepare)$/.test(x));
  assert(hooks.length === 0 || (pkg.name === 'esbuild' && pkg.version === '0.28.2' && hooks.join() === 'postinstall'), `${key}: unexpected lifecycle scripts`);
  result.push({ name: pkg.name, version: pkg.version, license: pkg.license, lifecycleScriptsBlocked: hooks });
}
console.log(JSON.stringify({ installed: result.length, packages: result }, null, 2));
