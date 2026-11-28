import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, writeFile, symlink, rm, cp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { FileRelay, candidate, select, assemble, candidatePaths, recordAccepted } from '../scripts/publication/snapshot-relay-poc.mjs';
import { activate, verifyRelease, readState, rollback } from '../scripts/publication/pages-artifact-poc.mjs';

const commit='72bb979d41003689e90cfa3dac0ee3ec92579836';
const now = Date.parse('2026-11-28T14:00:00Z');
const spec = {metars:['updated_utc','metars',[]],tafs:['updated_utc','tafs',[]],atis:['retrieved_utc','airports',{}],notams:['retrieved_utc','airports',{}],runways:['generated_utc','airports',{}]};
const names = Object.keys(spec);
function fixture(name, minutes = 10, extra = {}) {
  const [time, field, value] = spec[name];
  return Buffer.from(JSON.stringify({ [time]: new Date(now-minutes*60000).toISOString(), [field]: value, ...extra }));
}
async function setup(t) {
  const root = await mkdtemp(join(tmpdir(),'spatchin-relay-'));
  t.after(() => rm(root,{recursive:true,force:true}));
  const relay = new FileRelay(join(root,'relay'));
  for (const name of names) await relay.accept(name,fixture(name),now);
  return {root,relay};
}
test('per-source last-good survives restart; equal input is idempotent', async t => {
  const {root,relay}=await setup(t);
  assert.equal(await relay.accept('notams',fixture('notams'),now),false);
  await relay.accept('notams',fixture('notams',5),now);
  const restarted=new FileRelay(join(root,'relay'));
  assert.equal((await restarted.read('notams',now)).retrieved,new Date(now-5*60000).toISOString());
  const state=JSON.parse(await readFile(join(root,'relay/notams.json'),'utf8'));
  assert.equal(state.previous.retrieved,new Date(now-10*60000).toISOString());
  assert.equal((await restarted.read('metars',now)).retrieved,state.previous.retrieved);
});
test('reject older, same-time different, future, invalid JSON and unknown source', async t => {
  const {relay}=await setup(t);
  await assert.rejects(relay.accept('notams',fixture('notams',11),now),/Older/);
  await assert.rejects(relay.accept('notams',fixture('notams',10,{other:1}),now),/Conflicting/);
  await assert.rejects(relay.accept('notams',fixture('notams',-1),now),/Future/);
  await assert.rejects(relay.accept('notams',Buffer.from('{'),now));
  await assert.rejects(relay.accept('../private',Buffer.from('{}'),now),/Unknown/);
  await assert.rejects(relay.accept('notams',fixture('notams',5,{synthetic:true}),now),/Synthetic/);
  await assert.rejects(relay.accept('metars',fixture('metars',5,{metars:{}}),now),/envelope/);
  assert.equal((await relay.read('notams',now)).sha256,candidate('notams',fixture('notams'),now).sha256);
});
test('corrupt, missing and delayed entries retain independent checkpoint; no cold-start fabrication', async t => {
  const {root,relay}=await setup(t);
  const {selected:old}=await select(relay,null,now);
  await relay.accept('metars',fixture('metars',5),now);
  await writeFile(join(root,'relay/notams.json'),'{');
  await rm(join(root,'relay/atis.json'));
  const result=await select(relay,old,now);
  assert.equal(result.selected.notams.sha256,old.notams.sha256);
  assert.equal(result.selected.atis.sha256,old.atis.sha256);
  assert.notEqual(result.selected.metars.sha256,old.metars.sha256);
  assert.deepEqual(Object.keys(result.diagnostics).sort(),['atis','notams']);
  await assert.rejects(select(relay,null,now),/No verified snapshot/);
  const lagging={read:async name=>name==='metars'?old.metars:old[name]};
  const delayed=await select(lagging,result.selected,now);
  assert.equal(delayed.selected.metars.sha256,result.selected.metars.sha256);
});
test('checkpoint rejects a superseded publisher and detects digest corruption', async t => {
  const {root,relay}=await setup(t);
  const {selected:old}=await select(relay,null,now);
  const file=join(root,'accepted.json');
  await recordAccepted(file,old,now);
  await relay.accept('tafs',fixture('tafs',1),now);
  const {selected:next}=await select(relay,old,now);
  await recordAccepted(file,next,now);
  await assert.rejects(recordAccepted(file,old,now),/Older/);
  await assert.rejects(recordAccepted(file,{...next,tafs:{...next.tafs,sha256:'0'.repeat(64)}},now),/digest/);
  assert.equal(JSON.parse(await readFile(file,'utf8')).tafs.sha256,next.tafs.sha256);
});
test('assemble real pinned runtime shell with synthetic inputs; keep digest, source time, diagrams and rollback',async t=>{
  const {root,relay}=await setup(t);
  const scratch=join(root,'scratch'), releases=join(root,'releases');
  await mkdir(scratch);await mkdir(releases);
  const {selected:one}=await select(relay,null,now);
  const manifest=await assemble(process.cwd(),scratch,releases,'one',one,now,commit);
  assert.deepEqual(manifest.files.map(x=>x.path).sort(),await candidatePaths());
  assert.equal(manifest.sources.notams.sha256,one.notams.sha256);
  assert.equal(manifest.code_commit,commit);
  assert.equal(manifest.sources.notams.retrieved,one.notams.retrieved);
  assert.deepEqual(await readFile(join(releases,'one/data/notams.json')),fixture('notams'));
  await activate(releases,'one',await candidatePaths());
  await relay.accept('atis',fixture('atis',2),now);
  const {selected:two}=await select(relay,one,now);
  await assemble(process.cwd(),scratch,releases,'two',two,now,commit);
  await activate(releases,'two',await candidatePaths());
  await rollback(releases,await candidatePaths());
  assert.equal((await readState(releases)).current,'one');
  await writeFile(join(releases,'two/data/atis.json'),'{}');
  await assert.rejects(verifyRelease(releases,'two',await candidatePaths()),/verification failed/);
  await assert.rejects(assemble(process.cwd(),scratch,releases,'../escape',one,now,commit),/Unsafe release/);
});
test('candidate excludes engineering files and covers literal runtime imports, fetches and branding', async ()=>{
  const files=new Set(await candidatePaths());
  for(const path of files){
    if(!/\.(html|js|css)$/.test(path))continue;
    const source=await readFile(path,'utf8');
    const refs=[...source.matchAll(/(?:\b(?:src|href)=["']|\b(?:from\s*|import\s*\(\s*|fetch\(\s*|new URL\(\s*)["'`]|url\(\s*["']?)(\.?\/?(?:data\/|assets\/)[a-zA-Z0-9_.\/-]+|\.?\/?[a-zA-Z0-9_.-]+\.(?:js|css))/g)].map(m=>m[1].replace(/^\.\//,''));
    for(const ref of refs)assert.ok(files.has(ref),`${path} references missing ${ref}`);
  }
  assert.ok(files.has('airport-diagrams.js'));assert.ok(files.has('data/airport-diagrams.json'));
  assert.ok(!files.has('AGENTS.md'));
});
test('reject linked shell input (POSIX only)',{skip:process.platform==='win32'},async t=>{
  const {root,relay}=await setup(t);const source=join(root,'source'),scratch=join(root,'scratch'),releases=join(root,'releases');
  await mkdir(source);await mkdir(scratch);await mkdir(releases);
  await cp('CNAME',join(source,'private'));await symlink(join(source,'private'),join(source,'CNAME'));
  const {selected}=await select(relay,null,now);
  await assert.rejects(assemble(source,scratch,releases,'one',selected,now,commit),/Unsafe publication file/);
});

test('release verification rejects undeclared files and incomplete manifests',async t=>{
  const {root,relay}=await setup(t);
  const scratch=join(root,'scratch'),releases=join(root,'releases');
  await mkdir(scratch);await mkdir(releases);
  const {selected}=await select(relay,null,now);
  const manifest=await assemble(process.cwd(),scratch,releases,'one',selected,now,commit);
  const paths=await candidatePaths();
  const extra=join(releases,'one/unlisted.txt');
  await writeFile(extra,'not part of the release');
  await assert.rejects(verifyRelease(releases,'one',paths),/file set mismatch/);
  await rm(extra);
  manifest.files.pop();
  await writeFile(join(releases,'one/_publication/manifest.json'),JSON.stringify(manifest));
  await assert.rejects(verifyRelease(releases,'one',paths),/allowlist mismatch/);
});
