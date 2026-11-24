'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const vm=require('node:vm');
const root=join(__dirname,'..');
const source=name=>readFileSync(join(root,name),'utf8');
const registry=JSON.parse(source('docs/reference/c070-airport-registry.json')).airports;
const now=Date.parse('2026-11-24T15:11:00Z');
class FixedDate extends Date{constructor(...args){super(...(args.length?args:[now]));}static now(){return now;}}
const report=(icao,age=10)=>({icaoId:icao,obsTime:(now-age*60000)/1000,wdir:180,wspd:12,fltCat:'VFR',rawOb:icao+' SYNTHETIC OFFLINE METAR'});
const snapshot=metars=>({updated_utc:new Date(now).toISOString(),metars});
async function load(selected,initial){
 let payload=initial,requests=[],alerts=[],stored=new Map(),elements=new Map();
 if(selected!==undefined)stored.set('spatchin-airports',JSON.stringify(selected));
 const context=vm.createContext({
  Date:FixedDate,console:{error(){},info(){}},alert:msg=>alerts.push(msg),setInterval(){},
  document:{getElementById(id){if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',value:'',addEventListener(event,fn){this[event]=fn;}});return elements.get(id);},querySelectorAll:()=>[]},
  localStorage:{getItem:key=>stored.get(key)??null,setItem:(key,val)=>stored.set(key,val)},
  fetch:async url=>{requests.push(url);assert.match(url,/^\.\/data\//);if(!url.startsWith('./data/metars.json'))return new Promise(()=>{});if(payload instanceof Error)throw payload;return {ok:true,json:async()=>payload};}
 });
 for(const script of ['airport-catalog.js','app.js'])vm.runInContext(source(script),context);
 const run=code=>vm.runInContext(code,context);
 await new Promise(resolve=>setImmediate(resolve));
 return {run,requests,alerts,elements,stored,html:()=>elements.get('cards').innerHTML,
  state:code=>run('metarState(metars['+JSON.stringify(code)+'])'),
  data:code=>JSON.parse(run('JSON.stringify(metars['+JSON.stringify(code)+']||null)')),
  refresh:async next=>{payload=next;await run('refresh()');}};
}
test('browser catalog and mappings match all reviewed registry identities',async()=>{
 const app=await load([],snapshot([]));
 assert.equal(app.run('approvedCatalog.length'),130);
 assert.equal(app.run('Object.keys(airportInfo).length'),130);
 for(const {iata,icao,name} of registry){
  assert.equal(app.run('icao('+JSON.stringify(iata)+')'),icao);
  assert.equal(app.run('airportInfo['+JSON.stringify(iata)+'].name'),name);
 }
 assert.equal(app.requests.filter(x=>x.includes('metars.json')).length,0);
});
test('all 130 stations render in batches of at most 30 using the same shared snapshot',async()=>{
 const all=snapshot(registry.map(a=>report(a.icao)));
 for(let i=0;i<registry.length;i+=30){
  const group=registry.slice(i,i+30);
  const app=await load(group.map(a=>a.iata),all);
  assert.equal(app.run('airports.length'),group.length);
  for(const a of group){
   assert.equal(app.state(a.iata),'current');
   assert.equal(app.data(a.iata).raw,a.icao+' SYNTHETIC OFFLINE METAR');
   assert.ok(app.html().includes('data-airport="'+a.iata+'"'));
   assert.ok(app.html().includes('ids='+a.icao));
  }
  assert.equal(app.requests.filter(x=>x.includes('metars.json')).length,1);
 }
});
test('partial, older, stale, malformed and failed snapshots preserve truthful display',async()=>{
 const app=await load(['IWA','IND','OAK','ABE'],snapshot([report('KIWA'),report('KIND',70)]));
 assert.equal(app.state('IWA'),'current');assert.equal(app.state('IND'),'stale');assert.equal(app.state('OAK'),'unavailable');
 const previous=app.data('IWA');
 await app.refresh(snapshot([null,{...report('KABE'),obsTime:1e40},report('KIWA',30),report('KOAK')]));
 assert.deepEqual(app.data('IWA'),previous);assert.equal(app.state('IND'),'stale');assert.equal(app.state('OAK'),'current');assert.equal(app.state('ABE'),'unavailable');
 assert.match(app.html(),/Runway data pending/);
 await app.refresh(new Error('synthetic offline failure'));
 assert.deepEqual(app.data('IWA'),previous);assert.match(app.html(),/Feed refresh failed; showing retained observation/);
});
test('dashboard limit is 30 total and MEM remains only the removable initial example',async()=>{
 const all=snapshot(registry.map(a=>report(a.icao)));
 const app=await load(registry.slice(0,31).map(a=>a.iata),all);
 assert.equal(app.run('airports.length'),30);
 app.run("document.getElementById('iata')").value=registry[31].iata;
 app.elements.get('add-form').submit({preventDefault(){}});
 assert.equal(app.run('airports.length'),30);assert.deepEqual(app.alerts,['Maximum 30 airports.']);
 const initial=await load(undefined,all);
 assert.equal(initial.run('JSON.stringify(airports)'),'["MEM"]');
 initial.run('airports=[];save()');assert.equal(initial.stored.get('spatchin-airports'),'[]');
 const empty=await load([],all);assert.equal(empty.run('airports.length'),0);
});
