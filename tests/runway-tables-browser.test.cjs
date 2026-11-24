'use strict';
const {test,before,after}=require('node:test'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{chromium}=require('playwright');
const base='http://127.0.0.1:8770';let server,browser;
before(async()=>{server=spawn('python3',['-B','-m','http.server','8770','--bind','127.0.0.1'],{stdio:'ignore'});for(let i=0;i<50;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});});
after(async()=>{await browser?.close();server?.kill();});
test('catalog additions enforce 30 total; removable MEM and deliberate empty state persist',async()=>{
 const context=await browser.newContext(),page=await context.newPage(),dialogs=[];
 await context.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 const observed=Math.floor((Date.now()-60000)/1000);
 await context.route('**/data/metars.json*',r=>r.fulfill({json:{updated_utc:new Date().toISOString(),metars:[{icaoId:'KIND',obsTime:observed,wdir:180,wspd:8,fltCat:'VFR',rawOb:'KIND SYNTHETIC OFFLINE METAR'}]}}));
 page.on('dialog',async d=>{dialogs.push(d.message());await d.dismiss();});
 try{
  await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof AirportCatalog!=='undefined');
  assert.equal(await page.locator('#airport-options option').count(),130);
  await page.fill('#iata','ZZZ');await page.locator('#add-form button').click();assert.match(dialogs.pop(),/approved C070 catalog/);
  await page.fill('#iata','IND');await page.locator('#add-form button').click();assert.deepEqual(await page.evaluate(()=>airports),['MEM','IND']);
  assert.equal(await page.evaluate(()=>icao('IND')),'KIND');
  const ind=page.locator('[data-airport="IND"]');
  await ind.locator('.metar-current').waitFor();
  assert.match(await ind.locator('.name').innerText(),/INDIANAPOLIS/);
  assert.match(await ind.locator('.metar-raw').innerText(),/KIND SYNTHETIC OFFLINE METAR/);
  assert.match(await ind.locator('.weather-badge').getAttribute('href'),/ids=KIND$/);
  assert.match(await ind.locator('.empty').innerText(),/Runway data pending/);
  await page.evaluate(()=>{airports=AirportCatalog.slice(0,30);render();});
  await page.fill('#iata','MEM');await page.locator('#add-form button').click();assert.match(dialogs.pop(),/Maximum 30/);
  assert.equal(await page.locator('.airport').count(),30);
  await page.evaluate(()=>{airports=['MEM'];render();});await page.locator('[data-remove="MEM"]').click();
  assert.equal(await page.locator('.airport').count(),0);await page.reload();assert.equal(await page.locator('.airport').count(),0);
  assert.equal(await page.evaluate(()=>localStorage.getItem('spatchin-airports')),'[]');
 }finally{await context.close();}
});
const text='SYNTHETIC RWY 18R/36L\r\nUNICODE 🙂 <unsafe> &\rCR\nLF SCANINLINE';
for(const width of [1440,390])test(`inline rows, keyboard, exact text, SCAN, independent observed UTC state at ${width}`,async()=>{
 const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),external=[],errors=[];
 await context.route('**/*',r=>{if(new URL(r.request().url()).origin===base)return r.continue();external.push(r.request().url());return r.abort();});
 const entry={completeness:'UNKNOWN',warning:'SYNTHETIC fixture — not real FAA data',notices:[{number:'11/207',text,formatted_texts:[{type:'LOCAL_FORMAT',text}]},{number:'11/9',text:'SYNTHETIC RWY 18R',formatted_texts:[{type:'LOCAL_FORMAT',text:'SYNTHETIC short LOCAL_FORMAT'}]},{number:'11/9',text:'SYNTHETIC unmatched source record'}]};
 await context.route('**/data/notams.json',r=>r.fulfill({json:{retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:entry}}}));
 // Keep this NOTAM/observed-time test in the forecast-unavailable state; TAF has its own tests.
 await context.route('**/data/tafs.json*',r=>r.fulfill({status:404,body:''}));
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(base+'/dashboard/');await page.waitForFunction(()=>notamTransport?.snapshot&&ends('MEM').length===8);
  const a=page.locator('[data-reader-open="KMEM-18R"]'),b=page.locator('[data-reader-open="KMEM-36L"]');
  await a.focus();await page.keyboard.press('Enter');await b.focus();await page.keyboard.press('Space');
  assert.equal(await a.getAttribute('aria-expanded'),'true');assert.equal(await b.getAttribute('aria-expanded'),'true');
  assert.equal(await page.locator('#reader-KMEM-18R').evaluate(el=>el.previousElementSibling.querySelector('td').textContent),'18R');
  assert.equal(await page.locator('#reader-KMEM-18R > td').getAttribute('colspan'),'4');
  assert.deepEqual(await page.locator('#reader-KMEM-18R .reader-notice').evaluateAll(els=>els.map(el=>el.dataset.readerKey)),['KMEM-1','KMEM-0']);
  assert.equal(await page.locator('#reader-KMEM-36L .reader-raw').textContent(),text);
  await page.evaluate(()=>render());assert.equal(await page.evaluate(()=>document.activeElement.dataset.readerOpen),'KMEM-36L');
  assert.equal(await a.getAttribute('aria-expanded'),'true');assert.equal(await b.getAttribute('aria-expanded'),'true');
  await a.click();assert.equal(await a.getAttribute('aria-expanded'),'false');assert.equal(await b.getAttribute('aria-expanded'),'true');
  await b.click();await page.locator('#scan-toggle').click();await page.locator('#scan-terms').fill('SCANINLINE');
  await page.waitForFunction(()=>document.querySelector('[data-reader-inline] mark'));
  // SCAN also indexes the airport-wide source list, which precedes runway rows.
  // Navigate across matches until the matching runway detail is revealed.
  for(let i=0;i<20&&(await a.getAttribute('aria-expanded'))!=='true';i++){
   await page.locator('#scan-next').click();
  }
  assert.equal(await a.getAttribute('aria-expanded'),'true');assert.equal(await page.locator('#reader-KMEM-18R .reader-raw').last().textContent(),text);
  await page.evaluate(()=>render());assert.equal(await a.getAttribute('aria-expanded'),'true');
  await page.locator('#scan-terms').fill('');await page.waitForFunction(()=>!document.querySelector('mark[data-scan-match]'));
  assert.equal(await page.locator('#reader-KMEM-18R .reader-raw').last().textContent(),text);
  assert.equal(await page.locator('unsafe').count(),0);
  assert.equal(await page.locator('.notam-reader,[id$="-all"]').count(),0);
  assert.equal(await page.evaluate(()=>NotamReader.records('KMEM',ends('MEM')).length),3);
  assert.equal(await page.evaluate(()=>NotamReader.records('KMEM',ends('MEM')).some(n=>n.text==='SYNTHETIC unmatched source record')),true);
  const all=page.locator('#airport-notams-KMEM');assert.match(await all.locator('summary').textContent(),/All airport snapshot notices \(3\)/);
  assert.match(await all.textContent(),/LOCAL_FORMAT text unavailable/);assert.doesNotMatch(await all.textContent(),/unmatched source record/);
  await page.evaluate(()=>{metars.MEM={observed:'2026-11-12T23:59:00Z',wind:{direction:100,speed:5}};airports.push('LAX');metars.LAX={observed:'2026-11-13T00:01:00Z',wind:{direction:200,speed:8}};render();});
  await page.selectOption('#time-MEM','2026-11-12T23:59:00Z');await page.focus('#time-MEM');await page.evaluate(()=>render());
  assert.equal(await page.locator('#time-MEM').inputValue(),'2026-11-12T23:59:00Z');assert.equal(await page.locator('#time-LAX').inputValue(),'2026-11-13T00:01:00Z');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'time-MEM');
  assert.match(await page.locator('#time-MEM').innerText(),/2026-11-12 23:59Z/);assert.match(await page.locator('#time-LAX').innerText(),/2026-11-13 00:01Z/);
  assert.equal(await page.locator('#time-MEM option:not([disabled])').count(),1);
  assert.match(await page.locator('.taf').first().innerText(),/unavailable/i);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);assert.ok(external.every(url=>/^https:\/\/fonts\.(googleapis|gstatic)\.com\//.test(url)),external.join(', '));
 }finally{await context.close();}
});
