'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {pythonCommand}=require('./python-launcher.cjs');
const {chromium}=require('playwright');
const {mkdirSync}=require('node:fs');

const origin='http://127.0.0.1:8787';
let server,browser;

before(async()=>{
 server=spawn(pythonCommand(),['-B','-m','http.server','8787','--bind','127.0.0.1'],{stdio:'ignore'});
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
    topPadding:prop('.airport','paddingTop'),
    nameLine:prop('.airport-head .name','lineHeight'),
    geometry:(()=>{const code=rect('.icao'),badge=rect('.category-tag'),name=rect('.name'),row=rect('.airport-top-row'),head=rect('.airport-head'),metar=rect('.metar-panel'),scan=rect('#scan-toggle'),add=rect('#add-form button'),input=rect('#iata'),controls=rect('.dashboard-controls'),cards=rect('.cards');return {codeGap:badge.left-code.right,bottomGap:code.bottom-badge.bottom,nameGap:name.top-code.bottom,metarGap:metar.top-name.bottom,rowHeight:row.height,headTop:head.top,gripBottom:rect('.airport-grip').bottom,removeBottom:rect('.airport-remove').bottom,metarTop:metar.top,scanHeight:scan.height,addHeight:add.height,inputHeight:input.height,scanTop:scan.top,addTop:add.top,inputTop:input.top,controlGap:cards.top-controls.bottom,scanRight:scan.right,inputLeft:input.left};})(),
    nameOverflow:prop('.name','textOverflow'),nameWhitespace:prop('.name','whiteSpace'),
    icaoFont:prop('.icao','fontFamily'),
    icaoSize:parseFloat(prop('.icao','fontSize')),
    nameSize:parseFloat(prop('.airport-head .name','fontSize')),
    nameColor:prop('.airport-head .name','color'),
    bodyFont:prop('body','fontFamily'),
    metarFont:prop('.metar-raw','fontFamily'),
    metarSize:parseFloat(prop('.metar-raw','fontSize')),
    metarLine:parseFloat(prop('.metar-raw','lineHeight')),
    metarSide:prop('.metar-panel','paddingLeft'),
    categorySize:prop('.category-tag','fontSize'),categoryMargin:prop('.category-tag','marginLeft'),
    panelStyles:['.metar-panel','.taf','.atis'].map(sel=>({width:rect(sel).width,padding:prop(sel,'padding'),border:prop(sel,'border'),background:prop(sel,'backgroundColor'),margin:prop(sel,'margin')})),
    atisStyles:['.atis-top h3','.atis-meta','.atis-label','.atis-value','.atis-full summary'].map(sel=>({size:prop(sel,'fontSize'),line:prop(sel,'lineHeight'),weight:prop(sel,'fontWeight'),font:prop(sel,'fontFamily')})),
    headerHeight:rect('header').height,
    logoSize:rect('.brand-logo').height,
    tafSize:document.querySelector('.taf-raw')?parseFloat(prop('.taf-raw','fontSize')):null,
    tafLine:document.querySelector('.taf-raw')?parseFloat(prop('.taf-raw','lineHeight')):null,
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
  assert.equal(ui.controlMargin,'0px');
  assert.equal(ui.topPadding,'9px');
  const g=ui.geometry;
  assert.ok(g.codeGap>=8&&g.codeGap<=10,JSON.stringify(g));
  assert.ok(Math.abs(g.bottomGap-5)<=.1,JSON.stringify(g));
  assert.ok(g.nameGap>=3.9&&g.nameGap<=6,JSON.stringify(g));
  assert.ok(g.metarGap>=7.9&&g.metarGap<=10,JSON.stringify(g));
  assert.ok(g.rowHeight<30,JSON.stringify(g));
  assert.ok(g.gripBottom<=g.metarTop&&g.removeBottom<=g.metarTop,JSON.stringify(g));
  assert.deepEqual([g.scanHeight,g.addHeight,g.inputHeight],[44,44,44]);
  assert.equal(g.scanTop,g.addTop);assert.equal(g.inputTop,g.addTop);assert.ok(g.scanRight<=g.inputLeft);
  assert.equal(g.controlGap,parseFloat(ui.cardGap));
  assert.equal(ui.nameWhitespace,'nowrap');assert.equal(ui.nameOverflow,'ellipsis');
  assert.match(ui.icaoFont,/Inconsolata/);
  assert.match(ui.metarFont,/Inconsolata/);
  assert.match(ui.bodyFont,/Overpass/);
  assert.equal(ui.icaoSize,24);
  assert.equal(ui.nameSize,12);assert.ok(Math.abs(parseFloat(ui.nameLine)/12-1.15)<.01);
  assert.equal(ui.categorySize,'8px');assert.equal(ui.categoryMargin,'0px');
  assert.deepEqual(ui.panelStyles[1],ui.panelStyles[0]);assert.deepEqual(ui.panelStyles[2],ui.panelStyles[0]);
  for(const [i,style] of ui.atisStyles.entries()){assert.equal(style.size,'15px');assert.equal(style.line,'19.5px');assert.equal(style.weight,i===3?'700':'400');assert.match(style.font,/Inconsolata/);}
  assert.equal(ui.nameColor,'rgb(163, 166, 168)');
  assert.equal(ui.metarSize,15);
  assert.ok(Math.abs(ui.metarLine/ui.metarSize-1.3)<.01);
  assert.equal(ui.metarSide,width>760?'14px':'12px');
  assert.equal(ui.logoSize,18);
  if(width>340)assert.equal(ui.headerHeight,22);
  if(ui.tafSize!==null){assert.equal(ui.tafSize,15);assert.ok(Math.abs(ui.tafLine/ui.tafSize-1.3)<.01);}
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
  const name=page.locator('[data-airport="MEM"] .name');
  assert.equal(await name.getAttribute('title'),await name.textContent());
  assert.equal(await name.getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('label[for="iata"]').count(),0);
  assert.match(await page.locator('#iata').getAttribute('aria-label'),/Add airport/);
  const placeholderFit=await page.locator('#iata').evaluate(el=>{
   const style=getComputedStyle(el),canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
   ctx.font=style.font;
   const text=ctx.measureText(el.placeholder.toUpperCase()).width;
   return {available:el.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)-26,text};
  });
  assert.ok(placeholderFit.available>=placeholderFit.text,JSON.stringify(placeholderFit));
  const hit=await page.locator('[data-airport="MEM"] .airport-head').evaluate(head=>{
   const els=[...head.querySelectorAll('.airport-grip,.airport-remove,.airport-diagram a,.name,.icao,.category-tag')];
   const boxes=els.map(el=>({className:el.className,rect:el.getBoundingClientRect()}));
   return boxes.flatMap((a,i)=>boxes.slice(i+1).filter(b=>a.rect.left<b.rect.right-.5&&a.rect.right>b.rect.left+.5&&a.rect.top<b.rect.bottom-.5&&a.rect.bottom>b.rect.top+.5).map(b=>[a.className,b.className]));
  });
  assert.deepEqual(hit,[]);
  if(width===320)assert.equal(await name.evaluate(el=>el.scrollWidth>el.clientWidth),true);
  mkdirSync('screenshots',{recursive:true});
  await page.screenshot({path:'screenshots/compact-header-'+width+'.png'});
  await name.focus();await name.press('Enter');assert.equal(await name.getAttribute('aria-expanded'),'true');
  assert.equal(await name.evaluate(el=>getComputedStyle(el).whiteSpace),'normal');
  await name.press('Space');assert.equal(await name.getAttribute('aria-expanded'),'false');
  await page.locator('#scan-toggle').click();
  assert.equal(await page.locator('#scan-panel').isVisible(),true);
  const panel=await page.locator('#scan-panel').boundingBox(),toolbar=await page.locator('.dashboard-controls').boundingBox();
  assert.ok(panel.width>=toolbar.width-1,JSON.stringify({panel,toolbar}));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('#scan-terms').fill('SYNTHETIC');
  await page.locator('#scan-toggle').click();
  assert.equal(await page.locator('#scan-panel').isHidden(),true);
  assert.deepEqual(errors,[]);
 }finally{await context.close();}
});
