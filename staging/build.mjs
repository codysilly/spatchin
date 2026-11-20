// Explicit allowlist. Do not publish the repository, capture artifacts or secrets.
import { readFile, mkdir, rm, writeFile, copyFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const dist = join(here, 'dist');
const paths = [
  'styles.css', 'charcoal-dashboard.css', 'app.js', 'airport-catalog.js',
  'notam-reader.js', 'notam-snapshots.js', 'taf-reader.js', 'taf-timeline.js', 'scan.js',
  'assets/branding/logo-cyan-magenta.svg',
  'assets/branding/logo-16.png', 'assets/branding/logo-32.png',
  'assets/branding/logo-64.png', 'assets/branding/logo-128.png',
  'assets/branding/logo-180.png'
];
const original = await readFile(join(root, 'dashboard/index.html'), 'utf8');
const tag = '<base href="../">';
if (!original.includes(tag) || original.split(tag).length !== 2) {
  throw new Error('Dashboard base path differs from validated source');
}
await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });
await writeFile(join(dist, 'index.html'), original.replace(tag, '<base href="/">'));
for (const path of paths) {
  await mkdir(dirname(join(dist, path)), { recursive: true });
  await copyFile(join(root, path), join(dist, path));
}
console.log('Prepared private dashboard static files (no provider requests).');
