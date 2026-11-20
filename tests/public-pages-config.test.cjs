'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync,existsSync}=require('node:fs');
const config=readFileSync('_config.yml','utf8');
const landing=readFileSync('index.html','utf8');
test('GitHub Pages uses Jekyll to exclude all dashboard and preview routes',()=>{
 assert.equal(existsSync('.nojekyll'),false,'do not bypass Jekyll exclusions');
 assert.match(config,/^exclude:\s*$/m);
 for(const path of ['dashboard','preview']) assert.match(config,new RegExp('^\\s*- '+path+'\\s*$','m'));
 assert.doesNotMatch(config,/^include:/m);
});
test('public homepage does not link to or load development UI',()=>{
 assert.match(landing,/Not cleared for/);
 assert.match(landing,/takeoff…/);
 assert.doesNotMatch(landing,/(?:href|src)=["'][^"']*dashboard/);
 assert.doesNotMatch(landing,/src=["'](?:app|scan|notam-reader)\\.js/);
});
