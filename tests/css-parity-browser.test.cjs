'use strict';
// Compare the current visual result to SPA-67's pre-refactor CSS.
// Reference styles are read from a pinned commit, not from external providers.
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const {PNG}=require('pngjs');
const pixelmatch=require('pixelmatch');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8798';
const baseline='5120d81945787a5c80da738bf5e086a4105e0a1c';
const original=Object.fromEntries(['index.html','styles.css','dashboard.css','charcoal-dashboard.css'].map(p=>
 [p,execFileSync('git',['show',baseline+':'+p],{encoding:'utf8'})]));
const freeze=Date.parse('2026-11-20T07:00:00Z');
let server,browser;
before(async()=>{
 server=spawn('python3',['-B','-m','http.server','8798','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<80;i++){
  try{if((await fetch(origin)).ok)break;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});

async function launch(width,legacy){
 const context=await browser.newContext({viewport:{width,height:950},reducedMotion:'reduce'});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await context.addInitScript(time=>{
  const NativeDate=Date;
  class FrozenDate extends NativeDate{
   constructor(...args){super(...(args.length?args:[time]));}
   static now(){return time;}
  }
  window.Date=FrozenDate;
  localStorage.setItem('spatchin-airports','["MEM","IND","OAK"]');
 },freeze);
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.origin!==origin)return route.abort();
  const file=u.pathname==='/'?'index.html':u.pathname.slice(1);
  if(legacy&&Object.prototype.hasOwnProperty.call(original,file))
   return route.fulfill({status:200,contentType:file.endsWith('.css')?'text/css':'text/html',body:original[file]});
  return route.continue();
 });
 await page.goto(origin,{waitUntil:'load'});
 await page.waitForSelector('[data-airport="MEM"] .runway-row');
 return {context,page,errors};
}
async function state(page,name){
 if(name==='scan'||name==='reader'){
  await page.locator('#scan-toggle').click();
  await page.locator('#scan-terms').fill('RWY, METAR');
  await page.waitForFunction(()=>document.querySelectorAll('mark[data-scan-match]').length>0);
 }
 if(name==='reader'){
  const b=page.locator('[data-airport="MEM"] [data-reader-open]').first();
  await b.click();
  await page.waitForFunction(()=>document.querySelector('[data-airport="MEM"] [data-reader-open][aria-expanded="true"]'));
 }
}
async function imageOf(page){
 await page.evaluate(()=>document.fonts.ready);
 return PNG.sync.read(await page.screenshot({fullPage:true,animations:'disabled'}));
}
async function render(width,name,legacy){
 const app=await launch(width,legacy);
 await state(app.page,name);
 const png=await imageOf(app.page);
 const computed=await app.page.evaluate(()=>{
  const s=sel=>getComputedStyle(document.querySelector(sel));
  const sels=['body','header','.brand','.brand-wordmark','.clock','.dashboard-controls','.scan-toolbar','#scan-toggle','#scan-terms','.toolbar','#iata','.cards','.airport','.airport-head','.airport-top-row','.icao','.category-tag','.airport-grip','.airport-remove','.metar-panel','.metar-raw','.taf','.atis','.atis-box','.notam-summary','.time-control','.rw-table','.runway-row td','.airport-footer','.sources','footer'];
  return Object.fromEntries(sels.filter(sel=>document.querySelector(sel)).map(sel=>{
   const x=s(sel),b=document.querySelector(sel).getBoundingClientRect();
   return [sel,{display:x.display,font:x.font,fontFamily:x.fontFamily,lineHeight:x.lineHeight,
   color:x.color,backgroundColor:x.backgroundColor,border:x.border,borderRadius:x.borderRadius,
   boxShadow:x.boxShadow,backgroundImage:x.backgroundImage,padding:x.padding,margin:x.margin,
   gap:x.gap,alignItems:x.alignItems,justifyContent:x.justifyContent,position:x.position,
   width:Math.round(b.width*100)/100,height:Math.round(b.height*100)/100}];
  }));
 });
 const errors=app.errors.slice();
 await app.context.close();
 return {png,computed,errors};
}
for(const width of [1440,1120,760,390,320]){
 for(const scene of width===1440||width===390?['default','scan','reader']:['default']){
  test('SPA-68 CSS parity '+width+'px '+scene,async()=>{
   const before=await render(width,scene,true),after=await render(width,scene,false);
   assert.deepEqual(before.errors,[]);assert.deepEqual(after.errors,[]);
   assert.deepEqual(after.computed,before.computed,'Computed style differs at '+width+' '+scene);
   assert.equal(after.png.width,before.png.width,'Screenshot width differs');
   assert.equal(after.png.height,before.png.height,'Screenshot height differs');
   const difference=pixelmatch(before.png.data,after.png.data,null,before.png.width,before.png.height,{threshold:.02,includeAA:false});
   assert.equal(difference,0,'Screenshot differs by '+difference+' pixels at '+width+' '+scene);
  });
 }
}
