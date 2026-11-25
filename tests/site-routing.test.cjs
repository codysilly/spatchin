'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const root=readFileSync('index.html','utf8');
const local=readFileSync('dashboard/index.html','utf8');
const css=readFileSync('charcoal-dashboard.css','utf8');
const warning='WORK IN PROGRESS. Under development and not yet validated.';
test('public homepage is the real v0.9 dashboard, not the former holding page',()=>{
 assert.match(root,/<title>Spatchin v0\.9<\/title>/);
 assert.ok(root.includes('<div class="wip-banner" role="note">'+warning+'</div>'));
 assert.doesNotMatch(root,/Not cleared for takeoff|holding-banner|splash\.css/);
 assert.doesNotMatch(root,/<base href=/);
 for(const resource of ['styles.css','charcoal-dashboard.css','app.js','airport-catalog.js','notam-reader.js','notam-snapshots.js','taf-reader.js','taf-timeline.js','scan.js','assets/branding/logo-cyan-magenta.svg'])assert.ok(root.includes('"'+resource+'"'),'missing '+resource);
 for(const control of ['id="cards"','id="scan-toggle"','id="scan-terms"','id="iata"'])assert.ok(root.includes(control),'missing '+control);
 assert.match(root,/https:\/\/aviationweather\.gov\//);
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
