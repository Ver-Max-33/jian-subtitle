// Registry checks only: lifecycle scripts remain disabled and credentials omitted.
import { spawnSync } from 'node:child_process';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const shared = ['--ignore-scripts', '--userconfig=/dev/null', '--globalconfig=./.npm-empty', '--cache=/private/tmp/jian-subtitle-npm-cache', '--registry=https://registry.npmjs.org/'];
const env = { PATH: '/usr/local/bin:/usr/bin:/bin' };
const vulnerability = spawnSync('npm', ['audit', '--json', ...shared], { env, encoding: 'utf8', maxBuffer: 8_000_000 });
const signatures = spawnSync('npm', ['audit', 'signatures', ...shared], { env, encoding: 'utf8', maxBuffer: 8_000_000 });
if (vulnerability.error || signatures.error) throw vulnerability.error || signatures.error;
const record = { checkedAt: new Date().toISOString(), lockSha256: createHash('sha256').update(await readFile('package-lock.json')).digest('hex'), vulnerabilityExitCode: vulnerability.status, audit: JSON.parse(vulnerability.stdout), signatureExitCode: signatures.status, signatureResult: signatures.stdout, signatureStderr: signatures.stderr, boundary: 'Known-vulnerability and signature checks are not proof of absence of malicious code.' };
await mkdir('security', { recursive: true });
await writeFile('security/audit-result.json', JSON.stringify(record, null, 2));
console.log(JSON.stringify({ vulnerabilities: record.audit.metadata?.vulnerabilities, signatures: signatures.stdout, status: [vulnerability.status, signatures.status] }, null, 2));
if (vulnerability.status || signatures.status) process.exit(1);
