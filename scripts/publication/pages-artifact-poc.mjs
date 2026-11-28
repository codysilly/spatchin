import { createHash } from 'node:crypto';
import { copyFile, lstat, mkdir, open, readFile, readdir, rename } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const allowlistPath = join(repositoryRoot, 'config/pages-publication-allowlist.json');

function safePath(root, path) {
  if (typeof path !== 'string' || !/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(path) || path.split('/').some(part => part === '.' || part === '..')) {
    throw new Error(`Unsafe publication path: ${path}`);
  }
  const target = resolve(root, path);
  if (!target.startsWith(`${resolve(root)}${sep}`)) throw new Error(`Path escapes root: ${path}`);
  return target;
}

function releasePath(root, id) {
  if (typeof id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(id)) throw new Error('Invalid release ID');
  return safePath(root, id);
}

async function safeFile(root, path) {
  const target = safePath(root, path);
  let current = resolve(root);
  const base = await lstat(current);
  if (!base.isDirectory() || base.isSymbolicLink()) throw new Error('Unsafe publication root');
  for (const part of path.split('/')) {
    current = join(current, part);
    const info = await lstat(current);
    if (info.isSymbolicLink() || (current !== target && !info.isDirectory()) || (current === target && (!info.isFile() || info.nlink !== 1))) throw new Error(`Unsafe publication file: ${path}`);
  }
  return target;
}

function validatePaths(paths) {
  if (!Array.isArray(paths) || !paths.length || new Set(paths).size !== paths.length) throw new Error('Publication paths must contain unique files');
  for (const path of paths) {
    safePath(repositoryRoot, path);
    if (path === '.nojekyll' || path.startsWith('_publication/')) throw new Error('Reserved publication path');
  }
  return [...paths].sort();
}

async function treeFiles(root, dir = root) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const child = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...await treeFiles(root, child));
    else {
      const path = relative(root, child).split(sep).join('/');
      await safeFile(root, path);
      files.push(path);
    }
  }
  return files.sort();
}

async function allowlist() {
  const parsed = JSON.parse(await readFile(allowlistPath, 'utf8'));
  return validatePaths(parsed.files);
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

async function verifyRelease(releasesRoot, releaseId, expectedPaths) {
  const release = releasePath(releasesRoot, releaseId);
  const manifestPath = await safeFile(release, '_publication/manifest.json');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const paths = validatePaths(expectedPaths ?? await allowlist());
  if (manifest.schema !== 1 || manifest.release !== releaseId || !Array.isArray(manifest.files)) throw new Error('Invalid release manifest');
  if (JSON.stringify(validatePaths(manifest.files.map(entry => entry.path))) !== JSON.stringify(paths)) throw new Error('Release allowlist mismatch');
  if (JSON.stringify(await treeFiles(release)) !== JSON.stringify([...paths, '.nojekyll', '_publication/manifest.json'].sort())) throw new Error('Release file set mismatch');
  for (const entry of manifest.files) {
    const path = await safeFile(release, entry.path);
    const bytes = await readFile(path);
    if (bytes.length !== entry.bytes || createHash('sha256').update(bytes).digest('hex') !== entry.sha256) throw new Error(`Release verification failed: ${entry.path}`);
  }
  if (manifest.sources) {
    for (const [name, entry] of Object.entries(manifest.sources)) {
      if (manifest.files.find(file => file.path === `data/${name}.json`)?.sha256 !== entry.sha256) throw new Error('Source manifest digest mismatch');
    }
  }
  return manifest;
}

async function build(sourceRoot, releasesRoot, releaseId, options = {}) {
  const release = releasePath(releasesRoot, releaseId);
  const paths = validatePaths(options.paths ?? await allowlist());
  await mkdir(release, { recursive: false });
  const files = [];
  for (const path of paths) {
    const source = await safeFile(sourceRoot, path);
    const target = safePath(release, path);
    await mkdir(dirname(target), { recursive: true });
    await copyFile(source, target);
    const bytes = await readFile(target);
    if (path.startsWith('data/')) JSON.parse(bytes.toString('utf8'));
    files.push({ path, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') });
  }
  await writeExclusive(join(release, '.nojekyll'), '');
  await writeExclusive(
    join(release, '_publication/manifest.json'),
    `${JSON.stringify({ schema: 1, release: releaseId, files, ...(options.metadata ? { sources: options.metadata, code_commit: options.codeCommit } : {}) }, null, 2)}\n`,
  );
  return verifyRelease(releasesRoot, releaseId, paths);
}

async function readState(releasesRoot) {
  try {
    return JSON.parse(await readFile(join(releasesRoot, 'active.json'), 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') return { current: null, previous: null };
    throw error;
  }
}

async function activate(releasesRoot, releaseId, expectedPaths) {
  await verifyRelease(releasesRoot, releaseId, expectedPaths);
  const old = await readState(releasesRoot);
  const next = { current: releaseId, previous: old.current };
  const temporary = join(releasesRoot, `active-${process.pid}.tmp`);
  await writeExclusive(temporary, `${JSON.stringify(next, null, 2)}\n`);
  await rename(temporary, join(releasesRoot, 'active.json'));
  return next;
}

async function rollback(releasesRoot, expectedPaths) {
  const state = await readState(releasesRoot);
  if (!state.previous) throw new Error('No previous release is available');
  await verifyRelease(releasesRoot, state.previous, expectedPaths);
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

export { activate, allowlist, build, readState, rollback, safeFile, verifyRelease };
