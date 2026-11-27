// Execute the actual loader, reader and app with DOM stubs; transport is entirely injected.
const {test}=require('node:test');const assert=require('node:assert/strict');
const vm=require('node:vm');const {readFileSync}=require('node:fs');const {join}=require('node:path');
const {mountInVM}=require('./dashboard-module-support.cjs');
function load({notams,runways,diagrams}={}){
 const calls=[],elements=new Map(),pending=[];
 const ctx=vm.createContext({URL,AbortController,setTimeout,clearTimeout,console:{info(){},error(){}},setInterval(){},localStorage:{getItem(){return null},setItem(){throw Error('No preferences should be written')}},
  document:{baseURI:'http://local.test/spatchin/index.html',querySelectorAll:()=>[],getElementById:id=>{if(!elements.has(id))elements.set(id,{addEventListener(){},innerHTML:'',textContent:''});return elements.get(id);}},
  fetch:(url,options)=>{calls.push(url);const path=new URL(url,'http://local.test/spatchin/').pathname;
   if(path.endsWith('/notams.json'))return Promise.resolve(notams||{ok:false,status:404});
   if(path.endsWith('/airport-diagrams.json')&&diagrams)return Promise.resolve({ok:true,json:async()=>diagrams});
   if(path.endsWith('/runways.json')&&runways)return Promise.resolve({ok:true,json:async()=>runways});
   return new Promise(resolve=>pending.push(resolve));
  }});
 const {run}=mountInVM(ctx,[['airport-catalog.js',['AirportCatalog','AirportMetadata']],['notam-reader.js',['NotamReader']],['notam-snapshots.js',['NotamSnapshots']]]);
 return {ctx,calls,elements,run};
}
const valid=()=>({retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{notices:[{text:'SYNTHETIC RWY 18L retained report'}]}}});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
// Historical pre-magnetic publication retained as an explicit compatibility fixture.
const legacyRunways=()=>({"source":"FAA NASR 28-Day Subscription — APT_RWY_END.csv","source_url":"https://nfdc.faa.gov/webContent/28DaySub/extra/29_Oct_2026_APT_CSV.zip","effective_date":"2026-10-29","generated_utc":"2026-11-19T20:47:46.831271+00:00","heading_reference":"TRUE","airports":{"LAX":[{"id":"06L","true_heading":83,"pair":"06L/24R"},{"id":"06R","true_heading":83,"pair":"06R/24L"},{"id":"07L","true_heading":83,"pair":"07L/25R"},{"id":"07R","true_heading":83,"pair":"07R/25L"},{"id":"24L","true_heading":263,"pair":"06R/24L"},{"id":"24R","true_heading":263,"pair":"06L/24R"},{"id":"25L","true_heading":263,"pair":"07R/25L"},{"id":"25R","true_heading":263,"pair":"07L/25R"}],"MEM":[{"id":"09","true_heading":92,"pair":"09/27"},{"id":"18C","true_heading":179,"pair":"18C/36C"},{"id":"18L","true_heading":179,"pair":"18L/36R"},{"id":"18R","true_heading":179,"pair":"18R/36L"},{"id":"27","true_heading":272,"pair":"09/27"},{"id":"36C","true_heading":359,"pair":"18C/36C"},{"id":"36L","true_heading":359,"pair":"18R/36L"},{"id":"36R","true_heading":359,"pair":"18L/36R"}],"JFK":[{"id":"04L","true_heading":31,"pair":"04L/22R"},{"id":"04R","true_heading":31,"pair":"04R/22L"},{"id":"13L","true_heading":121,"pair":"13L/31R"},{"id":"13R","true_heading":121,"pair":"13R/31L"},{"id":"22L","true_heading":211,"pair":"04R/22L"},{"id":"22R","true_heading":211,"pair":"04L/22R"},{"id":"31L","true_heading":301,"pair":"13R/31L"},{"id":"31R","true_heading":301,"pair":"13L/31R"}],"ORD":[{"id":"04L","true_heading":39,"pair":"04L/22R"},{"id":"04R","true_heading":42,"pair":"04R/22L"},{"id":"09C","true_heading":90,"pair":"09C/27C"},{"id":"09L","true_heading":90,"pair":"09L/27R"},{"id":"09R","true_heading":90,"pair":"09R/27L"},{"id":"10C","true_heading":90,"pair":"10C/28C"},{"id":"10L","true_heading":90,"pair":"10L/28R"},{"id":"10R","true_heading":90,"pair":"10R/28L"},{"id":"22L","true_heading":222,"pair":"04R/22L"},{"id":"22R","true_heading":219,"pair":"04L/22R"},{"id":"27C","true_heading":270,"pair":"09C/27C"},{"id":"27L","true_heading":270,"pair":"09R/27L"},{"id":"27R","true_heading":270,"pair":"09L/27R"},{"id":"28C","true_heading":270,"pair":"10C/28C"},{"id":"28L","true_heading":270,"pair":"10R/28L"},{"id":"28R","true_heading":270,"pair":"10L/28R"}]}});
test('dashboard startup requests one local NOTAM snapshot; ordinary rerenders never refetch',async()=>{
 const app=load({notams:{ok:true,json:async()=>valid()}});await tick();
 assert.equal(app.run('notamTransport.error'),null);assert.doesNotMatch(app.elements.get('cards').innerHTML,/retained report/);assert.equal(app.run("NotamReader.records('KMEM',[])[0].text"),'SYNTHETIC RWY 18L retained report');
 app.run('render();render();render()');assert.equal(app.calls.filter(u=>u.includes('notams.json')).length,1);
 assert.ok(app.calls.every(u=>new URL(u,'http://local.test').hostname==='local.test'));
 assert.match(app.elements.get('cards').innerHTML,/Retrieved: 2020-01-01 00:00 UTC/);
 assert.match(app.elements.get('cards').innerHTML,/LOCAL_FORMAT text unavailable/);
});
test('dashboard first-load failure is explicit and synthetic production data is refused',async()=>{
 for(const notams of [{ok:false,status:404},{ok:true,json:async()=>({...valid(),synthetic:true})}]){
  const app=load({notams});await tick();assert.equal(app.run('notamTransport.snapshot'),null);assert.match(app.elements.get('cards').innerHTML,/NOTAM data unavailable/);
 }
});
test('valid optional eight-end MEM snapshot renders without wind; invalid MEM is rejected',async()=>{
 const legacy=legacyRunways();
 delete legacy.airports.MEM;delete legacy.airport_metadata;
 for(const mem of [undefined,Array.from({length:8},(_,i)=>({id:['09','27','18L','36R','18C','36C','18R','36L'][i],true_heading:i*40})),Array(8).fill({id:'09',true_heading:90}),[{id:'18L',true_heading:999}]]){
  const runways=JSON.parse(JSON.stringify(legacy));
  if(mem!==undefined){
   runways.airports.MEM=mem.map((end,i)=>({...end,pair:end.pair||[['09','27'],['27','09'],['18L','36R'],['36R','18L'],['18C','36C'],['36C','18C'],['18R','36L'],['36L','18R']][i]?.join('/')}));
   if(runways.airport_coverage?.MEM)runways.airport_coverage.MEM.status='available';
  }else if(runways.airport_coverage?.MEM)runways.airport_coverage.MEM.status='unavailable';
  const app=load({runways});await tick();
  const expected=mem&&new Set(mem.map(x=>x.id)).size===8?8:0;
  assert.equal(app.run('ends("MEM").length'),expected);
  if(expected)assert.equal((app.elements.get('cards').innerHTML.match(/data-reader-open=/g)||[]).length,8);
 }
});

