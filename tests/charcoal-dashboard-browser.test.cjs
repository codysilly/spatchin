'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {mkdirSync}=require('node:fs');
const {chromium}=require('playwright');

const base='http://127.0.0.1:8784';
let server,browser;
before(async()=>{
 server=spawn('python3',['-B','-m','http.server','8784','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<60;i++){
  try{if((await fetch(base)).ok)break;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});

for(const width of [1440,390])test('approved charcoal layout and interactions at '+width+'px',async()=>{
 const context=await browser.newContext({viewport:{width,height:1000}});
 const page=await context.newPage();
 const errors=[],external=[];
 page.on('pageerror',error=>errors.push(error.message));
 await context.route('**/*',route=>{
  if(new URL(route.request().url()).origin===base)return route.continue();
  external.push(route.request().url());return route.abort();
 });
 await context.addInitScript(()=>localStorage.setItem('spatchin-airports','["MEM","IND","OAK"]'));
 const now=new Date();
 await context.route('**/data/metars.json?*',route=>route.fulfill({json:{
  updated_utc:now.toISOString(),
  metars:[{icaoId:'KMEM',obsTime:Math.floor((now.getTime()-120*60000)/1000),
   wdir:150,wspd:6,wgst:null,fltCat:'VFR',rawOb:'SYNTHETIC KMEM 10SM CLR — layout test only'}]
 }}));
 await context.route('**/data/notams.json*',route=>route.fulfill({json:{
  retrieved_utc:now.toISOString(),airports:{KMEM:{completeness:'UNKNOWN',notices:[]}}
 }}));
 try{
  await page.goto(base);
  await page.waitForFunction(()=>document.querySelector('[data-airport="MEM"] .category-vfr'));
  assert.equal(await page.locator('.airport').count(),3);
  assert.equal(await page.locator('[data-airport="MEM"] .category-tag').innerText(),'VFR');
  assert.equal(await page.locator('[data-airport="MEM"] .flight-segment.is-active').innerText(),'VFR');
  assert.equal(await page.locator('[data-airport="MEM"] .flight-segment').count(),4);
  assert.match(await page.locator('[data-airport="MEM"] .metar-status').innerText(),/STALE/);
  for(const code of ['IND','OAK']){
   assert.equal(await page.locator('[data-airport="'+code+'"] .category-tag').innerText(),'NO DATA');
   assert.equal(await page.locator('[data-airport="'+code+'"] .flight-strip').count(),0);
   assert.match(await page.locator('[data-airport="'+code+'"] .empty').innerText(),/Runway data pending/);
  }
  const dom=await page.evaluate(()=>{
   const s=el=>getComputedStyle(document.querySelector(el));
   const boxes=[...document.querySelectorAll('.airport')].map(el=>el.getBoundingClientRect());
   const code=document.querySelector('[data-airport="MEM"] .icao').getBoundingClientRect();
   const diagram=document.querySelector('[data-airport="MEM"] .airport-diagram').getBoundingClientRect();
   return {background:s('body').backgroundColor,borderRadius:s('.airport').borderTopLeftRadius,
    grid:s('.cards').gridTemplateColumns.split(' ').length,
    codeSize:parseFloat(s('.icao').fontSize),
    font:s('.brand-wordmark').fontFamily,
    overflow:document.documentElement.scrollWidth-innerWidth,
    codeDiagramOverlap:code.left<diagram.right&&diagram.left<code.right&&code.top<diagram.bottom&&diagram.top<code.bottom,
    boxes:boxes.map(b=>({width:b.width,left:b.left,right:b.right}))};
  });
  assert.equal(dom.background,'rgb(27, 29, 31)');
  assert.equal(dom.borderRadius,'0px');
  assert.equal(dom.grid,width===1440?3:1);
  assert.ok(dom.codeSize>=62);
  assert.match(dom.font,/Inconsolata/);
  assert.ok(dom.overflow<=1,'horizontal overflow '+dom.overflow+' at '+width+'px');
  assert.equal(dom.codeDiagramOverlap,false,'airport diagram overlaps code');
  const mem=page.locator('[data-airport="MEM"]');
  assert.equal(await mem.locator('.airport-footer [data-notam-reload]').count(),1);
  assert.equal(await mem.locator('.airport-footer [data-remove]').count(),1);
  assert.equal(await mem.locator('.runway-row').count(),8);
  assert.equal(await page.locator('.scan-title').innerText(),'SCAN');
  await page.locator('#scan-toggle').click();
  await page.locator('#scan-terms').fill('SYNTHETIC');
  await page.waitForFunction(()=>document.querySelector('#cards mark'));
  assert.ok(await page.locator('mark[data-scan-match]').count()>=1);
  mkdirSync('screenshots',{recursive:true});
  await page.screenshot({path:'screenshots/charcoal-'+width+'.png',fullPage:true});
  await page.locator('[data-airport="OAK"] [data-remove]').click();
  assert.equal(await page.locator('.airport').count(),2);
  assert.deepEqual(errors,[]);
  assert.ok(external.every(url=>/fonts\.(googleapis|gstatic)\.com/.test(url)),String(external));
 }finally{await context.close();}
});
