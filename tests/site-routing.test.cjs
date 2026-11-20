'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const landing=readFileSync('index.html','utf8');
const dashboard=readFileSync('dashboard/index.html','utf8');
const splash=readFileSync('splash.css','utf8');
test('public root is a dedicated holding page',()=>{
 assert.match(landing,/Not cleared for/);
 assert.match(landing,/takeoff…/);
 assert.match(landing,/yet\./);
 assert.match(landing,/class="floating-plane"/);
 assert.match(landing,/href="splash\.css"/);
 assert.doesNotMatch(landing,/src="app\.js"|id="cards"|id="scan-toggle"/);
 assert.match(splash,/#1b1d1f/);
 assert.match(splash,/@media \(prefers-reduced-motion: reduce\)/);
});
test('dashboard retains current sources, branding and version',()=>{
 assert.match(dashboard,/<base href="\.\.\/">/);
 assert.match(dashboard,/src="app\.js"/);
 assert.match(dashboard,/src="notam-snapshots\.js"/);
 assert.match(dashboard,/src="scan\.js"/);
 assert.match(dashboard,/href="styles\.css"/);
 assert.match(dashboard,/href="charcoal-dashboard\.css"/);
 assert.match(dashboard,/logo-cyan-magenta\.svg/);
 assert.match(dashboard,/v0\.9/);
 assert.match(dashboard,/WORK IN PROGRESS/);
});
