'use strict';
const {installDashboardProbe}=require('./dashboard-module-support.cjs');
const {test,before,after}=require('node:test'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const {pythonCommand}=require('./python-launcher.cjs');
const offlineFont='https://fonts.googleapis.com/css2?family=Inconsolata:wght@400;700&family=Overpass:wght@400;600;700;800&display=swap';
const base='http://127.0.0.1:8774';let server,browser;
before(async()=>{server=spawn(pythonCommand(),['-B','-m','http.server','8774','--bind','127.0.0.1'],{stdio:'ignore'});for(let i=0;i<50;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});});
after(async()=>{await browser?.close();server?.kill();});
async function localPage(width){const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),external=[],errors=[];await context.route('**/*',r=>{if(new URL(r.request().url()).origin===base)return r.continue();if(r.request().url()===offlineFont)return r.fulfill({status:200,contentType:'text/css',body:''});external.push(r.request().url());return r.abort();});page.on('pageerror',e=>errors.push(e.message));return {context,page,external,errors};}
for(const width of [1440,390])test(`verified muted AWC source links, footer removal/focus and empty preference at ${width}px`,async()=>{
 const {context,page,external,errors}=await localPage(width);
 try{
  await installDashboardProbe(page,base);await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof render==='function');await page.waitForFunction(()=>notamTransport&&!notamTransport.refreshing);
  await page.evaluate(()=>{airports=['MEM','ORD','LAX','JFK','IND'];save();render();});
  for(const [code,station] of [['MEM','KMEM'],['ORD','KORD'],['LAX','KLAX'],['JFK','KJFK'],['IND','KIND']]){
   const card=page.locator(`[data-airport="${code}"]`),badge=card.locator('.metar-panel a.report-source');
   assert.equal(await badge.getAttribute('href'),`https://aviationweather.gov/data/metar/?ids=${station}`);assert.equal(await badge.getAttribute('target'),'_blank');assert.equal(await badge.getAttribute('rel'),'noopener noreferrer');assert.match(await badge.getAttribute('aria-label'),new RegExp(`${station}.*new tab`));
   assert.equal(await card.locator('a[href^="https://aviationweather.gov/data/metar/"]').count(),1);assert.equal(await card.locator('.taf a').getAttribute('href'),`https://aviationweather.gov/api/data/taf?ids=${station}&format=raw`);assert.deepEqual(await badge.evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})),{background:'rgba(0, 0, 0, 0)',color:'rgb(79, 209, 230)'});
   await badge.focus();assert.equal(await badge.evaluate(el=>el===document.activeElement),true);assert.notEqual(await badge.evaluate(el=>getComputedStyle(el).outlineStyle),'none');
  }
  // Unknown mappings cannot be added through the catalog. Exercise the helper without creating a real airport.
  const unknown=await page.evaluate(()=>metarBadge('ZZZ','Observation unavailable',false));assert.deepEqual(unknown,{raw:'Observation unavailable',fallback:''});
  assert.equal(await page.locator('[data-expand],.details,.notam-reader').count(),0);assert.equal(await page.locator('.airport-head [data-remove]').count(),5);
  assert.doesNotMatch(await page.locator('#cards').innerText(),/Last check:|Last successful check:|Show details|Original METAR/);assert.match(await page.locator('.notam-transport').first().innerText(),/Published snapshot · No live provider request/);
  await page.locator('[data-remove="MEM"]').click();assert.equal(await page.evaluate(()=>document.activeElement.dataset.remove),'ORD');assert.equal(await page.locator('[data-airport="MEM"]').count(),0);
  await page.evaluate(()=>render());assert.equal(await page.evaluate(()=>document.activeElement.dataset.remove),'ORD');
  while(await page.locator('[data-remove]').count())await page.locator('[data-remove]').first().click();
  assert.equal(await page.evaluate(()=>document.activeElement.id),'iata');assert.equal(await page.evaluate(()=>localStorage.getItem('spatchin-airports')),'[]');await page.reload();await page.waitForFunction(()=>typeof render==='function');assert.equal(await page.locator('.airport').count(),0);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
