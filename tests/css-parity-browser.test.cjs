'use strict';
// Preserve SPA-68's historical zero-difference proof, independently of later features.
// Preserve the SPA-96 proof and compare this worktree with the pre-SPA-106 main.
// Each comparison uses identical pinned data on both sides.
// No external provider or font requests are allowed.
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const {pythonCommand}=require('./python-launcher.cjs');
const {PNG}=require('pngjs');
const pixelmatch=require('pixelmatch');
const {chromium}=require('playwright');
const origin='http://127.0.0.1:8798';
const baseline='5120d81945787a5c80da738bf5e086a4105e0a1c';
const refactored='7a33c2f7ac021cb77b3e118d33a777297c76c868';
const spa96Baseline='defc13157003499d36c0223eff4729e0410ab23e';
const currentBaseline='0c72c300182ff7185da8654300d765e16f2dc83c';
const trees=new Map(),blobs=new Map();
function paths(sha){if(!trees.has(sha))trees.set(sha,new Set(execFileSync('git',['ls-tree','-r','--name-only',sha],{encoding:'utf8'}).trim().split(/\r?\n/)));return trees.get(sha);}
function blob(sha,file){const key=sha+':'+file;if(!blobs.has(key))blobs.set(key,execFileSync('git',['show',key],{maxBuffer:32*1024*1024}));return blobs.get(key);}
const mime={html:'text/html',css:'text/css',js:'text/javascript',json:'application/json',svg:'image/svg+xml',png:'image/png',ico:'image/x-icon',woff2:'font/woff2'};
const freeze=Date.parse('2026-11-20T07:00:00Z');
let server,browser;
before(async()=>{
 server=spawn(pythonCommand(),['-B','-m','http.server','8798','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let i=0;i<80;i++){
  try{if((await fetch(origin)).ok)break;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});

async function launch(width,revision,dataRevision,pagePath='/'){
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
  const sha=file.startsWith('data/')?dataRevision:revision;
  if(!sha)return route.continue();
  if(!paths(sha).has(file))return route.fulfill({status:404,body:''});
  return route.fulfill({status:200,contentType:mime[file.split('.').at(-1)]||'application/octet-stream',body:(()=>{
    const original=blob(sha,file);
    if(sha!==spa96Baseline||file!=='charcoal-dashboard.css')return original;
    let css=original.toString('utf8');
    const changes=[
     ['.reader-note{font-size:11px}','.reader-note{font-size:12px}'],
     ['.runway-row [data-reader-open]{font-size:12px;min-height:36px}','.runway-row [data-reader-open]{font-size:12px;min-height:44px}'],
     ['.time-control select{min-height:36px}','.time-control select{min-height:44px}']
    ];
    for(const [from,to] of changes){
     assert.equal(css.split(from).length,2,'Expected reference CSS rule: '+from);
     css=css.replace(from,to);
    }
    return css;
   })()});
 });
 await page.goto(origin+pagePath,{waitUntil:'load'});
 await page.waitForSelector('[data-airport="MEM"] .runway-row');
 if(pagePath==='/preview/snapshot-loader.html'){
  await page.waitForFunction(()=>notamTransport?.snapshot&&!notamTransport.refreshing);
  assert.deepEqual(await page.locator('link[rel="stylesheet"]').evaluateAll(links=>links.map(link=>link.getAttribute('href'))),['styles.css']);
 }
 await page.waitForLoadState('networkidle');
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
async function render(width,name,revision,dataRevision,pagePath='/'){
 const app=await launch(width,revision,dataRevision,pagePath);
 await state(app.page,name==='preview-error'?'reader':name);
 if(name==='preview-error'){
  await app.page.locator('#preview-state').selectOption('error');
  await app.page.waitForFunction(()=>notamTransport?.error&&notamTransport.snapshot&&!notamTransport.refreshing);
 }
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
  test('CSS parity '+width+'px '+scene,async()=>{
   for(const [label,left,right,data] of [['SPA-68 historical',baseline,refactored,baseline],['SPA-96 unchanged UI',spa96Baseline,currentBaseline,spa96Baseline],['SPA-106 unchanged UI',currentBaseline,null,currentBaseline]]){
   const before=await render(width,scene,left,data),after=await render(width,scene,right,data);
   assert.deepEqual(before.errors,[]);assert.deepEqual(after.errors,[]);
   assert.deepEqual(after.computed,before.computed,label+': computed style differs at '+width+' '+scene);
   assert.equal(after.png.width,before.png.width,'Screenshot width differs');
   assert.equal(after.png.height,before.png.height,'Screenshot height differs');
   const difference=pixelmatch(before.png.data,after.png.data,null,before.png.width,before.png.height,{threshold:.02,includeAA:false});
   assert.equal(difference,0,label+': screenshot differs by '+difference+' pixels at '+width+' '+scene);
   }
  });
 }
}

// The isolated snapshot preview loads only styles.css. Protect that consumer independently.
for(const width of [1440,390]){
 for(const scene of ['default','reader','preview-error']){
  test('SPA-106 standalone snapshot preview parity '+width+'px '+scene,async()=>{
   const pagePath='/preview/snapshot-loader.html';
   const before=await render(width,scene,currentBaseline,currentBaseline,pagePath);
   const after=await render(width,scene,null,currentBaseline,pagePath);
   assert.deepEqual(before.errors,[]);assert.deepEqual(after.errors,[]);
   assert.deepEqual(after.computed,before.computed,'Standalone preview computed styles differ');
   assert.equal(after.png.width,before.png.width,'Standalone preview screenshot width differs');
   assert.equal(after.png.height,before.png.height,'Standalone preview screenshot height differs');
   const difference=pixelmatch(before.png.data,after.png.data,null,before.png.width,before.png.height,{threshold:.02,includeAA:false});
   assert.equal(difference,0,'Standalone preview screenshot differs by '+difference+' pixels');
  });
 }
}