test('published MEM NASR inventory preserves every nominal magnetic heading and provenance without wind',async()=>{
 const runways=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));
 assert.equal(runways.heading_reference,'MAGNETIC');
 assert.match(runways.source,/FAA NASR.*APT_RWY_END\.csv/);
 assert.equal(new URL(runways.source_url).origin,'https://nfdc.faa.gov');
 assert.match(new URL(runways.source_url).pathname,/\/28DaySub\/extra\/\d{2}_[A-Za-z]{3}_\d{4}_APT_CSV\.zip$/);
 assert.match(runways.effective_date,/^\d{4}-\d{2}-\d{2}$/);
 const app=load({runways});await tick();
 assert.deepEqual(Array.from(app.run('ends("MEM")')),['09','18C','18L','18R','27','36C','36L','36R']);
 for(const end of runways.airports.MEM){
  assert.equal(end.magnetic_heading,Number(end.id.slice(0,2))*10%360);
  const variation=runways.airport_metadata.MEM.magnetic_variation_deg;
  assert.equal(app.run(`runwayHeading("MEM",${JSON.stringify(end.id)})`),Number.isFinite(variation)?(end.magnetic_heading+variation+360)%360:null);
  const windRow=app.run(`runwayRow("MEM",${JSON.stringify(end.id)},{direction:100,speed:10})`);
  assert.ok(windRow.includes(`Approximate magnetic runway heading: ${end.magnetic_heading}°`));
  assert.ok(end.pair.split('/').includes(end.id));
 }
 const html=app.elements.get('cards').innerHTML;
 assert.equal((html.match(/<td>[^<]*<\/td>/g)||[]).length,16);
 assert.equal(app.run('runwayData.effective_date'),runways.effective_date);
 assert.equal(app.run('runwayData.source_url'),runways.source_url);
 assert.ok(!html.includes('Chart-derived'));assert.match(html,/class="airport-diagram"/);assert.match(html,/Find FAA diagram/);assert.doesNotMatch(html,/00253AD.PDF/);
 assert.equal((app.elements.get('cards').innerHTML.match(/data-reader-open=/g)||[]).length,8);
 assert.equal(app.run('runwayBearingLabel("ORD")'),'Approximate magnetic runway heading');
 assert.match(app.run('diagramHeader("ORD")'),/Find FAA diagram/);
 assert.doesNotMatch(app.run('diagramHeader("ORD")'),/\.PDF/i);
 assert.equal(app.run('runwayBearingLabel("MEM")'),'Approximate magnetic runway heading');
 assert.match(html,/Approx. wind components/);
});

