'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const TafReader=require('../taf-reader.js');
const NOW=Date.parse('2026-11-20T08:00:00Z');
function report(overrides={}){
 return {icaoId:'KMEM',issueTime:'2026-11-20T06:00:00Z',validTimeFrom:NOW/1000-3600,
 validTimeTo:NOW/1000+22*3600,rawTAF:'TAF KMEM 200600Z 2006/2106 09005KT P6SM SKC',...overrides};
}
test('valid current TAF shows unchanged raw text and source times',()=>{
 const html=TafReader.render({code:'MEM',station:'KMEM',report:report(),now:NOW});
 assert.match(html,/TAF CURRENT/);
 assert.match(html,/Issued 2026-11-20 06:00Z/);
 assert.match(html,/Valid 2026-11-20 07:00Z–2026-11-21 06:00Z/);
 assert.match(html,/2006\/2106 09005KT/);
 assert.match(html,/ids=KMEM/);
 assert.doesNotMatch(html,/forecast wind|Headwind/);
});
test('source text is escaped without rewriting its contents',()=>{
 const html=TafReader.render({code:'MEM',station:'KMEM',report:report({rawTAF:'TAF KMEM </pre><script>alert(1)</script> & X'}),now:NOW});
 assert.match(html,/&lt;script&gt;/);
 assert.match(html,/&lt;\/pre&gt;/);
 assert.match(html,/&amp; X/);
 assert.doesNotMatch(html,/<script>/);
});
test('expired and old issues are marked stale and keep raw text',()=>{
 assert.match(TafReader.render({code:'MEM',station:'KMEM',report:report({validTimeTo:NOW/1000-1}),now:NOW}),/TAF STALE/);
 assert.match(TafReader.render({code:'MEM',station:'KMEM',report:report({issueTime:'2026-11-19T06:00:00Z'}),now:NOW}),/TAF STALE/);
});
test('missing station and malformed reports are unavailable, not current',()=>{
 for(const r of [null,report({icaoId:'KLAX'}),report({rawTAF:''}),report({issueTime:'tomorrow'}),report({validTimeTo:0})]){
   assert.match(TafReader.render({code:'MEM',station:'KMEM',report:r,now:NOW}),/TAF UNAVAILABLE/);
 }
 assert.match(TafReader.render({code:'ATL',station:null,report:null,now:NOW}),/Station mapping not verified/);
});
test('future issue rejected and future valid window marked clearly',()=>{
 assert.equal(TafReader.valid(report({issueTime:'2026-11-20T10:00:00Z'}),'KMEM',NOW),false);
 assert.match(TafReader.render({code:'MEM',station:'KMEM',report:report({validTimeFrom:NOW/1000+3600}),now:NOW}),/TAF NOT YET VALID/);
});
test('retained forecast has a refresh failure notice',()=>{
 const html=TafReader.render({code:'MEM',station:'KMEM',report:report(),feedError:true,now:NOW});
 assert.match(html,/retained previous TAF/);
});
