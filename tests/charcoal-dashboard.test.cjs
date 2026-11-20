'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');

const app=readFileSync('app.js','utf8');
const css=readFileSync('charcoal-dashboard.css','utf8');
const html=readFileSync('index.html','utf8');

// Exercise exactly the pure functions used by the current dashboard renderer.
const from=app.indexOf("const flightCategories=['VFR','MVFR','IFR','LIFR'];");
const to=app.indexOf('const observedSelection=new Map();');
const metarStart=app.indexOf('function parseMetar(m){');
const metarEnd=app.indexOf('async function refresh(){',metarStart);
assert.ok(from>=0&&to>from&&metarStart>0&&metarEnd>metarStart);
const code=app.slice(from,to)+'\n'+app.slice(metarStart,metarEnd);
const context=vm.createContext({Date,Number,METAR_STALE_MS:65*60*1000});
new vm.Script(code,{filename:'dashboard-flight-categories.js'}).runInContext(context);
const record=(category,minutesAgo=0)=>context.parseMetar({
  icaoId:'KMEM',obsTime:Math.floor((Date.now()-minutesAgo*60000)/1000),
  wdir:150,wspd:6,wgst:null,rawOb:'SYNTHETIC TEST DATA',fltCat:category
});

test('only the four AWC flight-category values are accepted',()=>{
 for(const category of ['VFR','MVFR','IFR','LIFR']){
  const metar=record(category);
  assert.equal(metar.flightCategory,category);
  const markup=context.categoryMarkup(metar);
  assert.match(markup.tag,new RegExp('>'+category+'<'));
  assert.equal(markup.strip,undefined,'four-part legend is removed');
 }
 for(const value of [undefined,null,'','NO DATA','UNKNOWN','vfr','SYNTHETIC']){
  const metar=record(value);
  assert.equal(metar.flightCategory,null);
  const markup=context.categoryMarkup(metar);
  assert.match(markup.tag,/NO DATA/);
  assert.equal(markup.strip,undefined);
 }
});

test('stale categories remain marked as observation-based, not live',()=>{
 const metar=record('VFR',120);
 assert.equal(context.metarState(metar),'stale');
 assert.match(context.categoryMarkup(metar).tag,/stale METAR observation/);
 assert.equal(context.categoryMarkup(metar).strip,undefined);
 assert.match(context.metarStatus(metar),/STALE/);
});

test('approved palette and fonts are attached after original styles',()=>{
 for(const token of ['--bg:#1b1d1f','--panel2:#151617','--line:#3a3d40','--muted:#a3a6a8',
  '--text:#e6e6e1','--blue:#4fd1e6','--amber:#ffb000','--green:#b4e33d',
  '--flight-ifr:#ff6b6b','--flight-lifr:#ff4fd8'])assert.ok(css.includes(token),token);
 assert.ok(css.includes('background-image:none!important'));
 assert.match(html,/fonts\.googleapis\.com\/css2\?family=Inconsolata/);
 assert.match(html,/family=Overpass/);
 assert.ok(html.indexOf('charcoal-dashboard.css')>html.indexOf('styles.css'));
 assert.ok(!html.includes('href="dashboard.css"'),'retired stylesheet must not be loaded');
 assert.match(html,/class="brand-wordmark">SPATCHIN/);
 assert.match(html,/v0\.9/);
});

test('existing SCAN and NOTAM markup remain available',()=>{
 assert.ok(html.includes('id="scan-toggle"'));
 assert.ok(html.includes('id="scan-terms"'));
 assert.ok(app.includes('reader?.summary(icao(code))'));
 assert.ok(app.includes('reader?.row(icao(code),id,r)'));
 assert.ok(app.includes('notamSnapshots?.refresh()'));
 assert.ok(app.includes('airports.length>=30'));
 assert.ok(app.includes('localStorage.setItem(AIRPORT_STORAGE_KEY'));
 assert.match(app,/class="airport-footer">\$\{notamTransportBlock\(code\)\}/);
 assert.match(css,/\.cards\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
 assert.match(css,/@media\(max-width:760px\)/);
});

test('compact row and raw METAR markup preserve source links',()=>{
 assert.match(app,/class="airport-top-row"/);
 assert.match(app,/data-airport-drag="/);
 assert.match(app,/data-remove="/);
 assert.match(app,/class="weather-row metar-panel"/);
 assert.match(app,/function moveAirport\(code,targetIndex\)/);
 assert.ok(!app.includes('${category.strip}'));
 assert.match(css,/\.icao\{font:700 60px\/\.95 var\(--font-data/);
 assert.match(css,/font:400 21px\/1\.6 var\(--font-data/);
 assert.match(html,/id="airport-order-status"/);
});

test('SPA-68 uses a single structural foundation and removes old theme rules',()=>{
 const foundation=readFileSync('styles.css','utf8');
 assert.equal((html.match(/rel="stylesheet" href="[^"]+\.css"/g)||[]).length,2);
 assert.ok(html.indexOf('styles.css')<html.indexOf('charcoal-dashboard.css'));
 assert.ok(!html.includes('href="dashboard.css"'));
 assert.doesNotMatch(foundation,/--bg:#0b1520|--bg:#061321/);
 assert.doesNotMatch(foundation,/radial-gradient|linear-gradient/);
 assert.doesNotMatch(css,/\.flight-strip\{|\.flight-segment\{|\.airport-code-line\{/);
 for(const active of ['.scan-toggle{','.scan-panel{','.notam-reader{','.atis-runways{','.inline-reader{','.sr-only{'])
  assert.ok(foundation.includes(active),'preserved structural rule '+active);
});
