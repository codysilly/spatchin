'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {pythonCommand}=require('./python-launcher.cjs');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8799';
let server,browser;
before(async()=>{
 server=spawn(pythonCommand(),['-B','-m','http.server','8799','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<80;i++){try{if((await fetch(origin)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});
for(const width of [1440,390])test('public homepage serves live WIP UI '+width+'px',async()=>{
 const context=await browser.newContext({viewport:{width,height:900}});
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);
  return route.continue();
 });
 try{
  const tafResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/data/tafs.json');
  await page.goto(origin+'/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
  await tafResponse;
  await page.waitForFunction(()=>document.querySelectorAll('[data-airport="MEM"] .runway-row').length===8);
  assert.equal((await page.locator('.wip-banner').innerText()).trim(),'WORK IN PROGRESS. Under development and not yet validated.');
  assert.equal(await page.locator('.wip-banner').getAttribute('role'),'note');
  const banner=await page.locator('.wip-banner').evaluate(el=>({size:parseFloat(getComputedStyle(el).fontSize),height:el.getBoundingClientRect().height}));
  assert.ok(banner.size>=16);
  assert.ok(banner.height>=48);
  assert.equal(await page.locator('.brand-wordmark').innerText(),'SPATCHIN');
  assert.equal(await page.locator('#scan-toggle').count(),1);
  assert.equal(await page.locator('#iata').count(),1);
  assert.equal(await page.locator('.holding-banner').count(),0);
  assert.ok(requests.includes('/app.js'));
  assert.ok(requests.includes('/charcoal-dashboard.css'));
  assert.ok(requests.some(p=>p==='/data/metars.json'));
  assert.ok(requests.some(p=>p==='/data/notams.json'));
  assert.ok(requests.some(p=>p==='/data/tafs.json'));
  assert.ok(!requests.includes('/splash.css'));
  assert.ok((await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth))<=1);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});

test('synthetic preview loads current stylesheet without external requests',async()=>{
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 const page=await context.newPage(),errors=[],external=[],missing=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('response',response=>{
  if(new URL(response.url()).origin===origin&&response.status()>=400)missing.push(new URL(response.url()).pathname);
 });
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin){external.push(url.origin);return route.abort();}
  return route.continue();
 });
 try{
  const stylesheet=page.waitForResponse(response=>new URL(response.url()).pathname==='/charcoal-dashboard.css');
  await page.goto(origin+'/preview/');
  assert.equal((await stylesheet).status(),200);
  await page.waitForSelector('.runway-row');
  assert.equal(await page.locator('.runway-row').count(),8);
  assert.match(await page.locator('.synthetic-banner').innerText(),/SYNTHETIC/);
  assert.ok(await page.evaluate(()=>Array.from(document.styleSheets).some(sheet=>sheet.href&&new URL(sheet.href).pathname==='/charcoal-dashboard.css'&&sheet.cssRules.length>0)));
  assert.ok(!missing.includes('/dashboard.css'));
  assert.deepEqual(errors,[]);
  assert.deepEqual(external,[]);
 }finally{await context.close();}
});

for(const entry of ['/','/dashboard/','/preview/','/preview/snapshot-loader.html'])test('SCAN module starts and highlights literal text at '+entry,async()=>{
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);return route.continue();
 });
 try{
  await page.goto(origin+entry);
  await page.waitForFunction(()=>document.querySelector('#scan-keyword-count')?.textContent==='0 active keywords');
  const moduleResult=await page.evaluate(async()=>{
   const mod=await import('/scan.js');
   const fixture=document.createElement('p');
   fixture.id='scan-module-test';
   fixture.textContent='ZQModule+123 zqmodule+123 ZQModule123';
   document.querySelector('main').append(fixture);
   return {exports:Object.keys(mod).sort(),global:typeof window.literalPattern};
  });
  assert.deepEqual(moduleResult,{exports:['literalPattern','matchingKeyword'],global:'undefined'});
  await page.locator('#scan-toggle').click();
  await page.locator('#scan-terms').fill('ZQModule+123');
  await page.waitForFunction(()=>document.querySelectorAll('#scan-module-test mark').length===2);
  await page.locator('#scan-case').check();
  await page.waitForFunction(()=>document.querySelectorAll('#scan-module-test mark').length===1);
  assert.equal(await page.locator('#scan-module-test mark').textContent(),'ZQModule+123');
  assert.equal(requests.filter(path=>path==='/scan.js').length,1);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});

test('forecast modules are private dependencies and a missing reader does not stop other feeds',async()=>{
 const context=await browser.newContext({viewport:{width:1440,height:900}});
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);
  if(url.pathname==='/taf-reader.js')return route.fulfill({status:404,body:'offline missing module'});
  return route.continue();
 });
 try{
  await page.goto(origin+'/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
  await page.waitForFunction(()=>document.querySelectorAll('[data-airport="MEM"] .runway-row').length===8);
  assert.match(await page.locator('[data-airport="MEM"] .taf').innerText(),/Forecast reader unavailable/);
  assert.equal(await page.evaluate(()=>typeof TafReader),'undefined');
  assert.equal(await page.evaluate(()=>typeof TafTimeline),'undefined');
  assert.ok(requests.includes('/taf-reader.js'));
  assert.ok(requests.includes('/taf-timeline.js'));
  assert.ok(requests.includes('/data/metars.json'));
  assert.ok(requests.includes('/data/atis.json'));
  assert.ok(!requests.includes('/data/tafs.json'));
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
test('synthetic previews do not load forecast modules or forecast snapshots',async()=>{
 const context=await browser.newContext();
 const page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);return route.continue();
 });
 try{
  for(const entry of ['/preview/','/preview/snapshot-loader.html']){
   await page.goto(origin+entry);
   await page.waitForSelector('.runway-row');
   await page.waitForLoadState('networkidle');
   assert.match(await page.locator('.synthetic-banner').innerText(),/SYNTHETIC/);
  }
  assert.ok(!requests.some(path=>['/taf-reader.js','/taf-timeline.js','/data/tafs.json'].includes(path)));
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});

