import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve,dirname} from 'node:path';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
test('static build uses an explicit dashboard allowlist',async()=>{
 const build=await readFile(resolve(root,'staging/build.mjs'),'utf8');
 assert.match(build,/dashboard\/index\.html/);
 assert.match(build,/base href="\/"/);
 assert.doesNotMatch(build,/readdir|glob|scripts\/capture|\.notam-review/);
});
test('Cloudflare route and signature validation settings cannot be bypassed',async()=>{
 const config=await readFile(resolve(root,'staging/wrangler.toml'),'utf8');
 assert.match(config,/workers_dev = false/);
 assert.match(config,/preview_urls = false/);
 assert.match(config,/run_worker_first = true/);
 assert.match(config,/pattern = "dev\.spatchin\.com"/);
 const policy=await readFile(resolve(root,'staging/verify.mjs'),'utf8');
 assert.match(policy,/jwtVerify\(token, keys/);
 assert.match(policy,/algorithms: \['RS256'\]/);
});