for(const width of [1440,390])test(`LOCAL_FORMAT-only DOM and SCAN retain all underlying records/counts at ${width}px`,async()=>{
 const {context,page,external,errors}=await localPage(width);
 const text='  SYNTHETIC VISIBLE_LOCAL\r\n🙂 <b>literal</b>&\rstandalone CR\nstandalone LF  ';
 const data={retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{completeness:'UNKNOWN',warning:'SYNTHETIC collection/legal warning — unchanged.',notices:[
  {id:'DUP',number:'11/207',text:'RAW_CONDITION_ONLY RWY 18R/36L',formatted_texts:[{type:'LOCAL_FORMAT',text},{type:'ICAO',text:'ICAO_ONLY'}],secret_metadata_for_test:'HIDDEN_METADATA'},
  {id:'DUP',number:'11/9',text:'RWY 18R',formatted_texts:[{type:'LOCAL_FORMAT',text:''}]},
  {number:'11/27',text:null,formatted_texts:[{type:'ICAO',text:'ICAO_ONLY RWY 18R'}]},
  {number:'11/214',text:'RWY 18R',formatted_texts:[{type:'LOCAL_FORMAT',text:'SYNTHETIC multi first'},{type:'OTHER',text:'OTHER_ONLY'},{type:'LOCAL_FORMAT',text:'SYNTHETIC multi second'}]},
  {scope:'airport-wide',text:'UNMATCHED_ONLY',formatted_texts:[{type:'LOCAL_FORMAT',text:'AIRPORT_WIDE_LOCAL'}]}
 ]}}};
 await context.route('**/data/notams.json',r=>r.fulfill({json:data}));
 try{
  await installDashboardProbe(page,base);await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof render==='function');await page.waitForFunction(()=>notamTransport?.snapshot&&ends('MEM').length===8);
  const before=await page.evaluate(()=>JSON.stringify(notamTransport.snapshot));
  const a=page.locator('[data-reader-open="KMEM-18R"]'),b=page.locator('[data-reader-open="KMEM-36L"]');assert.equal(await a.innerText(),'NOTAMs (4)');assert.match(await a.getAttribute('aria-label'),/NOTAMs \(4\).*18R.*KMEM/);
  await a.click();await b.click();assert.equal(await page.locator('#reader-KMEM-18R .reader-notice').count(),4);assert.equal(await page.locator('#reader-KMEM-18R .local-unavailable').textContent(),'LOCAL_FORMAT text unavailable.');
  const expected=['',text,'SYNTHETIC multi first','SYNTHETIC multi second'];assert.deepEqual(await page.locator('#reader-KMEM-18R .reader-raw').allTextContents(),expected);
  assert.equal(await page.locator('.inline-reader table,.inline-reader details,.inline-reader pre,.inline-reader dl,.inline-reader h4,.notam-reader,.notice-table,.notice-provenance').count(),0);
  const hidden=/RAW_CONDITION_ONLY|ICAO_ONLY|OTHER_ONLY|UNMATCHED_ONLY|HIDDEN_METADATA/;assert.doesNotMatch(await page.locator('body').textContent(),hidden);
  assert.equal(await page.locator('#airport-notams-KMEM .reader-raw').filter({hasText:'AIRPORT_WIDE_LOCAL'}).count(),1);assert.equal(await page.locator('[data-reader-inline] .reader-raw').filter({hasText:'AIRPORT_WIDE_LOCAL'}).count(),0);
  assert.equal(await page.evaluate(()=>[...document.querySelectorAll('[data-reader-inline] *')].some(el=>[...el.attributes].some(a=>a.value.includes('HIDDEN_METADATA')||a.value.startsWith('{')))),false);
  await page.locator('#scan-toggle').click();await page.locator('#scan-terms').fill('ICAO_ONLY, RAW_CONDITION_ONLY, HIDDEN_METADATA');assert.equal(await page.locator('#scan-count').textContent(),'0 / 0 matches');
  await page.locator('#scan-terms').fill('AIRPORT_WIDE_LOCAL');await page.waitForFunction(()=>document.querySelector('#airport-notams-KMEM mark'));await page.locator('#scan-next').click();assert.equal(await page.locator('#airport-notams-KMEM').evaluate(el=>el.open),true);assert.equal(await page.locator('#airport-notams-KMEM .scan-current').textContent(),'AIRPORT_WIDE_LOCAL');
  await page.locator('#scan-terms').fill('VISIBLE_LOCAL');await page.waitForFunction(()=>document.querySelector('.inline-reader mark'));await page.locator('#scan-next').click();await page.evaluate(()=>render());await page.waitForFunction(()=>document.querySelector('.inline-reader mark'));
  assert.equal(await a.getAttribute('aria-expanded'),'true');assert.equal(await b.getAttribute('aria-expanded'),'true');assert.deepEqual(await page.locator('#reader-KMEM-18R .reader-raw').allTextContents(),expected);assert.equal(await page.locator('mark mark,.inline-reader b').count(),0);
  await page.locator('#scan-terms').fill('');await page.waitForFunction(()=>!document.querySelector('mark[data-scan-match]'));assert.deepEqual(await page.locator('#reader-KMEM-18R .reader-raw').allTextContents(),expected);
  assert.doesNotMatch(await page.locator('body').textContent(),hidden);assert.equal(await page.evaluate(()=>JSON.stringify(notamTransport.snapshot)),before);assert.equal(await page.evaluate(()=>NotamReader.records('KMEM',ends('MEM')).length),5);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
