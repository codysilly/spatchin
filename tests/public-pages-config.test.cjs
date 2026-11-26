'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const config=readFileSync('_config.yml','utf8');
const homepage=readFileSync('index.html','utf8');
test('Jekyll publishes root dashboard while excluding synthetic/private staging code',()=>{
 assert.equal(existsSync('.nojekyll'),false);
 assert.match(config,/^exclude:\s*$/m);
 for(const path of ['dashboard','preview','staging'])assert.match(config,new RegExp('^\\s*- '+path+'\\s*$','m'));
 assert.doesNotMatch(config,/^\s*- index\.html\s*$/m);
 assert.doesNotMatch(config,/^include:/m);
});
test('public homepage shows full dashboard with prominent unvalidated warning',()=>{
 assert.match(homepage,/WORK IN PROGRESS\. Under development and not yet validated\./);
 assert.match(homepage,/src="app\.js"/);
 assert.match(homepage,/src="scan\.js"/);
 assert.match(readFileSync('app.js','utf8'),/import\('\.\/notam-snapshots\.js'\)/);
 assert.doesNotMatch(homepage,/src="notam-snapshots\.js"/);
 assert.doesNotMatch(homepage,/Not cleared for takeoff/);
});
