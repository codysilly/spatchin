// Offline model only. No provider, cloud, GitHub or deployment transport.
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { validate as validateNotams } from '../../notam-snapshots.js';
import { allowlist, build, safeFile } from './pages-artifact-poc.mjs';

const sources = Object.freeze({
  metars: ['updated_utc', 'metars', Array.isArray],
  tafs: ['updated_utc', 'tafs', Array.isArray],
  atis: ['retrieved_utc', 'airports', isObject],
  notams: ['retrieved_utc', 'airports', isObject],
  runways: ['generated_utc', 'airports', isObject],
});
export const names = Object.freeze(Object.keys(sources));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function isObject(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function sourceSpec(name) {
  if (!names.includes(name)) throw Error('Unknown snapshot source');
  return sources[name];
}
function stamp(value) {
  if (typeof value !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw Error('Invalid source time');
  return Date.parse(value);
}
export function candidate(name, bytes, now) {
  const [time, field, shape] = sourceSpec(name);
  if (!Number.isFinite(now)) throw Error('Invalid clock');
  if (!Buffer.isBuffer(bytes) || bytes.length > 10 * 1024 * 1024) throw Error('Invalid snapshot bytes');
  const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  if (!isObject(data) || !shape(data[field])) throw Error('Invalid source envelope');
  if (name === 'notams') validateNotams(data);
  const retrieved = stamp(data[time]);
  if (retrieved > now) throw Error('Future source time');
  return { name, retrieved: data[time], sha256: hash(bytes), bytes: bytes.toString('base64') };
}
export function verify(name, record, now) {
  if (!isObject(record) || record.name !== name || typeof record.bytes !== 'string') throw Error('Invalid relay record');
  const bytes = Buffer.from(record.bytes, 'base64');
  const actual = candidate(name, bytes, now);
  if (actual.bytes !== record.bytes || actual.sha256 !== record.sha256 || actual.retrieved !== record.retrieved) throw Error('Relay digest or metadata mismatch');
  return actual;
}
export function newer(next, old) {
  if (!old) return true;
  const delta = stamp(next.retrieved) - stamp(old.retrieved);
  if (delta < 0) throw Error('Older snapshot');
  if (delta === 0 && next.sha256 !== old.sha256) throw Error('Conflicting snapshot');
  return delta > 0;
}
// Contract: one serialized writer per source. This file adapter models one atomic KV value.
// It does not implement a distributed lock or claim KV read-after-write consistency.
async function readOptional(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
async function atomicJSON(file, value) {
  const temp = `${file}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(value), { flag: 'wx' });
  await rename(temp, file);
}
export class FileRelay {
  constructor(root) { this.root = resolve(root); }
  async accept(name, bytes, now) {
    const next = candidate(name, bytes, now);
    await mkdir(this.root, { recursive: true });
    const file = join(this.root, `${name}.json`);
    const state = await readOptional(file);
    const old = state === null ? null : verify(name, state.current, now);
    if (!newer(next, old)) return false;
    await atomicJSON(file, { current: next, previous: old });
    return true;
  }
  async read(name, now) {
    sourceSpec(name);
    const state = await readOptional(join(this.root, `${name}.json`));
    if (!state) return null;
    return verify(name, state.current, now);
  }
}
// A single publisher selects from independent sources. A stale, absent or corrupt
// relay entry cannot erase an accepted checkpoint or block another healthy source.
export async function select(relay, checkpoint, now) {
  const selected = {}, diagnostics = {};
  for (const name of names) {
    const old = checkpoint?.[name] ? verify(name, checkpoint[name], now) : null;
    try {
      const current = await relay.read(name, now);
      if (!current) throw Error('Missing snapshot');
      const next = verify(name, current, now);
      selected[name] = newer(next, old) ? next : old;
    } catch (error) {
      if (!old) throw Error(`No verified snapshot for ${name}`, { cause: error });
      selected[name] = old;
      diagnostics[name] = 'Retained checkpoint';
    }
  }
  return { selected, diagnostics };
}
// A separate candidate allowlist. Production config is unchanged.
export async function candidatePaths() {
  return [...new Set([...await allowlist(), 'airport-diagrams.js', 'data/airport-diagrams.json'])].sort();
}
export async function assemble(sourceRoot, scratchRoot, releasesRoot, releaseId, selection, now, codeCommit) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$/.test(releaseId)) throw Error('Unsafe release ID');
  if (typeof codeCommit !== 'string' || !/^[a-f0-9]{40}$/.test(codeCommit)) throw Error('Invalid code commit');
  const paths = await candidatePaths();
  const scratch = join(scratchRoot, releaseId);
  await mkdir(scratch); // scratchRoot must already exist and be isolated
  for (const path of paths) {
    const name = /^data\/([a-z]+)\.json$/.exec(path)?.[1];
    const bytes = names.includes(name) ? Buffer.from(verify(name, selection[name], now).bytes, 'base64') : await readFile(await safeFile(sourceRoot, path));
    const target = join(scratch, path);
    await mkdir(resolve(target, '..'), { recursive: true });
    await writeFile(target, bytes, { flag: 'wx' });
  }
  const metadata = Object.fromEntries(names.map(name => [name, { retrieved: selection[name].retrieved, sha256: selection[name].sha256 }]));
  return build(scratch, releasesRoot, releaseId, { paths, metadata, codeCommit });
}
// Call only after verified deployment in a real adapter; this model never deploys.
// The publisher must be serialized, including candidate selection and verification.
export async function recordAccepted(file, selected, now) {
  const old = await readOptional(file);
  const verified = {};
  for (const name of names) {
    verified[name] = verify(name, selected[name], now);
    if (old) newer(verified[name], verify(name, old[name], now));
  }
  await atomicJSON(file, verified);
}
