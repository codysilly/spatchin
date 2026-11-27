'use strict';
// White-box test adapters only. The real dashboard exposes only the mount/preview API.
// Browser routes instrument the local module; no test state is added to production code.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');
const {join}=require('node:path');
const root=join(__dirname,'..');
const read=name=>readFileSync(join(root,name),'utf8');
const boundary='return {render,refreshNotams:()=>notamSnapshots?.refresh()};';
function instrument(source,insertion){
 assert.equal(source.split(boundary).length,2,'dashboard mount return boundary');
 return source.replace(boundary,()=>insertion+'\n'+boundary);
}
function mountInVM(context,dependencies=[]){
 // Execute the exported factory in the existing VM realm with the original DOM,
 // clock, transport and storage stubs. Load only the requested module dependencies.
 // Load the real diagram module in the same realm as the instrumented factory.
 vm.runInContext(read('airport-diagrams.js').replace(/^export function /gm,'function '),context,{filename:'airport-diagrams.js'});
 const bindings=[];
 for(const [file,names] of dependencies){
  const source=read(file);
  for(const name of names)assert.ok(source.includes('export const '+name),'missing native export '+name);
  vm.runInContext(source.replace(/^export const /gm,'const '),context,{filename:file});
  bindings.push(...names);
 }
 const {mountDashboard}=require('../app.js');
 const source=instrument(mountDashboard.toString(),'return {run:source=>eval(source)};');
 return vm.runInContext("'use strict';("+source+")({"+bindings.join(',')+"})",context,{filename:'app.js'});
}
const readonly=['AirportCatalog','AirportMetadata','NotamReader','NotamSnapshots','SPATCHIN_SYNTHETIC_PREVIEW',
 'metars','loading','forecastReader','forecastTimeline','tafData','notamTransport','notamSnapshots',
 'render','save','ends','icao','diagramHeader','metarBadge','refresh','refreshAtis','refreshRunways','windLabel','runwayBearingLabel'];
const writable=['airports','runwayData','atisData','atisRetrieved'];
async function installDashboardProbe(page,origin){
 const descriptors=[...readonly.map(name=>name+':{configurable:true,get:()=>'+name+'}'),
  ...writable.map(name=>name+':{configurable:true,get:()=>'+name+',set:value=>{'+name+'=value}}')].join(',');
 const source=instrument(read('app.js'),'Object.defineProperties(globalThis,{'+descriptors+'});');
 await page.route(url=>url.origin===origin&&url.pathname==='/app.js',
  route=>route.fulfill({status:200,contentType:'text/javascript',body:source}));
}
async function loadStandaloneModule(page,file,names){
 await page.evaluate(async({source,names})=>{
  const url=URL.createObjectURL(new Blob([source],{type:'text/javascript'}));
  try{const module=await import(url);for(const name of names)globalThis[name]=module[name];}
  finally{URL.revokeObjectURL(url);}
 },{source:read(file),names});
}
module.exports={mountInVM,installDashboardProbe,loadStandaloneModule};
