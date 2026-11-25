'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');

const origin='http://127.0.0.1:8787';
let server,browser;

before(async()=>{
 server=spawn(process.env.PYTHON||'python3',['-B','-m','http.server','8787','--bind','127.0.0.1'],{stdio:'ignore'});
 for(let attempt=0;attempt<80;attempt++){
  try{if((await fetch(origin)).ok)break;}catch{}
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
});
after(async()=>{await browser?.close();server?.kill();});

const tokens={
 '--bg':'#1b1d1f','--panel2':'#151617','--line':'#3a3d40',
 '--text':'#e6e6e1','--muted':'#a3a6a8','--blue':'#4fd1e6',
 '--amber':'#ffb000','--green':'#b4e33d','--red':'#ff6b6b',
 '--flight-vfr':'#b4e33d','--flight-mvfr':'#4fd1e6',
 '--flight-ifr':'#ff6b6b','--flight-lifr':'#ff4fd8'
};

for(const width of [1440,1120,760,390,320])test('SPA-65 computed UI contract at '+width+'px',async()=>{
 const context=await browser.newContext({viewport:{width,height:1000}});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 // No aviation provider or external font requests: use only localhost.
 await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
 await context.addInitScript(()=>localStorage.setItem('spatchin-airports','["MEM","IND","OAK"]'));
 try{
  await page.goto(origin+'/dashboard/');
  await page.waitForSelector('[data-airport="MEM"] .metar-panel');
  await page.waitForSelector('[data-airport="MEM"] .runway-row td');
  const ui=await page.evaluate(()=>{
   const s=selector=>getComputedStyle(document.querySelector(selector));
   const prop=(selector,name)=>s(selector)[name];
   const rect=selector=>document.querySelector(selector).getBoundingClientRect();
   const root=getComputedStyle(document.documentElement);
   return {
    tokens:Object.fromEntries(['--bg','--panel2','--line','--text','--muted','--blue','--amber','--green','--red','--flight-vfr','--flight-mvfr','--flight-ifr','--flight-lifr'].map(k=>[k,root.getPropertyValue(k).trim()])),
    bg:prop('body','backgroundColor'),
    panel:prop('[data-airport="MEM"]','backgroundColor'),
    metar:prop('[data-airport="MEM"] .metar-panel','backgroundColor'),
    border:prop('[data-airport="MEM"]','borderTopColor'),
    borderWidth:prop('[data-airport="MEM"]','borderTopWidth'),
    metarBorder:prop('[data-airport="MEM"] .metar-panel','borderTopWidth'),
    runwayDivider:prop('[data-airport="MEM"] .runway-row td','borderBottomWidth'),
    radius:prop('[data-airport="MEM"]','borderTopLeftRadius'),
    metarRadius:prop('[data-airport="MEM"] .metar-panel','borderTopLeftRadius'),
    backgroundImages:['body','header','.airport','.atis','.scan-toolbar'].map(sel=>prop(sel,'backgroundImage')),
    cardShadow:prop('[data-airport="MEM"]','boxShadow'),
    columns:prop('.cards','gridTemplateColumns').split(' ').length,
    cardGap:prop('.cards','columnGap'),
    mainSide:prop('main','paddingLeft'),
    cardSide:prop('.airport','paddingLeft'),
    controlMargin:prop('.dashboard-controls','marginBottom'),
    icaoFont:prop('.icao','fontFamily'),
    icaoSize:parseFloat(prop('.icao','fontSize')),
    nameSize:parseFloat(prop('.airport-head .name','fontSize')),
    nameColor:prop('.airport-head .name','color'),
    bodyFont:prop('body','fontFamily'),
    metarFont:prop('.metar-raw','fontFamily'),
    metarSize:parseFloat(prop('.metar-raw','fontSize')),
    metarLine:parseFloat(prop('.metar-raw','lineHeight')),
    metarSide:prop('.metar-panel','paddingLeft'),
    scanLabelColor:prop('.scan-title','color'),
    sourceLinkColor:prop('.airport-diagram a','color'),
    grip:{width:rect('.airport-grip').width,height:rect('.airport-grip').height},
    remove:{width:rect('.airport-remove').width,height:rect('.airport-remove').height},
    overflow:document.documentElement.scrollWidth-innerWidth,
    headerPositions:(()=>{
     const brand=document.querySelector('header .brand').getBoundingClientRect();
     const time=document.querySelector('header .header-right').getBoundingClientRect();
     return {brandBottom:brand.bottom,clockTop:time.top,clockRight:time.right};
    })(),
    hasStrip:document.querySelectorAll('.flight-strip,.flight-segment').length
   };
  });
  assert.deepEqual(ui.tokens,tokens);
  assert.equal(ui.bg,'rgb(27, 29, 31)');
  assert.equal(ui.panel,'rgb(27, 29, 31)');
  assert.equal(ui.metar,'rgb(21, 22, 23)');
  assert.equal(ui.border,'rgb(58, 61, 64)');
  assert.equal(ui.borderWidth,'1px');
  assert.equal(ui.metarBorder,'1px');
  assert.equal(ui.runwayDivider,'1px');
  assert.equal(ui.radius,'0px');
  assert.equal(ui.metarRadius,'0px');
  assert.ok(ui.backgroundImages.every(v=>v==='none'),ui.backgroundImages.join(','));
  assert.equal(ui.cardShadow,'none');
  assert.equal(ui.columns,width>1120?3:width>760?2:1);
  assert.equal(ui.cardGap,width>760?'16px':'14px');
  assert.equal(ui.mainSide,width>760?'28px':'14px');
  assert.equal(ui.cardSide,width>760?'22px':width>400?'16px':'12px');
  assert.equal(ui.controlMargin,width>760?'40px':'22px');
  assert.match(ui.icaoFont,/Inconsolata/);
  assert.match(ui.metarFont,/Inconsolata/);
  assert.match(ui.bodyFont,/Overpass/);
  assert.equal(ui.icaoSize,width>1300?60:width>760?56:width>400?54:48);
  assert.equal(ui.nameSize,width>400?18:17);
  assert.equal(ui.nameColor,'rgb(163, 166, 168)');
  assert.equal(ui.metarSize,width>400?21:20);
  assert.ok(Math.abs(ui.metarLine/ui.metarSize-1.6)<.01);
  assert.equal(ui.metarSide,width>760?'14px':'12px');
  assert.equal(ui.scanLabelColor,'rgb(255, 176, 0)');
  assert.equal(ui.sourceLinkColor,'rgb(79, 209, 230)');
  assert.deepEqual(ui.grip,{width:44,height:44});
  assert.deepEqual(ui.remove,{width:44,height:44});
  assert.equal(ui.hasStrip,0);
  assert.ok(ui.overflow<=1,'horizontal overflow '+ui.overflow+'px at '+width);
  if(width<=340){
   assert.ok(ui.headerPositions.clockTop>=ui.headerPositions.brandBottom-1,'UTC clock wraps below logo on very narrow screens');
   assert.ok(ui.headerPositions.clockRight<=width-5,'UTC clock remains within page');
  }
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