test('dashboard starts and airport controls work while forecast module is pending',async()=>{
 const context=await browser.newContext({viewport:{width:390,height:2200},hasTouch:true,isMobile:true});
 const page=await context.newPage(),errors=[],requests=[];
 let release;
 const pending=new Promise(resolve=>{release=resolve;});
 page.on('pageerror',error=>errors.push(error.message));
 await context.addInitScript(()=>localStorage.setItem('spatchin-airports','["IND","OAK"]'));
 await context.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);
  if(url.pathname==='/taf-reader.js')await pending;
  return route.continue();
 });
 try{
  await page.goto(origin+'/dashboard/',{waitUntil:'domcontentloaded'});
  const grip=page.locator('[data-airport="IND"] .airport-grip');
  await grip.waitFor({state:'visible'});
  await page.waitForFunction(()=>document.querySelector('[data-airport="IND"] .metar-raw')?.textContent.includes('KIND')||document.querySelector('[data-airport="IND"] .metar-status')?.textContent==='METAR UNAVAILABLE');
  assert.ok(requests.includes('/data/metars.json'));
  assert.ok(requests.includes('/data/runways.json'));
  assert.ok(requests.includes('/taf-reader.js'));
  assert.ok(!requests.includes('/data/tafs.json'));
  assert.deepEqual(await page.locator('.airport').evaluateAll(els=>els.map(el=>el.dataset.airport)),['IND','OAK']);
  await grip.press('ArrowDown');
  assert.deepEqual(await page.locator('.airport').evaluateAll(els=>els.map(el=>el.dataset.airport)),['OAK','IND']);
  const tafResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/data/tafs.json');
  release();
  await tafResponse;
  await page.waitForFunction(()=>{const taf=document.querySelector('[data-airport="IND"] .taf');return taf&&!taf.textContent.includes('Forecast reader unavailable');});
  assert.deepEqual(await page.locator('.airport').evaluateAll(els=>els.map(el=>el.dataset.airport)),['OAK','IND']);
  assert.deepEqual(errors,[]);
 }finally{release();await context.close();}
});

for(const entry of ['/','/dashboard/','/preview/','/preview/snapshot-loader.html'])test('native dashboard dependencies stay module-scoped at '+entry,async()=>{
 const context=await browser.newContext(),page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);return route.continue();
 });
 try{
  await page.goto(origin+entry);
  await page.waitForSelector('[data-airport="MEM"] .runway-row');
  await page.waitForLoadState('networkidle');
  const app=await page.evaluate(async()=>({
   exports:Object.keys(await import('/app.js')),
   globals:['AirportCatalog','AirportMetadata','NotamReader','NotamSnapshots','mountDashboard','render','airports','metars','notamTransport','SPATCHIN_SYNTHETIC_PREVIEW'].map(name=>typeof globalThis[name])
  }));
  assert.deepEqual(app.exports,['mountDashboard']);
  assert.ok(app.globals.every(type=>type==='undefined'),app.globals.join(','));
  const synthetic=entry.startsWith('/preview/');
  const transportPreview=entry==='/preview/snapshot-loader.html';
  for(const [path,expected] of [['/app.js',true],['/airport-catalog.js',!transportPreview],['/notam-reader.js',true],['/notam-snapshots.js',!synthetic||transportPreview]]){
   assert.equal(requests.filter(p=>p===path).length,expected?1:0,path);
  }
  if(synthetic)assert.ok(!requests.some(path=>['/taf-reader.js','/taf-timeline.js','/data/tafs.json'].includes(path)));
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
test('unavailable catalog and NOTAM snapshot modules preserve independent dashboard feeds',async()=>{
 const context=await browser.newContext(),page=await context.newPage(),errors=[],requests=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin!==origin)return route.abort();
  requests.push(url.pathname);
  if(['/airport-catalog.js','/notam-snapshots.js'].includes(url.pathname))return route.fulfill({status:404,body:'offline missing module'});
  return route.continue();
 });
 try{
  await page.goto(origin+'/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
  await page.waitForLoadState('networkidle');
  assert.deepEqual(await page.locator('#airport-options option').evaluateAll(options=>options.map(option=>option.value)),['MEM','ORD','LAX','JFK']);
  assert.ok(requests.includes('/data/metars.json'));
  assert.ok(requests.includes('/data/runways.json'));
  assert.ok(requests.includes('/data/atis.json'));
  assert.ok(!requests.includes('/data/notams.json'));
  assert.equal(await page.locator('[data-notam-reload]').count(),0);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
