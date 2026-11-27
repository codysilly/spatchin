import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {currentDiagram, currentDiagramMarkup} from '../airport-diagrams.js';

const index=JSON.parse(readFileSync(new URL('../data/airport-diagrams.json',import.meta.url),'utf8'));
const start=Date.parse(index.effective_from_utc),end=Date.parse(index.effective_to_utc);
const resolve=(code,icao,now=start,data=index)=>currentDiagram(data,code,icao,now);

test('catalog resolves all 130 distinct chart filenames',()=>{
 const entries=Object.entries(index.airports);
 assert.equal(entries.length,130);
 const urls=new Set();
 for(const [code,entry] of entries){
  const actual=resolve(code,entry.icao);
  assert.ok(actual);
  assert.equal(actual.url,'https://aeronav.faa.gov/d-tpp/'+index.cycle+'/'+entry.pdf_name);
  urls.add(actual.url);
 }
 assert.equal(urls.size,130);
});

test('known cycle 2612 chart identities',()=>{
 if(index.cycle!=='2612')return;
 for(const [code,name] of Object.entries({MEM:'00253AD.PDF',ORD:'00166AD.PDF',LAX:'00237AD.PDF',JFK:'00610AD.PDF'})){
  assert.equal(resolve(code,'K'+code).url,'https://aeronav.faa.gov/d-tpp/2612/'+name);
 }
});

test('effective interval includes start and excludes expiration',()=>{
 assert.equal(resolve('MEM','KMEM',start-1),null);
 assert.ok(resolve('MEM','KMEM',start));
 assert.ok(resolve('MEM','KMEM',end-1));
 assert.equal(resolve('MEM','KMEM',end),null);
});

test('missing, mismatched or unsafe entries never resolve',()=>{
 assert.equal(resolve('ZZZ','KZZZ'),null);
 assert.equal(resolve('MEM','KORD'),null);
 assert.equal(resolve('MEM','KMEM',start,null),null);
 const bad=structuredClone(index);
 bad.airports.MEM.pdf_name='../OTHER.PDF';
 assert.equal(resolve('MEM','KMEM',start,bad),null);
 bad.airports.MEM.pdf_name='00253AD.PDF';bad.cycle='2612/../';
 assert.equal(resolve('MEM','KMEM',start,bad),null);
});

test('rendered link includes source and cycle, expired link is absent',()=>{
 const markup=currentDiagramMarkup(index,'MEM','KMEM',String,start);
 assert.match(markup,/Airport diagram for MEM/);
 assert.ok(markup.includes('FAA d-TPP cycle '+index.cycle));
 assert.match(markup,/target="_blank" rel="noopener"/);
 assert.equal(currentDiagramMarkup(index,'MEM','KMEM',String,end),'');
});
