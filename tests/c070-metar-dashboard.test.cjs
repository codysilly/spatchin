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
test('METAR staleness begins at the 70-minute boundary',async()=>{
 const current=await load(['MEM'],snapshot([report('KMEM',69)]));
 assert.equal(current.state('MEM'),'current');
 assert.match(current.html(),/METAR CURRENT/);
 const stale=await load(['MEM'],snapshot([report('KMEM',70)]));
 assert.equal(stale.state('MEM'),'stale');
 assert.match(stale.html(),/METAR STALE · 70\+ MIN/);
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

test('runway wind components retain heading, rounding and side conventions',async()=>{
 const app=await load([],snapshot([]));
 const components=(direction,speed,bearing)=>JSON.parse(app.run(`JSON.stringify(RunwayWind.components({direction:${direction},speed:${speed}},${bearing}))`));
 assert.deepEqual(components(90,12,90),{head:12,cross:0,side:'—'});
 assert.deepEqual(components(180,12,90),{head:0,cross:12,side:'R'});
 assert.deepEqual(components(0,12,90),{head:0,cross:12,side:'L'});
 assert.deepEqual(components(135,12,90),{head:8,cross:8,side:'R'});
 assert.equal(components(270,12,90).head,-12);
 assert.equal(components(270,12,90).cross,0);
 assert.equal(app.run("RunwayWind.heading('04L')"),40);
 assert.equal(app.run("RunwayWind.heading('36R')"),0);
});
test('runway wind display retains tailwind and crosswind threshold boundaries',async()=>{
 const app=await load([],snapshot([]));
 const values=(direction,speed)=>JSON.parse(app.run(`JSON.stringify(RunwayWind.values({direction:${direction},speed:${speed}},0))`));
 for(const [speed,cls] of [[4,'tailwind-low'],[5,'tailwind-high']]){
  assert.equal(values(180,speed)[0],`<span class="${cls}">${speed} TW</span>`);
 }
 for(const [speed,cls] of [[9,'crosswind-low'],[10,'crosswind-mid'],[14,'crosswind-mid'],[15,'crosswind-high']]){
  assert.equal(values(90,speed)[1],`<span class="${cls}">${speed} R</span>`);
  assert.equal(values(270,speed)[1],`<span class="${cls}">${speed} L</span>`);
 }
});
test('runway wind display preserves gusts and rejects unavailable inputs',async()=>{
 const app=await load([],snapshot([]));
 const values=expr=>JSON.parse(app.run('JSON.stringify(RunwayWind.values('+expr+'))'));
 const gust=values('{direction:90,speed:9,gust:15},0');
 assert.match(gust[1],/crosswind-low">9 R/);
 assert.match(gust[1],/class="gust">G <span class="crosswind-high">15 R/);
 assert.doesNotMatch(values('{direction:90,speed:9,gust:9},0')[1],/class="gust"/);
 for(const expr of ['null,0','{direction:null,speed:12},0','{direction:"VRB",speed:12},0','{direction:90,speed:NaN},0','{direction:90,speed:12},NaN']){
  assert.deepEqual(values(expr),['—','—']);
 }
});
test('runway row uses supplied true bearing for observations, gusts and forecast alternatives',async()=>{
 const app=await load([],snapshot([]));
 app.run('runwayData={airports:{MEM:[{id:"18L",true_heading:90}]}}');
 const row=app.run('runwayRow("MEM","18L",{direction:90,speed:12,gust:16},{alternatives:[{label:"TEMPO",wind:{direction:180,speed:15}},{label:"PROB 30%",wind:null}]})');
 assert.match(row,/FAA NASR true alignment: 90°/);
 assert.match(row,/class="headwind">12 HW/);
 assert.match(row,/class="gust">G <span class="headwind">16 HW/);
 assert.match(row,/TEMPO: <span class="crosswind-high">15 R/);
 assert.match(row,/PROB 30%: —/);
});

test('published runway validator preserves reviewed inventory and rejects invalid snapshots',async()=>{
 const app=await load([],snapshot([]));
 const pairs={...JSON.parse(app.run('JSON.stringify(runwayPairs)')),MEM:['09/27','18L/36R','18C/36C','18R/36L']};
 const airports=Object.fromEntries(Object.entries(pairs).map(([code,list])=>[code,list.flatMap(pair=>pair.split('/').map(id=>({id,pair,true_heading:Number(id.slice(0,2))*10%360})))]));
 const fixture={heading_reference:'TRUE',effective_date:'2026-11-01',airports};
 const validate=value=>app.run('PublishedSnapshots.runways('+JSON.stringify(value)+',approvedCatalog)');
 assert.deepEqual(JSON.parse(JSON.stringify(validate(fixture))),fixture);
 const copy=()=>JSON.parse(JSON.stringify(fixture));
 const invalidHeading=copy();invalidHeading.airports.MEM[0].true_heading=360;
 assert.throws(()=>validate(invalidHeading),/Invalid MEM runway end/);
 const missing=copy();delete missing.airports.MEM;
 assert.throws(()=>validate(missing),/Missing verified MEM runway ends/);
 const badPair=copy();badPair.airports.MEM[0].pair='09/01';
 assert.throws(()=>validate(badPair),/Incomplete MEM runway pair/);
 const badCoverage=copy();badCoverage.airport_coverage={};
 assert.throws(()=>validate(badCoverage),/Invalid C070 runway coverage/);
 assert.equal(app.run('runwayData'),null);
});
test('published TAF selection retains newer and richer reports and rejects invalid publications',async()=>{
 const app=await load([],snapshot([]));
 app.run(source('taf-reader.js'));
 const issue=minutes=>new Date(now-minutes*60000).toISOString();
 const report=(icaoId,age,groups=1)=>({icaoId,issueTime:issue(age),validTimeFrom:Math.floor((now-3600000)/1000),validTimeTo:Math.floor((now+3600000)/1000),rawTAF:'SYNTHETIC '+icaoId+' '+age+' '+groups,fcsts:Array.from({length:groups},()=>({}))});
 const current=report('KMEM',30,2),other=report('KORD',30);
 const previous={tafs:[current,other],updated_utc:issue(5)};
 const select=(tafs,updated_utc=issue(1))=>JSON.parse(app.run('JSON.stringify(PublishedSnapshots.tafs('+JSON.stringify({tafs,updated_utc})+','+JSON.stringify(previous)+',airportInfo,TafReader,Date.now))'));
 const retained=select([report('KMEM',45,3),report('KMEM',30,1)]);
 assert.deepEqual(retained.tafs,[current,other]);
 const richer=report('KMEM',30,3),newer=report('KMEM',10,1);
 assert.deepEqual(select([richer]).tafs,[richer,other]);
 assert.deepEqual(select([richer,newer]).tafs,[newer,other]);
 assert.throws(()=>select([report('ZZZZ',15)]),/No valid TAFs/);
 assert.throws(()=>select([newer],issue(-6)),/Invalid TAF publication time/);
 assert.throws(()=>select(null),/Invalid published TAF snapshot/);
 assert.equal(app.run('tafData'),null);
});
