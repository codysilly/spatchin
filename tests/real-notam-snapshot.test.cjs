'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {readFileSync}=require('node:fs'),{join}=require('node:path');
const snapshots=require('../notam-snapshots.js'),reader=require('../notam-reader.js');

test('published KMEM snapshot retains real display data without private capture metadata',()=>{
 const data=snapshots.validate(JSON.parse(readFileSync(join(__dirname,'../data/notams.json'),'utf8')));
 const notices=data.airports.KMEM.notices;
 assert.equal(data.retrieved_utc,'2026-11-15T10:39:04.087408+00:00');
 assert.equal(data.airports.KMEM.completeness,'UNKNOWN');assert.equal(notices.length,38);
 assert.equal(notices.reduce((n,x)=>n+x.formatted_texts.filter(t=>t.type==='LOCAL_FORMAT').length,0),38);
 assert.equal(notices.reduce((n,x)=>n+x.formatted_texts.filter(t=>t.type==='ICAO').length,0),21);
 for(const notice of notices){
  for(const field of ['id','number','text','issued','effectiveStart','effectiveEnd','lastUpdated'])assert.equal(typeof notice[field],'string',field);
  for(const field of ['original_feature','source_index','attempt','accountId','contentUrl'])assert.equal(field in notice,false,field);
 }
 assert.equal(data.publication.source_reference,'https://notams.aim.faa.gov/notamSearch/');
 const serialized=JSON.stringify(data);
 for(const value of ['nms-shared-ledger','notam-geojson-baseline','d876acdd1a814b73bf57fc4a7170c78b','FAA_NMS_CLIENT'])assert.equal(serialized.includes(value),false,value);

 const runwayData=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));
 const inventory=runwayData.airports.MEM.map(runway=>runway.id);reader.set(data);
 const records=reader.records('KMEM',inventory);
 assert.equal(reader.airportRecords('KMEM').length,38);
 assert.equal(records.filter(notice=>notice.references.length).length,16);
 assert.deepEqual(Object.fromEntries(inventory.map(id=>[id,records.filter(notice=>notice.references.some(ref=>ref.id===id)).length])),
  {'09':1,'18C':1,'18L':1,'18R':3,'27':1,'36C':1,'36L':3,'36R':5});
 assert.match(reader.summary('KMEM'),/All airport snapshot notices \(38\)/);
});
