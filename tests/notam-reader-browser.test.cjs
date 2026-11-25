const {test,before,after}=require('node:test'),assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process'),{chromium}=require('playwright');
const {readFileSync}=require('node:fs'),{join}=require('node:path');
const offlineFont='https://fonts.googleapis.com/css2?family=Inconsolata:wght@400;700&family=Overpass:wght@400;600;700;800&display=swap';
const base='http://127.0.0.1:8767';let server,browser;
before(async()=>{server=spawn(process.env.PYTHON||'python3',['-B','-m','http.server','8767','--bind','127.0.0.1'],{stdio:'ignore'});for(let i=0;i<50;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});});
after(async()=>{await browser?.close();server?.kill();});
async function localPage(width=1440){const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),external=[],errors=[];await context.route('**/*',r=>{if(new URL(r.request().url()).origin===base)return r.continue();if(r.request().url()===offlineFont)return r.fulfill({status:200,contentType:'text/css',body:''});external.push(r.request().url());return r.abort();});page.on('pageerror',e=>errors.push(e.message));return {context,page,external,errors};}
test('LOCAL_FORMAT preserves empty/multiple/exact strings; other evidence stays only in memory',async()=>{
 const {context,page,external}=await localPage();
 try{
  await page.setContent('<main id="reader"></main>');await page.addScriptTag({content:readFileSync(join(__dirname,'../notam-reader.js'),'utf8')});
  const result=await page.evaluate(()=>{
   const full='SYNTHETIC local\r\nline two\rline three\n🙂 <img src=x onerror=alert(1)> &';
   const source={retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{completeness:'UNKNOWN',notices:[
    {id:'DUPLICATE',number:'11/207',text:'HIDDEN_CONDITION RWY 18L',formatted_texts:[{type:'ICAO',text:'HIDDEN_ICAO'}, {type:'LOCAL_FORMAT',text:full}]},
    {id:'DUPLICATE',number:'11/9',text:null,formatted_texts:[{type:'ICAO',text:'HIDDEN_ICAO RWY 18L'},{type:'LOCAL_FORMAT',text:''}]},
    {number:'11/27',text:'RWY 18L',formatted_texts:[{type:'LOCAL_FORMAT',text:'SYNTHETIC first'},{type:'OTHER',text:'HIDDEN_OTHER'},{type:'LOCAL_FORMAT',text:'SYNTHETIC second'}]},
    {number:'11/214',text:'RWY 18L',formatted_texts:[{type:'ICAO',text:'HIDDEN_ICAO RWY 36R'}]}
   ]}}};
   const prior=JSON.stringify(source);NotamReader.set(source);
   document.querySelector('#reader').innerHTML=NotamReader.summary('KMEM')+'<table><tbody><tr>'+NotamReader.cell('KMEM','18L',['18L','36R'])+'</tr>'+NotamReader.row('KMEM','18L',['18L','36R'])+'</tbody></table>';NotamReader.after();
   return {texts:[...document.querySelectorAll('#reader-KMEM-18L .reader-raw')].map(p=>p.textContent),full,missing:document.querySelectorAll('#reader-KMEM-18L .local-unavailable').length,count:document.querySelector('[data-reader-open]').textContent,records:NotamReader.records('KMEM',['18L','36R']).length,otherCount:NotamReader.cell('KMEM','36R',['18L','36R']).includes('NOTAMs (1)'),unchanged:JSON.stringify(source)===prior,hiddenLeak:/HIDDEN_CONDITION|HIDDEN_ICAO|HIDDEN_OTHER/.test(document.querySelector('#reader').textContent),technical:document.querySelectorAll('.inline-reader table,.inline-reader h4,.inline-reader details,.inline-reader pre,.notam-reader,img').length,metadataAttribute:[...document.querySelectorAll('*')].some(el=>[...el.attributes].some(a=>a.value.includes('HIDDEN_')))};
  });
  assert.deepEqual(result.texts,['','SYNTHETIC first','SYNTHETIC second',result.full]);assert.equal(result.missing,1);assert.equal(result.count,'NOTAMs (4)');assert.equal(result.records,4);assert.equal(result.otherCount,true);assert.equal(result.unchanged,true);assert.equal(result.hiddenLeak,false);assert.equal(result.technical,0);assert.equal(result.metadataAttribute,false);assert.deepEqual(external,[]);
 }finally{await context.close();}
});
for(const width of [1440,390])test(`synthetic LOCAL_FORMAT preview, focus, SCAN and data states at ${width}px`,async()=>{
 const {context,page,external,errors}=await localPage(width);
 try{
  await page.goto(base+'/preview/');await page.waitForSelector('.runway-row');assert.equal(await page.locator('.runway-row').count(),8);assert.match(await page.locator('.synthetic-banner').innerText(),/SYNTHETIC/);assert.equal(await page.evaluate(()=>localStorage.getItem('spatchin-airports')),null);
  const b=page.locator('[data-reader-open="KMEM-18L"]');assert.equal(await b.innerText(),'NOTAMs (2)');await b.click();const region=page.locator('#scroll-KMEM-18L');await region.focus();await page.evaluate(()=>render());assert.equal(await page.evaluate(()=>document.activeElement.id),'scroll-KMEM-18L');assert.equal(await b.getAttribute('aria-expanded'),'true');assert.equal(await page.evaluate(()=>NotamReader.records('KMEM',ends('MEM')).find(n=>n.id==='SYN-1').effectiveEnd),'PERM');
  await b.click();await page.locator('#scan-toggle').click();await page.locator('#scan-terms').fill('lighting report');await page.waitForFunction(()=>document.querySelector('.inline-reader mark'));for(let i=0;i<await page.locator('#cards mark[data-scan-match]').count()&&(await b.getAttribute('aria-expanded'))!=='true';i++)await page.locator('#scan-next').click();assert.equal(await b.getAttribute('aria-expanded'),'true');
  await page.evaluate(()=>{SPATCHIN_SYNTHETIC_PREVIEW.notams.airports.KMEM.notices[0].formatted_texts[0].text+=' DYNAMICREADER';render();});await page.locator('#scan-terms').fill('DYNAMICREADER');await page.waitForFunction(()=>document.querySelector('.inline-reader mark'));await page.locator('#scan-next').click();assert.equal(await page.locator('.inline-reader b,.notam-reader,[data-expand],.notice-table,.notice-provenance').count(),0);
  for(const [state,pattern] of [['stale',/source reports STALE/],['error',/refresh failed/],['unavailable',/NOTAM data unavailable/]]){await page.selectOption('#preview-state',state);assert.match(await page.locator('.notam-summary').innerText(),pattern);}
  assert.equal(await page.locator('.runway-row').count(),8);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{await context.close();}
});
for(const state of ['available','unavailable','synthetic-rejected'])test(`production entry accepts only valid published snapshots: ${state}`,async()=>{
 const {context,page,external,errors}=await localPage();const fixture={retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{completeness:'UNKNOWN',warning:'SYNTHETIC TEST SNAPSHOT',notices:[{text:'HIDDEN_CONDITION RWY 18L',formatted_texts:[{type:'LOCAL_FORMAT',text:'SYNTHETIC LOCAL DISPLAY'}]}]}}};if(state==='synthetic-rejected')fixture.synthetic=true;
 await context.route('**/data/notams.json',r=>state==='unavailable'?r.fulfill({status:404,body:''}):r.fulfill({json:fixture}));
 try{
  await page.goto(base+'/dashboard/');await page.waitForFunction(()=>notamTransport&&!notamTransport.refreshing&&(notamTransport.snapshot||notamTransport.error)&&ends('MEM').length===8);assert.equal(await page.evaluate(()=>typeof SPATCHIN_SYNTHETIC_PREVIEW),'undefined');assert.equal(await page.locator('.synthetic-banner,.notam-reader').count(),0);
  if(state==='available'){assert.match(await page.locator('.notam-summary').innerText(),/Retrieved: 2020-01-01 00:00 UTC/);assert.equal(await page.evaluate(()=>notamTransport.snapshot.airports.KMEM.warning),'SYNTHETIC TEST SNAPSHOT');assert.match(await page.evaluate(()=>NotamReader.availability('KMEM')),/Coverage UNKNOWN/);assert.equal(await page.locator('#reader-KMEM-18L .reader-raw').textContent(),'SYNTHETIC LOCAL DISPLAY');assert.doesNotMatch(await page.locator('#cards').textContent(),/HIDDEN_CONDITION/);}else{assert.match(await page.locator('.notam-summary').innerText(),/NOTAM data unavailable/);assert.equal(await page.locator('.reader-notice').count(),0);if(state==='synthetic-rejected')assert.match(await page.locator('.notam-summary').innerText(),/Synthetic NOTAM snapshot rejected/);}
  assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
for(const width of [1440,390])test(`offline adapter output preserves all fields but renders only LOCAL_FORMAT at ${width}px`,async()=>{
 const normalized=spawnSync(process.env.PYTHON||(process.platform==='win32'?'python':'python3'),['-B','scripts/normalize_notam_snapshot.py','tests/fixtures/nms_reader_documentation.json','--airport','KCLT','--location','KCLT','--retrieved-utc','documentation preview only'],{encoding:'utf8'});assert.equal(normalized.status,0,normalized.stderr);const snapshot=JSON.parse(normalized.stdout);const {context,page,external}=await localPage(width);
 try{
  await page.goto(base+'/preview/');await page.waitForSelector('.runway-row');const result=await page.evaluate(data=>{const before=JSON.stringify(data);NotamReader.set(data);const div=document.createElement('div');div.id='adapter-review';div.innerHTML=NotamReader.summary('KCLT')+'<table><tbody><tr>'+NotamReader.cell('KCLT','27',['09','27'])+'</tr>'+NotamReader.row('KCLT','27',['09','27'])+'</tbody></table>';document.body.append(div);NotamReader.after();return {count:NotamReader.records('KCLT',['09','27']).length,unchanged:JSON.stringify(data)===before,texts:[...div.querySelectorAll('#reader-KCLT-27 .reader-raw')].map(el=>el.textContent)};},snapshot);
  assert.equal(result.count,snapshot.airports.KCLT.notices.length);assert.equal(result.unchanged,true);assert.deepEqual(result.texts,snapshot.airports.KCLT.notices.flatMap(n=>n.formatted_texts.filter(t=>t.type==='LOCAL_FORMAT').map(t=>t.text)));await page.locator('#scan-toggle').click();await page.locator('#scan-terms').fill('SAMPLE NOTAM');await page.waitForFunction(()=>document.querySelector('#adapter-review mark'));for(let i=0;i<await page.locator('mark[data-scan-match]').count()&&(await page.locator('[data-reader-open="KCLT-27"]').getAttribute('aria-expanded'))!=='true';i++)await page.locator('#scan-next').click();assert.equal(await page.locator('[data-reader-open="KCLT-27"]').getAttribute('aria-expanded'),'true');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(external,[]);
 }finally{await context.close();}
});
