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
  await page.goto(origin+'/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
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
