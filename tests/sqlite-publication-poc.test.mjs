import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { names, select } from '../scripts/publication/snapshot-relay-poc.mjs';
import { SqlitePublicationStore } from '../scripts/publication/sqlite-publication-poc.mjs';
const now=Date.parse('2026-11-28T14:00:00Z');
const fields={metars:['updated_utc','metars',[]],tafs:['updated_utc','tafs',[]],notams:['retrieved_utc','airports',{}],atis:['retrieved_utc','airports',{}],runways:['generated_utc','airports',{}]};
const fixture=(name,minutes=10,extra={})=>{const [t,k,v]=fields[name];return Buffer.from(JSON.stringify({[t]:new Date(now-minutes*60000).toISOString(),[k]:v,...extra}));};
function manifest(id,selected){return Buffer.from(JSON.stringify({schema:1,release:id,code_commit:'72bb979d41003689e90cfa3dac0ee3ec92579836',sources:Object.fromEntries(names.map(name=>[name,{sha256:selected[name].sha256,retrieved:selected[name].retrieved}])),files:names.map(name=>({path:`data/${name}.json`,sha256:selected[name].sha256}))}));}
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
async function setup(t){
 const dir=await mkdtemp(join(tmpdir(),'spatchin-sqlite-')),file=join(dir,'isolated-publication.db');
 const stores=[];const open=()=>{const x=new SqlitePublicationStore(file);stores.push(x);return x;};
 t.after(async()=>{for(const s of stores){try{s.close();}catch{}}await rm(dir,{recursive:true,force:true});});
 const store=open();for(const name of names)await store.accept(name,fixture(name),now);
 return {store,open};
}
test('transactional store retains bounded source slots across independent connections and restart',async t=>{
 const {store,open}=await setup(t);const other=open();
 for(let n=9;n>=1;n--)await other.accept('notams',fixture('notams',n),now);
 await assert.rejects(store.accept('notams',fixture('notams',2),now),/Older/);
 assert.equal((await store.read('notams',now)).retrieved,new Date(now-60000).toISOString());
 assert.equal(store.db.prepare("SELECT count(*) n FROM snapshots WHERE name='notams'").get().n,2);
 assert.equal(store.get('prior','notams',now).retrieved,new Date(now-120000).toISOString());
});
test('full-size synthetic catalog survives chunked storage',async t=>{
 const {store}=await setup(t);
 // Store a large synthetic snapshot separately from current source fixtures.
 const bytes=await readFile('data/notams.json');
 const next=fixture('notams',1,{airports:{},padding:'x'.repeat(bytes.length)});
 await store.accept('notams',next,now);
 const record=await store.read('notams',now);
 assert.deepEqual(Buffer.from(record.bytes,'base64'),next);
 const chunks=store.db.prepare("SELECT length(data) n FROM chunks WHERE slot='latest' AND name='notams'").all();
 assert.ok(chunks.length>10);assert.ok(chunks.every(x=>x.n<=512*1024));
});
test('pending recovery survives reopen; reject conflicting digest and preserve previous accepted release',async t=>{
 const {store,open}=await setup(t);const one=(await select(store,null,now)).selected;
 const m1=manifest('one',one);store.stage('one',m1,one,now);const recovered=open();
 assert.equal(recovered.status(now).pending.id,'one');
 assert.equal(recovered.status(now).accepted,null);
 assert.throws(()=>recovered.stage('two',manifest('two',one),one,now),/pending/);
 assert.throws(()=>recovered.confirm('one','b'.repeat(64),now),/digest mismatch/);
 recovered.confirm('one',digest(m1),now);
 await recovered.accept('metars',fixture('metars',1),now);
 const two=(await select(recovered,recovered.status(now).checkpoint,now)).selected;
 const m2=manifest('two',two);recovered.stage('two',m2,two,now);recovered.confirm('two',digest(m2),now);
 assert.equal(recovered.status(now).previous.id,'one');
 assert.equal(recovered.status(now).accepted.id,'two');
 assert.equal(recovered.status(now).pending,null);
 assert.throws(()=>recovered.stage('stale',manifest('stale',one),one,now),/Older/);
 assert.equal(recovered.status(now).accepted.id,'two');
});
test('failed transactional stage cannot leave partial pending state',async t=>{
 const {store}=await setup(t);const selected=(await select(store,null,now)).selected;
 const broken={...selected,runways:{...selected.runways,sha256:'f'.repeat(64)}};
 assert.throws(()=>store.stage('broken',manifest('broken',selected),broken,now),/digest/);
 assert.equal(store.status(now).pending,null);
 assert.equal(store.db.prepare("SELECT count(*) n FROM snapshots WHERE slot='pending'").get().n,0);
});

test('manifest cannot authorize different valid snapshot bytes',async t=>{
 const {store}=await setup(t);const one=(await select(store,null,now)).selected;
 await store.accept('notams',fixture('notams',1),now);const two=(await select(store,one,now)).selected;
 assert.throws(()=>store.stage('one',manifest('one',one),two,now),/Manifest source digest/);
 assert.equal(store.status(now).pending,null);
});
