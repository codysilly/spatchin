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
  assert.match(markup.strip,new RegExp('flight-'+category.toLowerCase()+' is-active'));
  assert.equal((markup.strip.match(/class="flight-segment/g)||[]).length,4);
 }
 for(const value of [undefined,null,'','NO DATA','UNKNOWN','vfr','SYNTHETIC']){
  const metar=record(value);
  assert.equal(metar.flightCategory,null);
  const markup=context.categoryMarkup(metar);
  assert.match(markup.tag,/NO DATA/);
  assert.equal(markup.strip,'');
 }
});

test('stale categories remain marked as observation-based, not live',()=>{
 const metar=record('VFR',120);
 assert.equal(context.metarState(metar),'stale');
 assert.match(context.categoryMarkup(metar).tag,/stale METAR observation/);
 assert.match(context.categoryMarkup(metar).strip,/stale observation/);
 assert.match(context.metarStatus(metar),/STALE/);
});

test('approved palette and fonts are attached after original styles',()=>{
 for(const token of ['--bg:#1b1d1f','--panel2:#151617','--line:#3a3d40','--muted:#a3a6a8',
  '--text:#e6e6e1','--blue:#4fd1e6','--amber:#ffb000','--green:#b4e33d',
  '--flight-ifr:#ff6b6b','--flight-lifr:#ff4fd8'])assert.ok(css.includes(token),token);
 assert.ok(css.includes('background-image:none!important'));
 assert.match(html,/fonts\.googleapis\.com\/css2\?family=Inconsolata/);
 assert.match(html,/family=Overpass/);
 assert.ok(html.indexOf('charcoal-dashboard.css')>html.indexOf('dashboard.css'));
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
