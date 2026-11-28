const {installDashboardProbe}=require('./dashboard-module-support.cjs');
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {pythonCommand}=require('./python-launcher.cjs');
const {chromium}=require('playwright');
const {readFileSync,mkdirSync}=require('node:fs');
const {join}=require('node:path');
const {tmpdir}=require('node:os');
const offlineFont='https://fonts.googleapis.com/css2?family=Inconsolata:wght@400;700&family=Overpass:wght@400;600;700;800&display=swap';
const base='http://127.0.0.1:8768';let server,browser;
before(async()=>{
 server=spawn(pythonCommand(),['-B','-m','http.server','8768','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<50;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});
const fixture=()=>({retrieved_utc:'2026-11-11T12:00:00Z',airports:{KMEM:{completeness:'UNKNOWN',notices:[{id:'SYNTHETIC',text:'SYNTHETIC RWY 18L lighting report',source:'Local test fixture',effectiveEnd:'PERM',formatted_texts:[{type:'LOCAL_FORMAT',text:'SYNTHETIC RWY 18L lighting report'}]}]}}});
const inventory=['09','27','18L','36R','18C','36C','18R','36L'];
for(const width of [1440,390])test(`same-origin snapshot flow, retained failures, SCAN and MEM inventory at ${width}px`,async()=>{
 const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),external=[],errors=[];let mode='good',requests=0;
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();if(route.request().url()===offlineFont)return route.fulfill({status:200,contentType:'text/css',body:''});external.push(route.request().url());return route.abort();});
 await context.route('**/data/notams.json',route=>{
  requests++;if(mode==='error')return route.fulfill({status:503,body:'private error body'});
  const data=fixture();if(mode==='bad')data.airports.KMEM.notices={};if(mode==='synthetic')data.synthetic=true;
  return route.fulfill({json:data});
 });
 await context.route('**/data/metars.json?*',route=>route.fulfill({json:{updated_utc:new Date().toISOString(),metars:[]}}));
 const runways=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));
 // Keep the actual magnetic snapshot and independently verify the eight MEM ends.
 assert.deepEqual(runways.airports.MEM.map(end=>end.id).sort(),[...inventory].sort());
 await context.route('**/data/runways.json?*',route=>route.fulfill({json:runways}));
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await installDashboardProbe(page,base);await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof render==='function');await page.waitForFunction(()=>notamTransport?.checked_utc&&!notamTransport.refreshing&&ends('MEM').length===8);
  assert.equal(requests,1);assert.equal(await page.locator('.rw-table > tbody > tr.runway-row').count(),8);
  await page.locator('[data-reader-open="KMEM-18L"]').click();
  const panel=page.locator('#reader-KMEM-18L');assert.match(await panel.innerText(),/lighting report/);
  await panel.locator('[data-reader-scroll]').focus();
  const prefs=await page.evaluate(()=>[localStorage.getItem('spatchin-airports'),localStorage.getItem('spatchin-scan-v1')]);
  mode='error';await page.evaluate(()=>notamSnapshots.refresh());
  assert.equal(await panel.getAttribute('hidden'),null);assert.equal(await page.evaluate(()=>document.activeElement.id),'scroll-KMEM-18L');
  assert.match(await page.locator('.notam-summary').innerText(),/retained snapshot/);assert.match(await panel.innerText(),/lighting report/);
  assert.deepEqual(await page.evaluate(()=>[localStorage.getItem('spatchin-airports'),localStorage.getItem('spatchin-scan-v1')]),prefs);
  await page.locator('#scan-toggle').click();await page.locator('#scan-terms').fill('lighting report');await page.waitForFunction(()=>document.querySelectorAll('#cards mark').length>0);
  for(let i=0;i<await page.locator('#cards mark[data-scan-match]').count()&&!(await page.locator('#reader-KMEM-18L .scan-current').count());i++)await page.locator('#scan-next').click();assert.ok(await page.locator('#reader-KMEM-18L .scan-current').count()>0);
  for(const bad of ['bad','synthetic']){mode=bad;await page.evaluate(()=>notamSnapshots.refresh());assert.match(await page.locator('.notam-summary').innerText(),/retained snapshot/);}
  mode='good';await page.locator('[data-notam-reload]').click();await page.waitForFunction(()=>notamTransport&&!notamTransport.refreshing&&!notamTransport.error);
  assert.equal(await page.evaluate(()=>document.activeElement.dataset.notamReload),'MEM');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const output=join(tmpdir(),'spatchin-snapshot-review');mkdirSync(output,{recursive:true});await page.screenshot({path:join(output,`${width}.png`),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{await context.close();}
});
test('first-load 404 is unavailable; absent MEM inventory does not fabricate runway ends',async()=>{
 const context=await browser.newContext(),page=await context.newPage();
 await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
 await context.route('**/data/notams.json',route=>route.fulfill({status:404,body:''}));
 const legacy=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));delete legacy.airports.MEM;delete legacy.airport_metadata;
 await context.route('**/data/runways.json?*',route=>route.fulfill({json:legacy}));
 try{await installDashboardProbe(page,base);await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof render==='function');await page.waitForFunction(()=>notamTransport?.error);assert.match(await page.locator('.notam-summary').innerText(),/NOTAM data unavailable/i);assert.equal(await page.locator('.rw-table > tbody > tr.runway-row').count(),0);assert.match(await page.locator('#cards').innerText(),/Runway data pending/);}finally{await context.close();}
});
for(const width of [1440,390])test(`published MEM NASR inventory and source provenance at ${width}px`,async()=>{
 const runways=JSON.parse(readFileSync(join(__dirname,'../data/runways.json'),'utf8'));
 const context=await browser.newContext({viewport:{width,height:1000}}),page=await context.newPage(),external=[],errors=[];
 await context.route('**/*',route=>{if(new URL(route.request().url()).origin===base)return route.continue();if(route.request().url()===offlineFont)return route.fulfill({status:200,contentType:'text/css',body:''});external.push(route.request().url());return route.abort();});
 await context.route('**/data/metars.json?*',route=>route.fulfill({json:{updated_utc:new Date().toISOString(),metars:[]}}));
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await installDashboardProbe(page,base);await page.goto(base+'/dashboard/');await page.waitForFunction(()=>typeof render==='function');await page.waitForFunction(()=>document.querySelectorAll('.rw-table > tbody > tr.runway-row').length===8);
  assert.deepEqual(await page.locator('.rw-table > tbody > tr.runway-row td:first-child').allTextContents(),['09','18C','18L','18R','27','36C','36L','36R']);
  assert.deepEqual(await page.locator('.rw-table > tbody > tr.runway-row > td:nth-child(2), .rw-table > tbody > tr.runway-row > td:nth-child(3)').allTextContents(),Array(16).fill('—'));
  // Bearing tooltips apply to computed components; supply wind only in this test.
  await page.evaluate(()=>{metars.MEM.wind={direction:100,speed:10};render();});
  for(const end of runways.airports.MEM){
   assert.equal(await page.locator('.rw-table > tbody > tr.runway-row td:first-child').filter({hasText:new RegExp(`^${end.id}$`)}).getAttribute('title'),`Approximate magnetic runway heading: ${end.magnetic_heading}°`);
  }
  assert.doesNotMatch(await page.locator('.runways').innerText(),/Approx. wind components/);
  assert.equal(await page.locator('.runways .sub').count(),0);
  assert.equal(await page.locator('[data-expand],.details,.notam-reader').count(),0);
  assert.equal(await page.evaluate(()=>runwayData.source_url),runways.source_url);
  assert.equal(await page.locator('.airport-head [data-remove="MEM"]').count(),1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await page.evaluate(()=>localStorage.getItem('spatchin-airports')),null);
  const output=join(tmpdir(),'spatchin-mem-review');mkdirSync(output,{recursive:true});await page.screenshot({path:join(output,`${width}.png`),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 }finally{await context.close();}
});
