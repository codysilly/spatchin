const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const {chromium}=require('playwright');

for(const width of [1440,390])test(`collection metadata and visible reload warnings survive failure and recovery at ${width}px`,async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||undefined,headless:true});
 const context=await browser.newContext({viewport:{width,height:1000}});
 const page=await context.newPage(),external=[],errors=[];
 await context.route('**/*',route=>{external.push(route.request().url());return route.abort();});
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.setContent('<main id="reader"></main>');
  await page.addStyleTag({content:readFileSync(join(__dirname,'../styles.css'),'utf8')});
  for(const file of ['notam-reader.js','notam-snapshots.js'])await page.addScriptTag({content:readFileSync(join(__dirname,'..',file),'utf8')});
  const result=await page.evaluate(async()=>{
   const warning='Fixed snapshot <unsafe>. Airport coverage UNKNOWN. No automatic updates.';
   const text='SYNTHETIC RWY 18L\r\ntext retained\rverbatim';
   const snapshot={retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{warning,completeness:'UNKNOWN',notices:[{text,source:'NMS-API snapshot',formatted_texts:[{type:'LOCAL_FORMAT',text}]}]}}};
   let failed=false,current;
   const loader=NotamSnapshots.create({baseURL:'https://snapshot.invalid/',fetchFn:async()=>({ok:!failed,status:failed?503:200,json:async()=>snapshot}),onChange:state=>{
    current=state.snapshot;NotamReader.set(state.snapshot,state.error);
    document.getElementById('reader').innerHTML=NotamReader.summary('KMEM')+'<table><tbody>'+NotamReader.row('KMEM','18L',['18L','36R'])+'</tbody></table>';
   }});
   const inspect=()=>({visible:document.getElementById('reader').innerText,text:document.querySelector('#reader-KMEM-18L .reader-raw')?.textContent,storedWarning:current?.airports.KMEM.warning,coverage:current?.airports.KMEM.completeness,availability:NotamReader.availability('KMEM'),injected:document.querySelectorAll('unsafe').length});
   await loader.refresh();const loaded=inspect();
   failed=true;await loader.refresh();const retained=inspect();
   failed=false;await loader.refresh();const recovered=inspect();
   return {loaded,retained,recovered,warning,text,overflow:document.documentElement.scrollWidth>innerWidth};
  });
  for(const stage of [result.loaded,result.retained,result.recovered]){
   assert.equal(stage.storedWarning,result.warning);
   assert.equal(stage.coverage,'UNKNOWN');assert.match(stage.availability,/Coverage UNKNOWN/);
   assert.ok(!stage.visible.includes(result.warning));
   assert.ok(stage.visible.includes('Retrieved: 2020-01-01 00:00 UTC'));
   assert.equal(stage.text,result.text);
   assert.equal(stage.injected,0);
  }
  assert.match(result.retained.visible,/refresh failed \(HTTP 503\)/);
  assert.match(result.retained.visible,/Showing retained snapshot/);
  assert.doesNotMatch(result.loaded.visible,/refresh failed/);
  assert.doesNotMatch(result.recovered.visible,/refresh failed|Showing retained snapshot/);
  assert.equal(result.overflow,false);
  assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 }finally{await context.close();await browser.close();}
});
