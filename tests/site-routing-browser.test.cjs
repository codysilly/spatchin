'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8799';
let server,browser;
before(async()=>{
 server=spawn(process.env.PYTHON||'python3',['-B','-m','http.server','8799','--bind','127.0.0.1'],{stdio:'ignore'});
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
