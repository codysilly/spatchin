'use strict';
// Spatchin v0.9. METARs loaded from GitHub Pages same-origin JSON. Not for operational dispatch use.
const runwayPairs={ORD:['04L/22R','04R/22L','09L/27R','09R/27L','09C/27C','10L/28R','10C/28C','10R/28L'],LAX:['06L/24R','06R/24L','07L/25R','07R/25L'],JFK:['04L/22R','04R/22L','13L/31R','13R/31L']};
const approvedCatalog=typeof AirportCatalog==='undefined'?Object.keys({MEM:1,ORD:1,LAX:1,JFK:1}):AirportCatalog;
const airportInfo={ORD:{name:'Chicago O’Hare',icao:'KORD'},LAX:{name:'Los Angeles International',icao:'KLAX'},JFK:{name:'John F. Kennedy International',icao:'KJFK'},MEM:{name:'Memphis International Airport',icao:'KMEM'}};
// Previously verified chart metadata, preserved from a986cedf13bcde536987848b16bf91d2d1213eff.
// This is a fixed chart link, not a current-cycle lookup or the NASR bearing source.
const verifiedDiagrams={MEM:{url:'https://aeronav.faa.gov/d-tpp/2611/00253AD.PDF',effective_date:'2026-10-29',valid_through:'2026-11-26'}};
function diagramHeader(code){
 const metadata=runwayData?.airport_metadata?.[code];
 const diagram=metadata?.heading_method==='chart-derived-approximate'?{...metadata,url:metadata.source_url}:verifiedDiagrams[code];
 if(!diagram||!/^https:\/\/[^/?#]+\/[^?#]*\.pdf(?:[?#].*)?$/i.test(diagram.url||''))return '';
 const dates=`Chart effective ${diagram.effective_date||'not supplied'}${diagram.valid_through?' through '+diagram.valid_through:''}`;
 return `<div class="airport-diagram"><a href="${esc(diagram.url)}" target="_blank" rel="noopener" title="${esc(dates)}" aria-label="Airport diagram for ${esc(code)}; opens in a new tab"><span class="diagram-link-text">Airport diagram </span><span aria-hidden="true">↗</span><span class="sr-only"> (${esc(dates)})</span></a></div>`;
}
let runwayData=null;
const reader=typeof NotamReader==='undefined'?null:NotamReader;
let notamTransport=null;
const syntheticNotamTransport=typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined'&&Boolean(SPATCHIN_SYNTHETIC_PREVIEW.useTransport);
const notamSnapshots=typeof NotamSnapshots==='undefined'||(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined'&&!syntheticNotamTransport)?null:NotamSnapshots.create({
 fetchFn:(...args)=>syntheticNotamTransport?SPATCHIN_SYNTHETIC_PREVIEW.fetchSnapshot(...args):fetch(...args),baseURL:document.baseURI,allowSynthetic:syntheticNotamTransport,
 onChange:state=>{notamTransport=state;reader?.set(state.snapshot,state.error&&!state.snapshot?'NOTAM data unavailable · '+state.error:state.error);render();}
});
function notamTransportBlock(code){
 if(!notamSnapshots)return '';
 return `<section class="notam-transport" aria-label="${esc(code)} NOTAM snapshot loading"><button type="button" data-notam-reload="${esc(code)}" aria-disabled="${Boolean(notamTransport?.refreshing)}">${notamTransport?.refreshing?'Loading NOTAM snapshot…':'Reload NOTAM snapshot'}</button><p>Published snapshot · No live provider request</p></section>`;
}
if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined'){runwayData=SPATCHIN_SYNTHETIC_PREVIEW.runways;if(!syntheticNotamTransport)reader?.set(SPATCHIN_SYNTHETIC_PREVIEW.notams);}
let atisData=null; let atisRetrieved=null;
const initial=['MEM'];let airports=initial.slice();const metars={};let lastFetch=null,loading=false,metarFeedError=false;
const METAR_STALE_MS=65*60*1000;
const AIRPORT_STORAGE_KEY='spatchin-airports';
function readAirports(key){
 try{
  const saved=JSON.parse(localStorage.getItem(key));
  if(Array.isArray(saved))return [...new Set(saved.filter(x=>typeof x==='string'&&/^[A-Z]{3}$/.test(x)))].slice(0,30);
 }catch{}
 return null;
}
const savedAirports=readAirports(AIRPORT_STORAGE_KEY);
if(savedAirports!==null)airports=savedAirports;
else{
 const legacyAirports=readAirports('niltsi-airports');
 if(legacyAirports!==null){airports=legacyAirports;save();}
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function icao(code){return airportInfo[code]?.icao||code;} // No inferred ICAO mapping; unsupported feeds remain unavailable.
function metarBadge(code){
 const station=airportInfo[code]?.icao;
 return station?`<a class="weather-badge" href="https://aviationweather.gov/data/metar/?ids=${encodeURIComponent(station)}" target="_blank" rel="noopener noreferrer" aria-label="METAR source for ${esc(code)} (${esc(station)}), opens in a new tab">METAR</a>`:'<span class="weather-badge" aria-label="METAR station-specific source unavailable; station mapping unverified">METAR</span>';
}
function components(w,h){const a=(w.direction-h)*Math.PI/180,head=w.speed*Math.cos(a),cross=w.speed*Math.sin(a);return {head:Math.round(head),cross:Math.round(Math.abs(cross)),side:cross>0?'R':cross<0?'L':'—'};}
function heading(id){return Number(id.slice(0,2))*10%360;}
function ends(code){return runwayData?.airports?.[code]?.map(x=>x.id)||(runwayPairs[code]||[]).flatMap(pair=>pair.split('/'));}
function runwayHeading(code,id){const end=runwayData?.airports?.[code]?.find(x=>x.id===id);return end?end.true_heading:heading(id);}
function runwayBearingLabel(code){
 if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return 'Synthetic placeholder bearing';
 if(runwayData?.airport_metadata?.[code]?.heading_method==='chart-derived-approximate')return 'Chart-derived approximate true bearing';
 return runwayData?.airports?.[code]?'FAA NASR true alignment':'Approximate runway-number heading';
}
function runwayRow(code,id,wind){
 const readerStatus=reader?.cell(icao(code),id,ends(code))||'<td class="unknown">—</td>';
 if(!wind||!Number.isFinite(wind.direction)||!Number.isFinite(wind.speed))return `<tr class="runway-row"><td>${esc(id)}</td><td class="unknown">—</td><td class="unknown">—</td>${readerStatus}</tr>`;
 const bearing=runwayHeading(code,id), c=components(wind,bearing);
 const gust=Number.isFinite(wind.gust)&&wind.gust>wind.speed?components({...wind,speed:wind.gust},bearing):null;
 function longitudinal(v){const head=v.head>=0;return `<span class="${head?'headwind':Math.abs(v.head)<5?'tailwind-low':'tailwind-high'}">${head?v.head+' HW':Math.abs(v.head)+' TW'}</span>`;}
 function lateral(v){return `<span class="${v.cross<10?'crosswind-low':v.cross<15?'crosswind-mid':'crosswind-high'}">${v.cross} ${v.side}</span>`;}
 return `<tr class="runway-row"><td title="${runwayBearingLabel(code)}: ${bearing}°">${esc(id)}</td><td>${longitudinal(c)}${gust?`<div class="gust">G ${longitudinal(gust)}</div>`:''}</td><td>${lateral(c)}${gust?`<div class="gust">G ${lateral(gust)}</div>`:''}</td>${readerStatus}</tr>`;
}
// Conservative extraction: only explicit approach/departure clauses, never generic runway mentions.
function advertised(text,kind){
 const normalized=String(text||'').toUpperCase();
 const pattern=kind==='arr' ? /(?:ARR\s+EXP|ARRIVALS?\s+(?:EXP|EXPECT)|LANDING\s+RWYS?)\s+([\s\S]*?)(?=\.\s|\bDEPS?\s+EXP\b|$)/g : /(?:DEPS?\s+EXP\s+RWYS?|DEPARTURES?\s+(?:EXP|EXPECT)\s+RWYS?)\s+([\s\S]*?)(?=\.\s|$)/g;
 const found=new Set(); let match;
 while((match=pattern.exec(normalized))!==null){
  const fragment=match[1].slice(0,300);
  for(const runway of fragment.matchAll(/\b(?:RWY\s*)?([0-3]?[0-9][LRC]?)\b/g)){
   const id=runway[1].padStart(runway[1].match(/[LRC]$/)?3:2,'0');
   if(/^(?:0[1-9]|[12][0-9]|3[0-6])[LRC]?$/.test(id))found.add(id);
  }
 }
 return [...found];
}
function atisBlock(code){
 const reports=atisData?.airports?.[icao(code)];
 const list=Array.isArray(reports)?reports:[];
 const latest=type=>list.filter(x=>x.type===type).sort((a,b)=>Date.parse(b.updatedAt||0)-Date.parse(a.updatedAt||0))[0];
 const combined=latest('combined'), arr=latest('arr')||combined, dep=latest('dep')||combined;
 const report=combined||latest('arr')||latest('dep');
 const newest=Math.max(...list.map(x=>Date.parse(x.updatedAt||0)).filter(Number.isFinite),0);
 const age= newest?Date.now()-newest:Infinity;
 const stale=age>45*60*1000 || age< -5*60*1000 || !atisRetrieved || Date.now()-Date.parse(atisRetrieved)>45*60*1000;
 const landing=arr?advertised(arr.datis,'arr'):[], departing=dep?advertised(dep.datis,'dep'):[];
 const label=values=>values.length?values.join(' · '):'—';
 const info=report?.code?esc(report.code):'—';
 const issue=report?.time&&/^\d{4}$/.test(String(report.time))?esc(report.time)+'Z':'—';
 const full=list.map(r=>`<p><strong>${esc(r.type.toUpperCase())} · INFO ${esc(r.code||'—')} · ${esc(r.time||'—')}Z</strong></p><p class="atis-raw">${esc(r.datis)}</p>`).join('');
 return `<section class="atis"><div class="atis-top"><div><h3>ATIS</h3><div class="atis-provider">atis.info · ${stale?'STALE / UNVERIFIED':'UNOFFICIAL'}</div></div><div class="atis-meta">INFO ${info} · ISSUED <strong>${issue}</strong></div></div><div class="atis-runways"><div class="atis-box"><div class="atis-label">↘ LANDING</div><div class="atis-value">${esc(label(landing))}</div></div><div class="atis-box"><div class="atis-label">↗ DEPARTING</div><div class="atis-value">${esc(label(departing))}</div></div></div><details class="atis-full"><summary>Full ATIS information</summary>${full||'<p>ATIS not available.</p>'}<p>Source update: ${esc(newest?utc(newest):'—')} · Snapshot retrieved: ${esc(utc(atisRetrieved))}</p><p><a href="https://atis.info/api/${encodeURIComponent(icao(code))}" target="_blank" rel="noopener">Original ATIS source</a></p><p>Do not use for real world flight planning or navigation. Advertised runway extraction is automated and may be incomplete.</p></details></section>`;
}
function windLabel(w){if(!w)return '—';const dir=Number.isFinite(w.direction)?String(w.direction).padStart(3,'0')+'°':'VRB';return `${dir} / ${w.speed}${Number.isFinite(w.gust)&&w.gust>0?'G'+w.gust:''}KT`;}
function utc(t){if(!t)return '—';const d=new Date(t);return Number.isNaN(d.getTime())?'—':d.toISOString().slice(0,16).replace('T',' ')+'Z';}
const flightCategories=['VFR','MVFR','IFR','LIFR'];
function flightCategory(m){return flightCategories.includes(m?.flightCategory)?m.flightCategory:null;}
function categoryMarkup(m){
 const current=flightCategory(m),stale=metarState(m)==='stale';
 // The AWC fltCat value represents the limiting (worst) ceiling/visibility category.
 // Do not guess a category if the provider omits it or the observation is unavailable.
 const tag=current?'<span class="category-tag category-'+current.toLowerCase()+'" title="AWC ceiling/visibility flight category from '+(stale?'stale ':'')+'METAR observation">'+current+'</span>':'<span class="category-tag category-unavailable">NO DATA</span>';
 return {tag};
}
function metarState(m){
 if(!m || !m.wind || !m.observed || !Number.isFinite(Date.parse(m.observed)))return 'unavailable';
 const age=Date.now()-Date.parse(m.observed);
 return age>=METAR_STALE_MS || age< -5*60*1000?'stale':'current';
}
function metarStatus(m){
 const state=metarState(m);
 if(state==='unavailable')return '<span class="metar-status metar-unavailable">METAR UNAVAILABLE</span>';
 if(state==='stale')return '<span class="metar-status metar-stale">METAR STALE · 65+ MIN</span>';
 return '<span class="metar-status metar-current">METAR CURRENT</span>';
}
const observedSelection=new Map();
function render(){const reloadFocus=document.activeElement?.dataset?.notamReload,active=document.activeElement,activeId=active?.id,removeFocus=active?.dataset?.remove;
 const atisOpen=new Set([...document.querySelectorAll('.atis-full[open]')].map(el=>el.closest('[data-airport]')?.dataset.airport));
 reader?.before();document.getElementById('cards').innerHTML=airports.map(code=>{const a=airportInfo[code],m=metars[code],r=ends(code),w=m?.wind;

 const observation=m?.raw||m?.error||'Observation unavailable';
 const retained=metarFeedError&&m?.raw?'<span class="metar-retained">Feed refresh failed; showing retained observation.</span>':'';
 const category=categoryMarkup(m);
 return `<article class="airport" data-airport="${code}"><div class="airport-head"><div class="airport-top-row"><button type="button" class="airport-grip" data-airport-drag="${esc(code)}" aria-label="Reorder ${esc(code)} airport: drag or use arrow keys" title="Drag to reorder; arrow keys also work" ${airports.length<2?'disabled':''}><svg viewBox="0 0 16 24" width="16" height="24" aria-hidden="true" focusable="false" fill="currentColor"><circle cx="4" cy="5" r="1.8"/><circle cx="12" cy="5" r="1.8"/><circle cx="4" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="4" cy="19" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg></button><div class="icao">${esc(code)}</div>${category.tag}<div class="airport-head-spacer"></div>${diagramHeader(code)}<button type="button" class="airport-remove" data-remove="${esc(code)}" aria-label="Remove ${esc(code)} airport" title="Remove airport">×</button></div><div class="name">${esc(a?.name||'Airport not yet configured')}</div></div><section class="weather-row metar-panel" aria-label="${esc(code)} METAR"><div class="weather-source">${metarBadge(code)}</div><div class="weather-copy">${metarStatus(m)}<div class="metar-raw">${esc(observation)}</div>${retained}</div></section><section class="taf"><strong>TAF</strong><span>Unavailable — feed not connected; forecast selection not supported.</span></section>${atisBlock(code)}${reader?.summary(icao(code))||''}<div class="time-control"><label for="time-${code}">Time (UTC / Zulu)</label><select id="time-${code}" data-observed-time="${code}"><option value="${esc(m?.observed||'unavailable')}">${m?.observed?'Observed '+esc(utc(m.observed)):'Observation unavailable'}</option><option disabled>Forecast unavailable</option></select></div><div class="runways">${r.length?`<table class="rw-table"><thead><tr><th>RWY</th><th>Head/Tail</th><th>Cross</th><th>NOTAM references</th></tr></thead><tbody>${r.map(id=>runwayRow(code,id,w)+(reader?.row(icao(code),id,r)||'')).join('')}</tbody></table>`:'<div class="empty">Runway data pending.</div>'}</div><footer class="airport-footer">${notamTransportBlock(code)}</footer></article>`;}).join('');
 document.querySelectorAll('[data-airport]').forEach(el=>{const details=el.querySelector('.atis-full');if(details)details.open=atisOpen.has(el.dataset.airport);});
 document.querySelectorAll('[data-observed-time]').forEach(el=>{const previous=observedSelection.get(el.dataset.observedTime);if([...el.options].some(o=>o.value===previous&&!o.disabled))el.value=previous;el.addEventListener('change',()=>observedSelection.set(el.dataset.observedTime,el.value));});
 document.querySelectorAll('[data-remove]').forEach(b=>b.addEventListener('click',()=>{const index=airports.indexOf(b.dataset.remove);airports=airports.filter(x=>x!==b.dataset.remove);save();render();const next=airports[Math.min(index,airports.length-1)];([...document.querySelectorAll('[data-remove]')].find(el=>el.dataset.remove===next)||document.getElementById('iata'))?.focus();}));reader?.after();
 document.querySelectorAll('[data-notam-reload]').forEach(b=>b.addEventListener('click',()=>notamSnapshots?.refresh()));
 attachAirportReordering();
 if(reloadFocus)[...document.querySelectorAll('[data-notam-reload]')].find(b=>b.dataset.notamReload===reloadFocus)?.focus({preventScroll:true});
 else if(removeFocus)[...document.querySelectorAll('[data-remove]')].find(b=>b.dataset.remove===removeFocus)?.focus({preventScroll:true});
 else if(activeId)document.getElementById(activeId)?.focus?.({preventScroll:true});
}
// Airport order is the existing spatchin-airports array, including on reload.
function moveAirport(code,targetIndex){
 const from=airports.indexOf(code);
 if(from<0||!Number.isInteger(targetIndex)||targetIndex<0||targetIndex>=airports.length||from===targetIndex)return false;
 airports.splice(from,1);
 airports.splice(targetIndex,0,code);
 save();
 render();
 document.querySelector?.('[data-airport-drag="'+code+'"]')?.focus({preventScroll:true});
 const status=document.getElementById('airport-order-status');
 if(status)status.textContent=code+' moved to position '+(targetIndex+1)+' of '+airports.length;
 return true;
}
function attachAirportReordering(){
 // Pointer events support mouse, pen and touch without native HTML5 DnD's touch gaps.
 document.querySelectorAll('[data-airport-drag]').forEach(handle=>{
  const code=handle.dataset.airportDrag;
  let drag=null;
  const clear=()=>{
   document.querySelectorAll('.airport.is-dragging, .airport.is-drop-target')
    .forEach(el=>el.classList.remove('is-dragging','is-drop-target'));
  };
  handle.addEventListener('keydown',event=>{
   const direction=['ArrowLeft','ArrowUp'].includes(event.key)?-1:
    ['ArrowRight','ArrowDown'].includes(event.key)?1:0;
   if(!direction)return;
   event.preventDefault();
   moveAirport(code,airports.indexOf(code)+direction);
  });
  // A tap or Enter also moves one position; arrows offer both directions.
  handle.addEventListener('click',()=>{
   if(handle.dataset.suppressClick==='true'){delete handle.dataset.suppressClick;return;}
   const i=airports.indexOf(code);
   if(airports.length>1)moveAirport(code,i===airports.length-1?i-1:i+1);
  });
  handle.addEventListener('pointerdown',event=>{
   if(event.button!==0||event.isPrimary===false)return;
   drag={pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,target:null,active:false};
   try{handle.setPointerCapture(event.pointerId);}catch{}
  });
  handle.addEventListener('pointermove',event=>{
   if(!drag||event.pointerId!==drag.pointerId)return;
   if(!drag.active&&Math.hypot(event.clientX-drag.startX,event.clientY-drag.startY)<8)return;
   drag.active=true;
   document.querySelector('[data-airport="'+code+'"]')?.classList.add('is-dragging');
   document.querySelectorAll('.airport.is-drop-target').forEach(el=>el.classList.remove('is-drop-target'));
   const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-airport]');
   drag.target=target?.dataset.airport&&target.dataset.airport!==code?target.dataset.airport:null;
   if(drag.target)target.classList.add('is-drop-target');
  });
  const finish=(event,cancelled)=>{
   if(!drag||event.pointerId!==drag.pointerId)return;
   const {active,target}=drag;
   drag=null;
   clear();
   if(active){
    handle.dataset.suppressClick='true';
    if(!cancelled&&target)moveAirport(code,airports.indexOf(target));
   }
  };
  handle.addEventListener('pointerup',event=>finish(event,false));
  handle.addEventListener('pointercancel',event=>finish(event,true));
  handle.addEventListener('lostpointercapture',event=>finish(event,true));
 });
}
const catalogOptions=document.getElementById('airport-options');if(catalogOptions)catalogOptions.innerHTML=approvedCatalog.map(c=>`<option value="${c}">${esc(airportInfo[c]?.name||'Airport metadata unverified')}</option>`).join('');
function save(){try{localStorage.setItem(AIRPORT_STORAGE_KEY,JSON.stringify(airports));}catch{}}
function parseMetar(m){const speed=m.wspd===null||m.wspd===undefined?NaN:Number(m.wspd),direction=m.wdir===null||m.wdir===undefined||m.wdir==='VRB'?null:Number(m.wdir),gust=m.wgst===null||m.wgst===undefined?null:Number(m.wgst);return {wind:Number.isFinite(speed)?{speed,direction:Number.isFinite(direction)?direction:null,gust:Number.isFinite(gust)?gust:null}:null,observed:typeof m.obsTime==='number'?new Date(m.obsTime*1000).toISOString():(m.obsTime||m.reportTime||null),raw:m.rawOb||'',flightCategory:flightCategories.includes(m.fltCat)?m.fltCat:null,error:null};}
async function refresh(){
 if(loading)return;
 loading=true;
 const targets=airports.filter(c=>airportInfo[c]);
 if(!targets.length){loading=false;render();return;}
 try{
  const response=await fetch(`./data/metars.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(!Array.isArray(data.metars))throw new Error('Unexpected METAR response');
  const updated=Date.parse(data.updated_utc||'');
  if(!Number.isFinite(updated)||updated>Date.now()+5*60*1000)throw new Error('Invalid METAR retrieval timestamp');
  const found=new Set();
  for(const m of data.metars){
   const code=targets.find(c=>icao(c)===m.icaoId);
   if(!code)continue;
   const parsed=parseMetar(m);
   if(!parsed.wind||!Number.isFinite(Date.parse(parsed.observed||'')))continue;
   const previous=metars[code];
   if(!previous?.observed || Date.parse(parsed.observed)>=Date.parse(previous.observed))metars[code]=parsed;
   found.add(code);
  }
  for(const code of targets){if(!found.has(code)&&!metars[code])metars[code]={error:'No valid METAR returned',wind:null};}
  if(!lastFetch || updated>=Date.parse(lastFetch))lastFetch=data.updated_utc;
  metarFeedError=false;
 }catch(e){
  metarFeedError=true;
  for(const code of targets){if(!metars[code])metars[code]={error:'Published METAR feed unavailable',wind:null};}
  console.error('Spatchin METAR retrieval:',e);
 }finally{loading=false;render();}
}
document.getElementById('add-form').addEventListener('submit',e=>{e.preventDefault();const f=document.getElementById('iata'),code=f.value.trim().toUpperCase();if(!approvedCatalog.includes(code)){alert('Choose an IATA code from the approved C070 catalog.');return;}if(airports.includes(code)){alert(code+' is already displayed.');return;}if(airports.length>=30){alert('Maximum 30 airports.');return;}airports.push(code);save();render();f.value='';refresh();});
async function refreshRunways(){
 if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return;
 try{
  const response=await fetch(`./data/runways.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(data.heading_reference!=='TRUE'||!data.airports||!data.effective_date)throw new Error('Invalid FAA runway data');
  for(const [code,count] of Object.entries({ORD:16,LAX:8,JFK:8})){
   const list=data.airports[code];
   if(!Array.isArray(list)||list.length!==count||list.some(x=>!x.id||!Number.isFinite(x.true_heading)))throw new Error(`Invalid ${code} runway data`);
  }
  // Accept legacy snapshots without MEM; validate all eight ends when MEM arrives.
  if(data.airports.MEM!==undefined){
   const list=data.airports.MEM;
   if(!Array.isArray(list)||list.length!==8||new Set(list.map(x=>x.id)).size!==8||list.some(x=>!/^((0[1-9]|[12][0-9]|3[0-6])[LRC]?)$/.test(x.id)||!Number.isFinite(x.true_heading)||x.true_heading<0||x.true_heading>=360))throw new Error('Invalid MEM runway data');
  }
  runwayData=data;render();
 }catch(e){console.info('FAA runway data not yet available; retaining provisional headings:',e.message);}
}
async function refreshAtis(){
 try{
  const response=await fetch(`./data/atis.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(!data.airports||!data.retrieved_utc)throw new Error('Invalid ATIS snapshot');
  atisData=data;atisRetrieved=data.retrieved_utc;render();
 }catch(e){console.info('ATIS snapshot unavailable:',e.message);}
}
function clock(){document.getElementById('clock').textContent=new Date().toISOString().replace('T',' ').slice(0,19)+'Z';}clock();setInterval(clock,1000);render();refresh();refreshRunways();refreshAtis();notamSnapshots?.refresh();setInterval(refresh,120000);setInterval(render,30000);setInterval(refreshRunways,3600000);setInterval(refreshAtis,120000);
