import { test } from 'node:test';
import assert from 'node:assert/strict';
import { makeHandler } from '../worker-core.mjs';
const config = {
 TEAM_DOMAIN:'https://spatchin-test.cloudflareaccess.com',
 POLICY_AUD:'abcdefghijklmnopqrstuvwxyz123456',
 ALLOWED_EMAILS:'allowed@example.com, other@example.com'
};
const req=(path='/',token='signed',method='GET',host='dev.spatchin.com')=>
 new Request('https://'+host+path,{method,headers:token?{'Cf-Access-Jwt-Assertion':token}:{}});
const assets={fetch:async()=>new Response('<h1>Private dashboard</h1>',{headers:{'Content-Type':'text/html'}})};
const env={...config,ASSETS:assets};
const valid=async()=>({email:'allowed@example.com'});
const invalid=async()=>{throw Error('Invalid signature');};

test('missing config and missing Access JWT deny without fetching',async()=>{
 let visited=false;
 const handler=makeHandler(async()=>{visited=true;return {email:'allowed@example.com'}},()=>{visited=true;return new Response('bad')});
 assert.equal((await handler(req(),{ASSETS:assets})).status,403);
 assert.equal((await handler(req('/',null),env)).status,403);
 assert.equal(visited,false);
});
test('invalid signature, unlisted email, or alternate host deny',async()=>{
 assert.equal((await makeHandler(invalid)(req(),env)).status,403);
 assert.equal((await makeHandler(async()=>({email:'attacker@example.com'}))(req(),env)).status,403);
 assert.equal((await makeHandler(valid)(req('/','signed','GET','other.spatchin.com'),env)).status,403);
});
test('valid identity receives private no-store assets',async()=>{
 const r=await makeHandler(valid)(req(),env);
 assert.equal(r.status,200);
 assert.match(await r.text(),/Private dashboard/);
 assert.equal(r.headers.get('Cache-Control'),'private, no-store');
 assert.match(r.headers.get('Content-Security-Policy'),/frame-ancestors 'none'/);
 assert.equal(r.headers.get('X-Robots-Tag'),'noindex, nofollow, noarchive');
});
test('trusted issuer and audience are passed to signature verifier',async()=>{
 let actual=[];
 const handler=makeHandler(async(...args)=>{actual=args;return {email:'ALLOWED@example.com'}});
 assert.equal((await handler(req(),env)).status,200);
 assert.deepEqual(actual,['signed',config.TEAM_DOMAIN,config.POLICY_AUD]);
});
test('allowlisted snapshot proxy never forwards auth headers',async()=>{
 const upstream=[];
 const handler=makeHandler(valid,async(u,options)=>{upstream.push({u,options});return new Response('{"metars":[]}')});
 const good=await handler(req('/data/metars.json?t=123'),env);
 assert.equal(good.status,200);
 assert.equal(good.headers.get('Content-Type'),'application/json; charset=utf-8');
 assert.deepEqual(upstream,[{u:'https://www.spatchin.com/data/metars.json',options:{method:'GET',cache:'no-store',redirect:'error'}}]);
 assert.equal((await handler(req('/data/mystery.json'),env)).status,404);
 assert.equal((await handler(req('/data/notams.json',null),env)).status,403);
 assert.equal(upstream.length,1);
});
test('failed public snapshot returns a generic 503',async()=>{
 const handler=makeHandler(valid,async()=>new Response('private log',{status:502}));
 const response=await handler(req('/data/notams.json'),env);
 assert.equal(response.status,503);
 assert.equal(await response.text(),'Snapshot unavailable');
});
test('unsafe HTTP methods never reach assets or upstream',async()=>{
 let calls=0;
 const handler=makeHandler(valid,async()=>{calls++;return new Response('not safe')});
 assert.equal((await handler(req('/',null,'POST'),env)).status,405);
 assert.equal(calls,0);
});