test('synthetic legacy chart metadata is labelled approximate and a later NASR snapshot replaces it',async()=>{
 const runways=legacyRunways();
 runways.airport_metadata={MEM:{heading_method:'chart-derived-approximate',source_url:'https://aeronav.faa.gov/d-tpp/2001/SYNTHETIC-diagram.pdf',effective_date:'2020-01-01',valid_through:'2020-01-29'}};
 const app=load({runways});await tick();
 assert.equal(app.run('runwayBearingLabel("MEM")'),'Chart-derived approximate true bearing');
 const html=app.elements.get('cards').innerHTML;
 assert.match(html,/Chart effective/);
 assert.match(html,/SYNTHETIC-diagram\.pdf/);
 assert.match(html,/Chart effective 2020-01-01 through 2020-01-29/);
 const current=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));
 app.run('runwayData=PublishedSnapshots.runways('+JSON.stringify(current)+',approvedCatalog);render()');
 assert.equal(app.run('runwayBearingLabel("MEM")'),'Approximate magnetic runway heading');
 assert.ok(!app.elements.get('cards').innerHTML.includes('Chart-derived'));
});

test('published diagram index integrates with airport cards without changing runway bearings',async()=>{
 const diagrams=JSON.parse(readFileSync(join(__dirname,'../data/airport-diagrams.json'),'utf8'));
 const app=load({diagrams});await tick();
 app.run('Date.now=()=>Date.parse(diagramIndex.effective_from_utc)');
 app.run('airports=["MEM","ORD","LAX","JFK"];render()');
 const html=app.elements.get('cards').innerHTML;
 for(const code of ['MEM','ORD','LAX','JFK']){
  const url='https://aeronav.faa.gov/d-tpp/'+diagrams.cycle+'/'+diagrams.airports[code].pdf_name;
  assert.ok(html.includes(url),code);
 }
 assert.equal(app.calls.filter(u=>u.includes('airport-diagrams.json')).length,1);
 assert.ok(app.calls.every(u=>new URL(u,'http://local.test').hostname==='local.test'));
 app.run('Date.now=()=>Date.parse(diagramIndex.effective_to_utc);render()');
 assert.match(app.run('diagramHeader("ORD")'),/Find FAA diagram/);
 assert.doesNotMatch(app.run('diagramHeader("ORD")'),/\.PDF/i);
});
