'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const root=readFileSync('index.html','utf8');
const local=readFileSync('dashboard/index.html','utf8');
const app=readFileSync('app.js','utf8');
const css=readFileSync('charcoal-dashboard.css','utf8');
const warning='WORK IN PROGRESS. Under development and not yet validated.';
test('public homepage is the real v0.9 dashboard, not the former holding page',()=>{
 assert.match(root,/<title>Spatchin v0\.9<\/title>/);
 assert.ok(root.includes('<div class="wip-banner" role="note">'+warning+'</div>'));
 assert.doesNotMatch(root,/Not cleared for takeoff|holding-banner|splash\.css/);
 assert.doesNotMatch(root,/<base href=/);
 for(const resource of ['styles.css','charcoal-dashboard.css','app.js','scan.js','assets/branding/logo-cyan-magenta.svg'])assert.ok(root.includes('"'+resource+'"'),'missing '+resource);
 for(const control of ['id="cards"','id="scan-toggle"','id="scan-terms"','id="iata"'])assert.ok(root.includes(control),'missing '+control);
 assert.match(root,/https:\/\/aviationweather\.gov\//);
 assert.match(root,/<script type="module" src="app\.js" data-forecast="true">/);
 for(const path of ['airport-catalog.js','notam-reader.js','notam-snapshots.js','taf-reader.js','taf-timeline.js'])assert.ok(app.includes("import('./"+path+"')"),'missing module import '+path);
});
test('offline dashboard remains equivalent, including source warnings and version',()=>{
 assert.ok(local.includes('<base href="../">'));
 assert.equal(local.replace('<base href="../">',''),root);
 assert.ok(root.includes('do not use for real world flight planning or navigation'));
 assert.match(css,/\.wip-banner\{[^}]*font:800 clamp\(16px,/);
 assert.match(css,/\.wip-banner\{[^}]*border-bottom:2px solid #ffb000/);
});

// The local synthetic previews must not reference retired stylesheets.
test('preview stylesheet paths resolve to existing local files',()=>{
 for(const path of ['preview/index.html','preview/snapshot-loader.html']){
  const html=readFileSync(path,'utf8');
  const links=[...html.matchAll(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g)].map(match=>match[1]);
  assert.ok(links.length>0,'no stylesheets in '+path);
  for(const href of links)assert.ok(existsSync(href),'missing '+href+' in '+path);
 }
});

test('all dashboard entry points load SCAN as one ES module',()=>{
 for(const path of ['index.html','dashboard/index.html','preview/index.html','preview/snapshot-loader.html']){
  const html=readFileSync(path,'utf8');
  assert.equal((html.match(/<script type="module" src="scan\.js">/g)||[]).length,1,path);
  assert.equal((html.match(/src="scan\.js"/g)||[]).length,1,path);
 }
});
test('core modules expose named exports without browser globals or automatic Node startup',()=>{
 const {AirportCatalog,AirportMetadata}=require('../airport-catalog.js');
 assert.equal(AirportCatalog.length,130);
 assert.equal(AirportMetadata.MEM.icao,'KMEM');
 assert.equal(typeof require('../notam-reader.js').NotamReader.references,'function');
 assert.equal(typeof require('../notam-snapshots.js').NotamSnapshots.validate,'function');
 assert.deepEqual(Object.keys(require('../app.js')),['mountDashboard']);
 for(const name of ['AirportCatalog','AirportMetadata','NotamReader','NotamSnapshots','mountDashboard'])assert.equal(globalThis[name],undefined);
});
test('SCAN exports literal search rules without requiring browser state',async()=>{
 const {literalPattern,matchingKeyword}=await import('../scan.js');
 const ordered=[{term:'runway',index:0},{term:'run',index:1},{term:'a+b',index:2},{term:'[x]',index:3},{term:'Ångström',index:4}];
 const text='RUNWAY run a+b aab [x] Ångström ångström';
 assert.deepEqual([...text.matchAll(literalPattern(ordered,false))].map(m=>m[0]),['RUNWAY','run','a+b','[x]','Ångström','ångström']);
 assert.deepEqual([...text.matchAll(literalPattern(ordered,true))].map(m=>m[0]),['run','a+b','[x]','Ångström']);
 assert.equal(matchingKeyword(ordered,'RUNWAY',false),ordered[0]);
 assert.equal(matchingKeyword(ordered,'aab',false),undefined);
 assert.equal(matchingKeyword(ordered,'[x]',true),ordered[3]);
 assert.equal(matchingKeyword(ordered,'ångström',true),undefined);
});
