// Offline protocol proof only. No production key, endpoint, scheduler or app wiring.
import { NotamSnapshots } from '../../notam-snapshots.js';

const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const hex = /^[a-f0-9]{64}$/;
const airport = /^[A-Z0-9]{3,4}$/;
const keyIdPattern = /^[a-zA-Z0-9_-]{1,64}$/;
const bytes = value => encoder.encode(JSON.stringify(value));
const parse = value => JSON.parse(decoder.decode(value));
const own = (obj, key) => Object.hasOwn(obj, key);
const record = obj => obj !== null && typeof obj === 'object' && !Array.isArray(obj);
const validTime = value => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const validGeneration = value => Number.isSafeInteger(value) && value > 0;
const pathFor = (kind, digest) => `${kind}/${digest}.json`;
const toHex = value => Array.from(new Uint8Array(value), n => n.toString(16).padStart(2, '0')).join('');
async function digest(value) { return toHex(await crypto.subtle.digest('SHA-256', value)); }
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (record(value)) return Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])]));
  return value;
}
const encode = value => bytes(canonical(value));

export async function buildShards(snapshot, { generation, keyId, privateKey, allowSynthetic = false }) {
  NotamSnapshots.validate(snapshot, { allowSynthetic });
  if (!validGeneration(generation) || typeof keyId !== 'string' || !keyIdPattern.test(keyId)) throw Error('Invalid generation or key ID');
  const { airports, ...metadata } = snapshot;
  const files = new Map();
  const shards = {};
  for (const [code, entry] of Object.entries(airports)) {
    const body = encode(entry); // Preserve ALL original fields, including record retrieval times.
    const hash = await digest(body);
    files.set(pathFor('shards', hash), body);
    shards[code] = { hash, bytes: body.byteLength, count: entry.notices.length };
  }
  const payload = decoder.decode(encode({ protocol: 1, generation, keyId, metadata, shards }));
  const signature = toHex(await crypto.subtle.sign('Ed25519', privateKey, encoder.encode(payload)));
  const index = encode({ payload, signature });
  const root = await digest(index);
  files.set(pathFor('indexes', root), index);
  files.set('head.json', encode({ protocol: 1, generation, root }));
  return files;
}

async function bounded(response, limit) {
  if (!response.body) throw Error('Missing response body');
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw Error('Response too large');
      chunks.push(value);
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
  const result = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
  return result;
}

export function createShardedReader({ baseURL, trustedKeys, fetchFn = globalThis.fetch, now = Date.now, allowSynthetic = false, manualConditional = false }) {
  const base = new URL(baseURL);
  if (base.protocol !== 'https:' || base.username || base.password || base.search || base.hash || !base.pathname.endsWith('/')) throw Error('Explicit HTTPS directory required');
  let accepted = null, lastGood = null, etag = null, cached = new Map(), pending = false;
  const keys = new Map(trustedKeys);
  async function get(path, limit, conditional = false, signal) {
    const response = await fetchFn(new URL(path, base).href, { redirect: 'error', credentials: 'omit', cache: conditional ? 'no-cache' : 'default', ...(conditional && manualConditional && etag ? { headers: { 'If-None-Match': etag } } : {}), signal });
    if (conditional && response.status === 304 && accepted && etag) return { unchanged: true };
    if (!response.ok) throw Error('Publication unavailable');
    return { body: await bounded(response, limit), etag: response.headers.get('ETag') };
  }
  async function refresh(selected, { signal } = {}) {
    if (pending) throw Error('Refresh already in progress');
    if (!Array.isArray(selected) || selected.length > 30 || new Set(selected).size !== selected.length || !selected.every(code => typeof code === 'string' && airport.test(code))) throw Error('Invalid airport selection');
    pending = true;
    try {
      const response = await get('head.json', 1024, true, signal);
      let next = accepted;
      if (!response.unchanged) {
        const head = parse(response.body);
        if (!record(head) || head.protocol !== 1 || !validGeneration(head.generation) || typeof head.root !== 'string' || !hex.test(head.root)) throw Error('Invalid head');
        if (accepted && (head.generation < accepted.generation || (head.generation === accepted.generation && head.root !== accepted.root))) throw Error('Replay or conflicting generation');
        if (!accepted || head.root !== accepted.root) {
          const index = (await get(pathFor('indexes', head.root), 262144, false, signal)).body;
          if (await digest(index) !== head.root) throw Error('Index digest mismatch');
          const envelope = parse(index);
          if (!record(envelope) || typeof envelope.payload !== 'string' || typeof envelope.signature !== 'string' || !/^[a-f0-9]{128}$/.test(envelope.signature)) throw Error('Invalid signature envelope');
          const body = JSON.parse(envelope.payload);
          if (!record(body) || body.protocol !== 1 || body.generation !== head.generation || typeof body.keyId !== 'string' || !keyIdPattern.test(body.keyId) || !keys.has(body.keyId)) throw Error('Untrusted index');
          const signature = Uint8Array.from(envelope.signature.match(/../g), pair => parseInt(pair, 16));
          if (!await crypto.subtle.verify('Ed25519', keys.get(body.keyId), signature, encoder.encode(envelope.payload))) throw Error('Signature rejected');
          if (!record(body.metadata) || own(body.metadata, 'airports') || !validTime(body.metadata.retrieved_utc) || Date.parse(body.metadata.retrieved_utc) > now() || (accepted && Date.parse(body.metadata.retrieved_utc) <= Date.parse(accepted.metadata.retrieved_utc))) throw Error('Invalid retrieval chronology');
          if (!record(body.shards) || Object.keys(body.shards).length > 200 || !Object.entries(body.shards).every(([code, entry]) => airport.test(code) && record(entry) && typeof entry.hash === 'string' && hex.test(entry.hash) && Number.isSafeInteger(entry.bytes) && entry.bytes > 0 && entry.bytes <= 2_000_000 && Number.isSafeInteger(entry.count) && entry.count >= 0)) throw Error('Invalid shard catalog');
          NotamSnapshots.validate({ ...body.metadata, airports: {} }, { allowSynthetic });
          next = { ...body, root: head.root };
        }
      }
      const nextCache = new Map(), airports = {};
      for (const code of selected) {
        if (!own(next.shards, code)) throw Error('Selected airport missing from index');
        const entry = next.shards[code];
        let shard = cached.get(entry.hash);
        if (!shard) {
          const raw = (await get(pathFor('shards', entry.hash), entry.bytes, false, signal)).body;
          if (raw.byteLength !== entry.bytes || await digest(raw) !== entry.hash) throw Error('Shard digest mismatch');
          shard = parse(raw);
        }
        if (!record(shard) || !Array.isArray(shard.notices) || shard.notices.length !== entry.count) throw Error('Shard count mismatch');
        airports[code] = shard;
        nextCache.set(entry.hash, shard);
      }
      const snapshot = NotamSnapshots.validate({ ...next.metadata, airports }, { allowSynthetic });
      if (signal?.aborted) throw Error('Refresh aborted');
      accepted = next; cached = nextCache; lastGood = { generation: next.generation, snapshot };
      if (!response.unchanged) etag = response.etag;
      return structuredClone(lastGood);
    } finally { pending = false; }
  }
  return { refresh, read: () => structuredClone(lastGood), acceptedGeneration: () => accepted?.generation ?? null };
}
