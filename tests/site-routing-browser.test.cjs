'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8799';
let server,browser;
before(async()=>{
 server=spawn('python3',['-B','-m','http.server','8799','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<80;i++){try{if((await fetch(origin)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});
for(const width of [1440,390])test('public root and routed dashboard '+width+'px',async()=>{
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
  const headline=await page.locator('h1').innerText();
  assert.equal(headline.replace(/\s+/g,' ').trim(),'Not cleared for takeoff… yet.');
  assert.equal(await page.locator('.floating-plane').count(),1);
  assert.equal(await page.locator('#cards').count(),0);
  assert.equal(await page.locator('script[src]').count(),0);
  assert.equal(await page.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(27, 29, 31)');
  assert.ok((await page.locator('.floating-plane').evaluate(el=>el.complete&&el.naturalWidth>0)));
  assert.ok(!requests.includes('/app.js'),'no dashboard code should load at site root');
  requests.length=0;
  await page.goto(origin+'/dashboard/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
  await page.waitForFunction(()=>document.querySelectorAll('[data-airport="MEM"] .runway-row').length===8);
  assert.ok(requests.includes('/app.js'));
  assert.ok(requests.some(p=>p==='/data/metars.json'));
  assert.ok(requests.some(p=>p==='/data/notams.json'));
  assert.ok(requests.includes('/charcoal-dashboard.css'));
  assert.equal(await page.locator('.brand-wordmark').innerText(),'SPATCHIN');
  assert.equal(await page.locator('#scan-toggle').count(),1);
  assert.equal(await page.locator('.wip-banner').count(),1);
  assert.ok((await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth))<=1);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
