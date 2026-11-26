import { createHash } from 'node:crypto';
import { copyFile, mkdir, open, readFile, rename, stat } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const allowlistPath = join(repositoryRoot, 'config/pages-publication-allowlist.json');

function safePath(root, path) {
  const target = resolve(root, path);
  if (target !== resolve(root) && !target.startsWith(`${resolve(root)}${sep}`)) {
    throw new Error(`Path escapes root: ${path}`);
  }
  return target;
}

async function allowlist() {
  const parsed = JSON.parse(await readFile(allowlistPath, 'utf8'));
  if (!Array.isArray(parsed.files) || new Set(parsed.files).size !== parsed.files.length) {
    throw new Error('Publication allowlist must contain unique files');
  }
  return [...parsed.files].sort();
}

async function digest(path) {
  return createHash('sha256').update(await readFile(path)).digest('hex');
}

async function writeExclusive(path, contents) {
  await mkdir(dirname(path), { recursive: true });
  const handle = await open(path, 'wx');
  try {
    await handle.writeFile(contents);
  } finally {
    await handle.close();
  }
}

async function verifyRelease(releasesRoot, releaseId) {
  const release = safePath(releasesRoot, releaseId);
  const manifest = JSON.parse(await readFile(join(release, '_publication/manifest.json'), 'utf8'));
  for (const entry of manifest.files) {
    const path = safePath(release, entry.path);
    const info = await stat(path);
    if (!info.isFile() || info.size !== entry.bytes || (await digest(path)) !== entry.sha256) {
      throw new Error(`Release verification failed: ${entry.path}`);
    }
  }
  return manifest;
}

async function build(sourceRoot, releasesRoot, releaseId) {
  const release = safePath(releasesRoot, releaseId);
  await mkdir(release, { recursive: false });
  const files = [];
  for (const path of await allowlist()) {
    const source = safePath(sourceRoot, path);
    const target = safePath(release, path);
    const info = await stat(source);
    if (!info.isFile()) throw new Error(`Allowlisted path is not a file: ${path}`);
    if (path.startsWith('data/')) JSON.parse(await readFile(source, 'utf8'));
    await mkdir(dirname(target), { recursive: true });
    await copyFile(source, target);
    files.push({ path, bytes: info.size, sha256: await digest(source) });
  }
  await writeExclusive(join(release, '.nojekyll'), '');
  await writeExclusive(
    join(release, '_publication/manifest.json'),
    `${JSON.stringify({ schema: 1, release: releaseId, files }, null, 2)}\n`,
  );
  return verifyRelease(releasesRoot, releaseId);
}

async function readState(releasesRoot) {
  try {
    return JSON.parse(await readFile(join(releasesRoot, 'active.json'), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return { current: null, previous: null };
    throw error;
  }
}

async function activate(releasesRoot, releaseId) {
  await verifyRelease(releasesRoot, releaseId);
  const old = await readState(releasesRoot);
  const next = { current: releaseId, previous: old.current };
  const temporary = join(releasesRoot, `active-${process.pid}.tmp`);
  await writeExclusive(temporary, `${JSON.stringify(next, null, 2)}\n`);
  await rename(temporary, join(releasesRoot, 'active.json'));
  return next;
}

async function rollback(releasesRoot) {
  const state = await readState(releasesRoot);
  if (!state.previous) throw new Error('No previous release is available');
  await verifyRelease(releasesRoot, state.previous);
  const next = { current: state.previous, previous: state.current };
  const temporary = join(releasesRoot, `active-${process.pid}.tmp`);
  await writeExclusive(temporary, `${JSON.stringify(next, null, 2)}\n`);
  await rename(temporary, join(releasesRoot, 'active.json'));
  return next;
}

async function main([command, ...args]) {
  let result;
  if (command === 'build' && args.length === 3) result = await build(...args);
  else if (command === 'activate' && args.length === 2) result = await activate(...args);
  else if (command === 'rollback' && args.length === 1) result = await rollback(...args);
  else {
    throw new Error(
      'Usage: pages-artifact-poc.mjs build SOURCE RELEASES RELEASE_ID | activate RELEASES RELEASE_ID | rollback RELEASES',
    );
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}

export { activate, allowlist, build, readState, rollback, verifyRelease };
