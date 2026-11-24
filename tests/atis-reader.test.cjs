'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');

const app=readFileSync('app.js','utf8');
const advertisedStart=app.indexOf('function advertised(text,kind){');
const atisEnd=app.indexOf('\nfunction tafBlock(code){',advertisedStart);
const utcStart=app.indexOf('function utc(t){');
const utcEnd=app.indexOf('\nconst flightCategories=',utcStart);
assert.ok(advertisedStart>=0&&atisEnd>advertisedStart&&utcStart>=0&&utcEnd>utcStart);
const context=vm.createContext({Date,Number,encodeURIComponent,
 esc:value=>String(value).replace(/[&<>"']/g,character=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character])),
 icao:value=>value,atisData:null,atisRetrieved:null});
new vm.Script(app.slice(advertisedStart,atisEnd)+'\n'+app.slice(utcStart,utcEnd),{filename:'atis-reader.js'}).runInContext(context);

const now=Date.now();
const stamp=minutesAgo=>new Date(now-minutesAgo*60000).toISOString();
const report=(type,minutesAgo,code,time,datis)=>({airport:'KMEM',type,code,time,updatedAt:stamp(minutesAgo),datis});
const combined=(minutesAgo,code='C',time='1200')=>report('combined',minutesAgo,code,time,'ARR EXP RWY 18R. DEP EXP RWYS 36L. RAW COMBINED');
const arrival=(minutesAgo,code='A',time='1201')=>report('arr',minutesAgo,code,time,'ARR EXP RWY 09. RAW ARRIVAL');
const departure=(minutesAgo,code='D',time='1202')=>report('dep',minutesAgo,code,time,'DEP EXP RWYS 27. RAW DEPARTURE');
function render(reports,retrieved=stamp(1)){
 context.atisData={airports:{KMEM:reports}};context.atisRetrieved=retrieved;
 return vm.runInContext("atisBlock('KMEM')",context);
}

test('fresh arrival cannot conceal stale departure and the inverse is independent',()=>{
 let html=render([arrival(5),departure(60)]);
 assert.match(html,/↘ LANDING · CURRENT/);assert.match(html,/↗ DEPARTING · STALE/);
 html=render([arrival(60),departure(5)]);
 assert.match(html,/↘ LANDING · STALE/);assert.match(html,/↗ DEPARTING · CURRENT/);
});

test('both stale, missing sides, and stale retrieval are distinguished',()=>{
 let html=render([arrival(60),departure(70)]);
 assert.match(html,/↘ LANDING · STALE/);assert.match(html,/↗ DEPARTING · STALE/);
 html=render([arrival(5)]);assert.match(html,/↗ DEPARTING · UNAVAILABLE/);
 html=render([arrival(5),departure(6)],stamp(60));
 assert.match(html,/↘ LANDING · STALE/);assert.match(html,/↗ DEPARTING · STALE/);
});

test('newer combined and newer split reports win by source timestamp',()=>{
 let html=render([combined(5,'N','1300'),arrival(20),departure(15)]);
 assert.match(html,/INFO N · ISSUED <strong>1300Z/);assert.match(html,/>18R</);assert.match(html,/>36L</);
 html=render([combined(30,'O','1100'),arrival(5,'A','1301'),departure(4,'D','1302')]);
 assert.match(html,/INFO D · ISSUED <strong>1302Z/);assert.match(html,/>09</);assert.match(html,/>27</);
});

test('invalid source timestamps are unavailable and never replaced by retrieval time',()=>{
 const invalid=arrival(5);delete invalid.updatedAt;
 const html=render([invalid]);
 assert.match(html,/↘ LANDING · UNAVAILABLE/);assert.match(html,/INFO — · ISSUED <strong>—/);
 assert.match(html,/Landing source update: —/);
});

test('original issue times, raw text, timestamps, and source link remain visible',()=>{
 const arr=arrival(5,'Q','2359');
 const html=render([arr]);
 assert.match(html,/INFO Q · ISSUED <strong>2359Z/);
 assert.match(html,/2359Z<\/strong><\/p><p class="atis-raw">ARR EXP RWY 09\. RAW ARRIVAL/);
 assert.match(html,new RegExp(arr.updatedAt.slice(0,16).replace('T',' ')+"Z"));
 assert.match(html,/href="https:\/\/atis\.info\/api\/KMEM"/);
});

test('unsupported report content is preserved but does not infer runway use',()=>{
 const vague=report('arr',2,'V','1210','RWY 18R MENTIONED WITHOUT AN ARRIVAL CLAUSE');
 const html=render([vague]);
 assert.match(html,/↘ LANDING · UNAVAILABLE/);assert.match(html,/RWY 18R MENTIONED/);
 assert.doesNotMatch(html,/class="atis-value">18R/);
});

test('newer report without a runway clause supersedes older runway text',()=>{
 const vagueArr=report('arr',2,'V','1210','NO EXPLICIT RUNWAY CONFIGURATION');
 const vagueDep=report('dep',2,'V','1210','NO EXPLICIT RUNWAY CONFIGURATION');
 let html=render([combined(10),vagueArr]);
 assert.match(html,/↘ LANDING · UNAVAILABLE/);
 assert.doesNotMatch(html,/class="atis-value">18R/);
 assert.match(html,/↗ DEPARTING · CURRENT/);assert.match(html,/>36L</);
 assert.match(html,/RAW COMBINED/);
 html=render([combined(10),vagueDep]);
 assert.match(html,/↗ DEPARTING · UNAVAILABLE/);
 assert.doesNotMatch(html,/class="atis-value">36L/);
 assert.match(html,/↘ LANDING · CURRENT/);
 const vagueCombined=report('combined',1,'N','1211','NO EXPLICIT RUNWAY CONFIGURATION');
 html=render([arrival(5),departure(5),vagueCombined]);
 assert.match(html,/↘ LANDING · UNAVAILABLE/);assert.match(html,/↗ DEPARTING · UNAVAILABLE/);
 assert.doesNotMatch(html,/class="atis-value">(?:09|27)/);
});

test('source times require explicit timezone and valid calendar values',()=>{
 for(const updatedAt of [stamp(5).slice(0,-1),'2026-02-30T12:00:00Z','2026-11-24T24:00:00Z',stamp(-10)]){
  const html=render([{...arrival(5),updatedAt}]);
  assert.match(html,/↘ LANDING · UNAVAILABLE/);
  assert.match(html,/INFO — · ISSUED <strong>—/);
 }
 const offset=stamp(5).replace(/Z$/,'+00:00');
 const html=render([{...arrival(5),updatedAt:offset}]);
 assert.match(html,/↘ LANDING · CURRENT/);
 assert.match(render([{...arrival(5),updatedAt:stamp(5).replace(/Z$/,'1234Z')}]),/↘ LANDING · CURRENT/);
});

test('timezone-less snapshot retrieval cannot mark report current',()=>{
 const html=render([arrival(5)],stamp(1).slice(0,-1));
 assert.match(html,/↘ LANDING · STALE/);
 assert.match(html,/Snapshot retrieved: —/);
});
