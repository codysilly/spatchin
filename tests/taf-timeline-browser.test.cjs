'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const base='http://127.0.0.1:8786';let server,browser;
before(async()=>{
 server=spawn('python3',['-B','-m','http.server','8786','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<70;i++){
  try{if((await fetch(base)).ok)break;}catch{}
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});
const fmt=ms=>new Date(ms).toISOString().slice(0,16);
for(const width of [1440,390])test('forecast UTC controls, source and runway components at '+width+'px',async()=>{
 const now=Date.now(),HOUR=3600000;
 const issued=now-HOUR,from=now-3*HOUR,to=now+22*HOUR;
 const fmAt=now+2*HOUR,tempoAt=now+4*HOUR,probAt=now+6*HOUR;
 const epoch=ms=>Math.floor(ms/1000);
 const forecast={icaoId:'KMEM',issueTime:new Date(issued).toISOString(),
  validTimeFrom:epoch(from),validTimeTo:epoch(to),
  rawTAF:'TAF KMEM SYNTHETIC 27012KT FM 09010KT TEMPO 20020G30KT',
  fcsts:[
   {timeFrom:epoch(from),timeTo:epoch(to),fcstChange:null,wdir:270,wspd:12,wgst:18},
   {timeFrom:epoch(fmAt),timeTo:epoch(to),fcstChange:'FM',wdir:90,wspd:10,wgst:null},
   {timeFrom:epoch(tempoAt),timeTo:epoch(tempoAt+2*HOUR),fcstChange:'TEMPO',wdir:200,wspd:20,wgst:30},
   {timeFrom:epoch(probAt),timeTo:epoch(probAt+2*HOUR),fcstChange:'PROB',probability:30,wdir:160,wspd:16,wgst:26},
  ]};
 const context=await browser.newContext({viewport:{width,height:1000}});
 await context.addInitScript(()=>localStorage.setItem('spatchin-airports','["MEM","IND"]'));
 const page=await context.newPage(),errors=[],external=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(url.origin===base)return route.continue();
  external.push(url.href);return route.abort();
 });
 await context.route('**/data/tafs.json?*',route=>route.fulfill({json:{
  updated_utc:new Date(now).toISOString(),
  source:'https://aviationweather.gov/api/data/taf?ids=KORD,KLAX,KJFK,KMEM&format=json',
  tafs:[forecast]
 }}));
 await context.route('**/data/metars.json?*',route=>route.fulfill({json:{
  updated_utc:new Date(now).toISOString(),
  metars:[{icaoId:'KMEM',obsTime:epoch(now-5*60000),wdir:90,wspd:5,wgst:null,fltCat:'VFR',
   rawOb:'METAR KMEM SYNTHETIC 09005KT'}]
 }}));
 await context.route('**/data/notams.json*',route=>route.fulfill({json:{retrieved_utc:new Date(now).toISOString(),
  airports:{KMEM:{completeness:'UNKNOWN',notices:[]}}}}));
 try{
  await page.goto(base+'/dashboard/');
  await page.waitForFunction(()=>typeof TafTimeline!=='undefined'&&tafData?.tafs?.[0]?.fcsts?.length===4);
  const mem=page.locator('[data-airport="MEM"]');
  assert.match(await mem.locator('.taf-raw').innerText(),/SYNTHETIC 27012KT/);
  assert.match(await mem.locator('.taf-meta').innerText(),/Issued/);
  assert.match(await mem.locator('.taf-meta').innerText(),/Valid/);
  assert.equal(await page.locator('[data-airport="IND"] [data-forecast-controls]').count(),0);
  assert.equal(await mem.locator('.runway-row').count(),8);
  const observed=await mem.locator('.runway-row').first().locator('td').nth(1).innerText();
  assert.equal(await page.locator('#time-MEM option:not([disabled])').count(),2);
  await page.selectOption('#time-MEM',{index:1});
  assert.equal(await mem.locator('.forecast-table').count(),1);
  assert.match(await mem.locator('.forecast-summary').innerText(),/TAF FORECAST/);
  assert.match(await mem.locator('.forecast-summary').innerText(),/270° \/ 12G18KT/);
  const projected=await mem.locator('.runway-row').first().locator('td').nth(1).innerText();
  assert.notEqual(projected,observed);
  await page.fill('#forecast-date-MEM',fmt(fmAt+5*60000));
  assert.match(await mem.locator('.forecast-summary').innerText(),/090° \/ 10KT/);
  await page.fill('#forecast-date-MEM',fmt(tempoAt+5*60000));
  assert.match(await mem.locator('.forecast-summary').innerText(),/TEMPO/);
  assert.match(await mem.locator('.forecast-alt').first().innerText(),/TEMPO/);
  await page.fill('#forecast-date-MEM',fmt(probAt+5*60000));
  assert.match(await mem.locator('.forecast-alt').first().innerText(),/PROB 30%/);
  await page.locator('#forecast-slider-MEM').evaluate(el=>{
   el.value='2';el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
  });
  assert.match(await mem.locator('.forecast-summary').innerText(),/TAF FORECAST/);
  await page.selectOption('#time-MEM',{index:0});
  assert.equal(await mem.locator('.forecast-table').count(),0);
  assert.equal(await mem.locator('.runway-row').first().locator('td').nth(1).innerText(),observed);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)<=1);
  // Verify raw TAF status and forecast availability use the same six-hour cutoff.
  await page.evaluate(()=>{
   const report=tafData.tafs.find(item=>item.icaoId==='KMEM');
   report.issueTime=new Date(Date.now()-6*3600000-60000).toISOString();
   render();
  });
  assert.match(await mem.locator('.taf-status').innerText(),/TAF STALE/);
  assert.equal(await mem.locator('#time-MEM option:not([disabled])').count(),1);
  await page.evaluate(()=>{
   const report=tafData.tafs.find(item=>item.icaoId==='KMEM');
   report.issueTime=new Date(Date.now()-6*3600000+60000).toISOString();
   render();
  });
  assert.match(await mem.locator('.taf-status').innerText(),/TAF CURRENT/);
  assert.equal(await mem.locator('#time-MEM option:not([disabled])').count(),2);
  // Expired validity is not a stale issue: keep raw text, show red and disable projections.
  await page.evaluate(()=>{
   const report=tafData.tafs.find(item=>item.icaoId==='KMEM');
   report.issueTime=new Date(Date.now()-90*60000).toISOString();
   report.validTimeTo=Math.floor((Date.now()-60*60000)/1000);
   render();
  });
  assert.equal(await mem.locator('.taf-status').innerText(),'NO LONGER VALID');
  assert.equal(await mem.locator('.taf-status').evaluate(el=>getComputedStyle(el).color),'rgb(255, 107, 107)');
  assert.match(await mem.locator('.taf-raw').innerText(),/SYNTHETIC 27012KT/);
  assert.equal(await mem.locator('#time-MEM option:not([disabled])').count(),1);
  assert.deepEqual(errors,[]);
  assert.ok(external.every(url=>/fonts\.(googleapis|gstatic)\.com/.test(url)),external.join(', '));
 }finally{await context.close();}
});
