import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  activate,
  allowlist,
  build,
  readState,
  rollback,
  verifyRelease,
} from '../scripts/publication/pages-artifact-poc.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

async function filesBelow(path, base = path) {
  const output = [];
  for (const entry of await readdir(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isDirectory()) output.push(...(await filesBelow(child, base)));
    else output.push(relative(base, child).replaceAll('\\', '/'));
  }
  return output.sort();
}

test('build emits only allowlisted runtime files and a verifiable manifest', async () => {
  const releases = await mkdtemp(join(tmpdir(), 'spatchin-pages-poc-'));
  const manifest = await build(root, releases, 'release-one');
  assert.deepEqual(manifest.files.map((entry) => entry.path).sort(), await allowlist());
  assert.deepEqual(
    await filesBelow(join(releases, 'release-one')),
    [...(await allowlist()), '.nojekyll', '_publication/manifest.json'].sort(),
  );
  for (const excluded of [
    'AGENTS.md',
    'package-lock.json',
    'scripts',
    'tests',
    'workers',
    'docs',
  ]) {
    assert.equal((await filesBelow(join(releases, 'release-one'))).includes(excluded), false);
  }
  await verifyRelease(releases, 'release-one');
});

test('activation is reversible and rollback restores the verified prior release', async () => {
  const releases = await mkdtemp(join(tmpdir(), 'spatchin-pages-rollback-'));
  await build(root, releases, 'release-one');
  await build(root, releases, 'release-two');
  assert.deepEqual(await activate(releases, 'release-one'), {
    current: 'release-one',
    previous: null,
  });
  assert.deepEqual(await activate(releases, 'release-two'), {
    current: 'release-two',
    previous: 'release-one',
  });
  assert.deepEqual(await rollback(releases), {
    current: 'release-one',
    previous: 'release-two',
  });
  assert.deepEqual(
    JSON.parse(await readFile(join(releases, 'active.json'), 'utf8')),
    await readState(releases),
  );
});
