import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildShards, createShardedReader } from '../scripts/publication/sharded-notam-poc.mjs';
const keys = await crypto.subtle.generateKey('Ed25519', false, ['sign', 'verify']);
const bad = await crypto.subtle.generateKey('Ed25519', false, ['sign', 'verify']);
const data = (time, text = 'SYNTHETIC A') => ({ synthetic: true, retrieved_utc: time, publication: { coverage: 'UNKNOWN' }, airports: { KMEM: { completeness: 'UNKNOWN', notices: [{ text, id: 'A', retrieved_utc: '2026-11-28T12:00:00Z', effectiveStart: '2026-11-28T11:00:00Z' }] }, KORD: { notices: [{ text: 'SYNTHETIC B', id: 'B' }] } } });
const a = data('2026-11-28T12:00:00Z'), b = data('2026-11-28T12:10:00Z', 'SYNTHETIC A changed');
const build = (snapshot, generation, privateKey = keys.privateKey) => buildShards(snapshot, { generation, keyId: 'test', privateKey, allowSynthetic: true });
const fixture = async () => {
  const one = await build(a, 1), two = await build(b, 2);
  let files = one, version = '1'; const calls = [];
  const reader = createShardedReader({ baseURL: 'https://example.invalid/data/', trustedKeys: new Map([['test', keys.publicKey]]), allowSynthetic: true, manualConditional: true, now: () => Date.parse('2026-11-28T13:00:00Z'), fetchFn: async (url, options) => {
    const path = new URL(url).pathname.slice(6); calls.push(path);
    assert.equal(options.credentials, 'omit'); assert.equal(options.redirect, 'error');
    if (path === 'head.json' && options.headers?.['If-None-Match'] === version) return new Response(null, { status: 304 });
    return files.has(path) ? new Response(files.get(path), { headers: { ETag: version } }) : new Response(null, { status: 404 });
  } });
  return { one, two, calls, reader, switchTo: (next, tag) => { files = next; version = tag; } };
};
test('selected shards, 304, and unchanged hashes reuse verified bytes', async () => {
  const f = await fixture();
  const first = await f.reader.refresh(['KMEM','KORD']); assert.deepEqual(first.snapshot, a);
  assert.equal(f.calls.length, 4);
  await f.reader.refresh(['KMEM','KORD']); assert.equal(f.calls.length, 5);
  f.switchTo(f.two,'2'); const next = await f.reader.refresh(['KMEM','KORD']);
  assert.deepEqual(next.snapshot,b); assert.equal(f.calls.length, 8);
});
test('adding an airport after 304 loads only that airport', async () => {
  const f = await fixture(); await f.reader.refresh(['KMEM']); assert.equal(f.calls.length,3);
  const result = await f.reader.refresh(['KMEM','KORD']); assert.equal(f.calls.length,5); assert.deepEqual(result.snapshot,a);
});
test('bad signature, missing shard and replay preserve prior generation', async () => {
  const f = await fixture(); await f.reader.refresh(['KMEM']);
  f.switchTo(await build(b,2,bad.privateKey),'bad'); await assert.rejects(f.reader.refresh(['KMEM']),/Signature rejected/);
  const broken = new Map(f.two); for(const path of broken.keys()) if(path.startsWith('shards/')) broken.delete(path);
  f.switchTo(broken,'broken'); await assert.rejects(f.reader.refresh(['KMEM']),/unavailable/); assert.equal(f.reader.acceptedGeneration(),1); assert.deepEqual(f.reader.read().snapshot.airports.KMEM,a.airports.KMEM);
  f.switchTo(f.two,'2'); await f.reader.refresh(['KMEM']); f.switchTo(f.one,'1'); await assert.rejects(f.reader.refresh(['KMEM']),/Replay/); assert.equal(f.reader.acceptedGeneration(),2);
});
test('corrupt shard and index reject without accepting candidate', async () => {
  const f = await fixture(); const damaged = new Map(f.one);
  const path = [...damaged.keys()].find(k=>k.startsWith('indexes/')); damaged.set(path,new TextEncoder().encode('{}'));
  f.switchTo(damaged,'x'); await assert.rejects(f.reader.refresh(['KMEM']),/Index digest/);
  const shards = new Map(f.one); for(const [k,v] of shards) if(k.startsWith('shards/')) { const copy = v.slice(); copy[0]^=1; shards.set(k,copy); }
  f.switchTo(shards,'y'); await assert.rejects(f.reader.refresh(['KMEM']),/Shard digest/); assert.equal(f.reader.acceptedGeneration(),null);
});
test('future retrieval and same-generation conflict reject', async()=>{
  const f=await fixture(); await f.reader.refresh(['KMEM']); f.switchTo(await build(b,1),'conflict'); await assert.rejects(f.reader.refresh(['KMEM']),/conflicting/);
  f.switchTo(await build(data('2026-11-28T14:00:00Z'),2),'future'); await assert.rejects(f.reader.refresh(['KMEM']),/chronology/);
});
test('synthetic data rejected by default; selection constrained; no silent missing airport', async()=>{
  await assert.rejects(buildShards(a,{generation:1,keyId:'test',privateKey:keys.privateKey}),/Synthetic/);
  const f=await fixture(); await assert.rejects(f.reader.refresh(['../x']),/selection/); await assert.rejects(f.reader.refresh(['KXXX']),/missing/); assert.equal(f.reader.acceptedGeneration(),null);
});
test('default browser-managed revalidation sends no custom header or cookies', async () => {
  const files=await build(a,1); const calls=[];
  const reader=createShardedReader({baseURL:'https://example.invalid/data/',trustedKeys:new Map([['test',keys.publicKey]]),allowSynthetic:true,now:()=>Date.parse('2026-11-28T13:00:00Z'),fetchFn:async(url,options)=>{
    const path=new URL(url).pathname.slice(6); calls.push(path);
    assert.equal(options.headers,undefined); assert.equal(options.credentials,'omit');
    if(path==='head.json') assert.equal(options.cache,'no-cache');
    return new Response(files.get(path),{headers:{ETag:'1'}});
  }});
  await reader.refresh(['KMEM']); await reader.refresh(['KMEM']); assert.equal(calls.length,4);
});
