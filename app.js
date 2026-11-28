'use strict';
import {currentDiagramMarkup,diagramSearchMarkup} from './airport-diagrams.js';
// Spatchin v0.9. METARs loaded from GitHub Pages same-origin JSON. Not for operational dispatch use.
// Explicit dependencies keep browser state inside one dashboard instance.
export function mountDashboard({AirportCatalog,AirportMetadata,NotamReader,NotamSnapshots,preview,enableForecast=false}={}){
const SPATCHIN_SYNTHETIC_PREVIEW=preview;
const runwayPairs={ORD:['04L/22R','04R/22L','09L/27R','09R/27L','09C/27C','10L/28R','10C/28C','10R/28L'],LAX:['06L/24R','06R/24L','07L/25R','07R/25L'],JFK:['04L/22R','04R/22L','13L/31R','13R/31L']};
const approvedCatalog=typeof AirportCatalog==='undefined'?Object.keys({MEM:1,ORD:1,LAX:1,JFK:1}):AirportCatalog;
const airportInfo=typeof AirportMetadata==='undefined'?{ORD:{name:'Chicago O’Hare',icao:'KORD'},LAX:{name:'Los Angeles International',icao:'KLAX'},JFK:{name:'John F. Kennedy International',icao:'KJFK'},MEM:{name:'Memphis International Airport',icao:'KMEM'}}:AirportMetadata;
// Historical chart sources are shown only for chart-derived runway bearings.
let diagramIndex=null;
function diagramHeader(code){
 const search=currentDiagramMarkup(diagramIndex,code,airportInfo[code]?.icao,esc)||diagramSearchMarkup(airportInfo[code]?.icao,esc);
 const metadata=runwayData?.airport_metadata?.[code];
 const diagram=metadata?.heading_method==='chart-derived-approximate'?{...metadata,url:metadata.source_url}:null;
 if(!diagram||!/^https:\/\/aeronav\.faa\.gov\/d-tpp\/[0-9]{4}\/[A-Za-z0-9_-]+\.pdf$/i.test(diagram.url||''))return search;
 const dates=`Chart effective ${diagram.effective_date||'not supplied'}${diagram.valid_through?' through '+diagram.valid_through:''}`;
 return search+`<div class="airport-diagram"><a href="${esc(diagram.url)}" target="_blank" rel="noopener" title="${esc(dates)}; historical source, check current FAA edition" aria-label="Airport diagram for ${esc(code)}; historical source; opens in a new tab"><span class="diagram-link-text">Historical diagram </span><span aria-hidden="true">↗</span><span class="sr-only"> (${esc(dates)})</span></a></div>`;
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
 const busy=Boolean(notamTransport?.refreshing);
 const label=busy?'Loading NOTAM snapshot…':'Reload NOTAM snapshot';
 return `<button class="notam-reload" type="button" data-notam-reload="${esc(code)}" aria-label="${label}" title="${label} (published data only)" aria-disabled="${busy}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M5.5 8a7.5 7.5 0 0 1 12.4-2L20 9M4 15l2.1 3A7.5 7.5 0 0 0 18.5 16"/></svg></button>`;
}
if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined'){runwayData=SPATCHIN_SYNTHETIC_PREVIEW.runways;if(!syntheticNotamTransport)reader?.set(SPATCHIN_SYNTHETIC_PREVIEW.notams);}
let atisData=null; let atisRetrieved=null;
let tafData=null,tafFeedError=false;
// Native module dependencies are absent in the synthetic previews.
let forecastReader,forecastTimeline;
const initial=['MEM'];let airports=initial.slice();const metars={};let lastFetch=null,loading=false,metarFeedError=false;
const METAR_STALE_MS=70*60*1000;
const AIRPORT_STORAGE_KEY='spatchin-airports';
// Airport preference normalization and order changes without storage or DOM access.
const AirportOrder=(()=>{
 function normalize(saved){
  return Array.isArray(saved)?[...new Set(saved.filter(x=>typeof x==='string'&&/^[A-Z]{3}$/.test(x)))].slice(0,30):null;
 }
 function move(order,code,targetIndex){
  const from=order.indexOf(code);
  if(from<0||!Number.isInteger(targetIndex)||targetIndex<0||targetIndex>=order.length||from===targetIndex)return false;
  order.splice(from,1);
  order.splice(targetIndex,0,code);
  return true;
 }
 return {normalize,move};
})();
function readAirports(key){
 try{
  const saved=JSON.parse(localStorage.getItem(key));
  return AirportOrder.normalize(saved);
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
// Link the original report prefix; retain source access for unavailable or unfamiliar reports.
function metarBadge(code,observation='',hasRaw=false){
 const station=airportInfo[code]?.icao;
 const link=label=>station?`<a class="report-source" href="https://aviationweather.gov/data/metar/?ids=${encodeURIComponent(station)}" target="_blank" rel="noopener noreferrer" aria-label="METAR source for ${esc(code)} (${esc(station)}), opens in a new tab">${esc(label)}</a>`:esc(label);
 const prefix=hasRaw&&station&&/^[A-Z]{4}$/.test(station)?String(observation).match(new RegExp('^(\\s*)((?:(?:METAR|SPECI)\\s+)?'+station+')(?=\\s|$)')):null;
 return prefix?{raw:esc(prefix[1])+link(prefix[2])+esc(observation.slice(prefix[0].length)),fallback:''}:
  {raw:esc(observation),fallback:station?link('METAR source'):''};
}
// Pure runway wind calculations and display values. Keep provider and DOM state outside this boundary.
const RunwayWind=(()=>{
 function components(w,h){const a=(w.direction-h)*Math.PI/180,head=w.speed*Math.cos(a),cross=w.speed*Math.sin(a);return {head:Math.round(head),cross:Math.round(Math.abs(cross)),side:cross>0?'R':cross<0?'L':'—'};}
 function heading(id){return Number(id.slice(0,2))*10%360;}
 function longitudinal(v){const head=v.head>=0;return `<span class="${head?'headwind':Math.abs(v.head)<5?'tailwind-low':'tailwind-high'}">${head?v.head+' HW':Math.abs(v.head)+' TW'}</span>`;}
 function lateral(v){return `<span class="${v.cross<10?'crosswind-low':v.cross<15?'crosswind-mid':'crosswind-high'}">${v.cross} ${v.side}</span>`;}
 function values(w,bearing){
  if(!w||!Number.isFinite(w.direction)||!Number.isFinite(w.speed)||!Number.isFinite(bearing))return ['—','—'];
  const current=components(w,bearing);
  const gust=Number.isFinite(w.gust)&&w.gust>w.speed?components({...w,speed:w.gust},bearing):null;
  return [longitudinal(current)+(gust?'<div class="gust">G '+longitudinal(gust)+'</div>':''),
   lateral(current)+(gust?'<div class="gust">G '+lateral(gust)+'</div>':'')];
 }
 return {components,heading,values};
})();
function ends(code){return runwayData?.airports?.[code]?.map(x=>x.id)||(runwayPairs[code]||[]).flatMap(pair=>pair.split('/'));}
function runwayHeading(code,id){
 const end=runwayData?.airports?.[code]?.find(x=>x.id===id);
 if(runwayData?.heading_reference==='MAGNETIC'){
  const variation=runwayData.airport_metadata?.[code]?.magnetic_variation_deg;
  return end&&Number.isFinite(end.magnetic_heading)&&Number.isFinite(variation)?(end.magnetic_heading+variation+360)%360:null;
 }
 return end?end.true_heading:RunwayWind.heading(id);
}
function runwayBasis(code){
 if(runwayData?.heading_reference!=='MAGNETIC')return '';
 const metadata=runwayData.airport_metadata?.[code];
 return Number.isFinite(metadata?.magnetic_variation_deg)?'Approx. wind components · FAA magnetic variation '+metadata.magnetic_variation_year:'Wind components unavailable · magnetic variation missing';
}
function runwayBearingLabel(code){
 if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return 'Synthetic placeholder bearing';
 if(runwayData?.heading_reference==='MAGNETIC')return 'Approximate magnetic runway heading';
 if(runwayData?.airport_metadata?.[code]?.heading_method==='chart-derived-approximate')return 'Chart-derived approximate true bearing';
 return runwayData?.airports?.[code]?'FAA NASR true alignment':'Approximate runway-number heading';
}
function runwayRow(code,id,wind,forecast=null){
 const readerStatus=reader?.cell(icao(code),id,ends(code))||'<td class="unknown">—</td>';
 const bearing=runwayHeading(code,id);
 const displayedBearing=runwayData?.heading_reference==='MAGNETIC'?runwayData.airports?.[code]?.find(x=>x.id===id)?.magnetic_heading:bearing;
 const primary=RunwayWind.values(wind,bearing);
 const alternates=forecast?.alternatives||[];
 const extra=alternates.map(item=>{
  const alt=RunwayWind.values(item.wind,bearing);
  const label=esc(item.label);
  return ['<div class="forecast-alt">'+label+': '+alt[0]+'</div>',
   '<div class="forecast-alt">'+label+': '+alt[1]+'</div>'];
 });
 return `<tr class="runway-row"><td title="${runwayBearingLabel(code)}: ${Number.isFinite(displayedBearing)?displayedBearing+"°":"unavailable"}">${esc(id)}</td><td>${primary[0]}${extra.map(x=>x[0]).join('')}</td><td>${primary[1]}${extra.map(x=>x[1]).join('')}</td>${readerStatus}</tr>`;
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
 // Explicit in-use clauses observed in MEM ATIS. Require a complete runway list,
 // not arbitrary numbers in the remainder of the report.
 const inUse=kind==='arr'
  ? /(?:^|[.!?]\s*)ILS\s+APCH\s+IN\s+USE\s+R(?:W)?YS?\s+([^.!?]*)(?=[.!?]|$)/g
  : /(?:^|[.!?]\s*)SIMUL\s+DEPS?\s+IN\s+USE\s+R(?:W)?YS?\s+([^.!?]*)(?=[.!?]|$)/g;
 const runwayList=/^(?:0?[1-9]|[12][0-9]|3[0-6])[LRC]?(?:(?:\s*,\s*(?:AND\s+)?|\s+AND\s+|\s+)(?:0?[1-9]|[12][0-9]|3[0-6])[LRC]?)*$/;
 while((match=inUse.exec(normalized))!==null){
  const fragment=match[1].trim();
  if(!runwayList.test(fragment))continue;
  for(const token of fragment.matchAll(/\b(?:0?[1-9]|[12][0-9]|3[0-6])[LRC]?\b/g)){
   const id=token[0].padStart(/[LRC]$/.test(token[0])?3:2,'0');
   found.add(id);
  }
 }
 return [...found];
}
const ATIS_STALE_MS=45*60*1000;
function atisTimestamp(value){
 // Require an explicit timezone and reject normalized invalid dates.
 if(typeof value!=='string')return null;
 const m=/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/.exec(value);
 if(!m)return null;
 const [year,month,day,hour,minute,second]=m.slice(1,7).map(Number);
 if(year<1||month<1||month>12||day<1||day>new Date(Date.UTC(year,month,0)).getUTCDate()||
  hour>23||minute>59||(Number.isFinite(second)&&second>59))return null;
 const stamp=Date.parse(value.replace(' ','T'));
 return Number.isFinite(stamp)?stamp:null;
}
function atisSourceTime(report){
 const stamp=atisTimestamp(report?.updatedAt);
 return stamp!==null&&stamp<=Date.now()+5*60*1000?stamp:null;
}
function atisApplicable(list,kind){
 // Select the newest applicable report before extracting runway clauses.
 return list.filter(report=>(report.type===kind||report.type==='combined')&&atisSourceTime(report)!==null)
  .sort((a,b)=>atisSourceTime(b)-atisSourceTime(a))[0]||null;
}
function atisState(report,retrieved=atisRetrieved){
 const source=atisSourceTime(report),snapshot=atisTimestamp(retrieved);
 if(source===null)return 'unavailable';
 const sourceAge=Date.now()-source,snapshotAge=Date.now()-snapshot;
 return sourceAge>ATIS_STALE_MS||sourceAge< -5*60*1000||snapshot===null||
  snapshotAge>ATIS_STALE_MS||snapshotAge< -5*60*1000?'stale':'current';
}
function atisCoverage(station,snapshot=atisData){
 const configured=snapshot?.configured_airports;
 const reports=snapshot?.airports;
 if(!reports||typeof reports!=='object'||Array.isArray(reports))return 'unknown';
 // Do not infer coverage from missing reports, malformed metadata or a legacy snapshot.
 if(Array.isArray(configured)&&configured.length&&
  configured.every(code=>typeof code==='string'&&/^[A-Z0-9]{4}$/.test(code))&&
  new Set(configured).size===configured.length){
  const catalog=snapshot?.catalog_airports;
  if(catalog!==undefined&&(!Array.isArray(catalog)||catalog.length!==130||
   new Set(catalog).size!==catalog.length||!catalog.every(code=>typeof code==='string'&&/^[A-Z0-9]{4}$/.test(code))||
   !configured.every(code=>catalog.includes(code))||!Object.keys(reports).every(code=>catalog.includes(code))||!catalog.includes(station)))return 'unknown';
  if(catalog===undefined&&!Object.keys(reports).every(code=>configured.includes(code)))return 'unknown';
  return configured.includes(station)?'configured':'not configured';
 }
 return 'unknown';
}
function atisBlock(code){
 const station=icao(code),coverage=atisCoverage(station);
 const reports=atisData?.airports?.[station];
 const list=Array.isArray(reports)?reports.filter(r=>r&&['arr','dep','combined'].includes(r.type)):[];
 const missingState=coverage==='not configured'?'not configured':
  coverage==='unknown'&&!list.length?'coverage unknown':'unavailable';
 const active=coverage==='not configured'?[]:list;
 const arr=atisApplicable(active,'arr'),dep=atisApplicable(active,'dep');
 const report=active.filter(x=>atisSourceTime(x)!==null).sort((a,b)=>atisSourceTime(b)-atisSourceTime(a))[0]||null;
 const landing=arr?advertised(arr.datis,'arr'):[], departing=dep?advertised(dep.datis,'dep'):[];
 const arrState=landing.length?atisState(arr):missingState,depState=departing.length?atisState(dep):missingState;
 const providerState=arrState==='stale'||depState==='stale'?'STALE / UNVERIFIED':
  !landing.length&&!departing.length?missingState.toUpperCase():'UNOFFICIAL';
 const coverageNote=coverage==='not configured'?'Airport is outside collection coverage in this snapshot. Provider support is not established.':
  coverage==='unknown'?'ATIS collection coverage is unknown in this snapshot.':
  !list.length?'Configured airport; no usable ATIS report in this snapshot.':'Configured airport.';
 const runwayNote=coverage==='not configured'&&list.length?' Retained historical reports below are not current configuration.':
  list.length&&(!landing.length||!departing.length)?' No usable explicit runway information for one or both directions.':'';
 const label=values=>values.length?values.join(' · '):'—';
 const info=report?.code?esc(report.code):'—';
 const issue=report?.time&&/^\d{4}$/.test(String(report.time))?esc(report.time)+'Z':'—';
 const full=list.map(r=>`<p><strong>${esc(r.type.toUpperCase())} · INFO ${esc(r.code||'—')} · ${esc(r.time||'—')}Z</strong></p><p class="atis-raw">${esc(r.datis)}</p>`).join('');
 return `<section class="atis"><div class="atis-top"><div><h3>ATIS</h3>${providerState==='UNOFFICIAL'?'':`<div class="atis-provider">atis.info · ${providerState}</div>`}</div><div class="atis-meta">INFO ${info} · ISSUED <strong>${issue}</strong></div></div><div class="atis-runways"><div class="atis-box"><div class="atis-label">LANDING${arrState==='current'?'':' · '+arrState.toUpperCase()}</div><div class="atis-value">${esc(label(landing))}</div></div><div class="atis-box"><div class="atis-label">DEPARTING${depState==='current'?'':' · '+depState.toUpperCase()}</div><div class="atis-value">${esc(label(departing))}</div></div></div><details class="atis-full"><summary>Full ATIS information</summary>${full}<p>${esc(coverageNote+runwayNote)}</p><p>Landing source update: ${esc(atisSourceTime(arr)!==null?utc(atisSourceTime(arr)):'—')} · Departure source update: ${esc(atisSourceTime(dep)!==null?utc(atisSourceTime(dep)):'—')} · Snapshot retrieved: ${esc(utc(atisTimestamp(atisRetrieved)))}</p><p><a href="https://atis.info/api/${encodeURIComponent(icao(code))}" target="_blank" rel="noopener">Original ATIS source</a></p><p>Do not use for real world flight planning or navigation. Advertised runway extraction is automated and may be incomplete.</p></details></section>`;
}
function tafBlock(code){
 const station=airportInfo[code]?.icao;
 if(typeof forecastReader==='undefined')return '<section class="taf" aria-label="TAF"><div class="taf-status taf-unavailable">TAF UNAVAILABLE</div><div>Forecast reader unavailable.</div></section>';
 return forecastReader.render({code,station,report:tafData?.tafs?.find(item=>item.icaoId===station),feedError:tafFeedError});
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
 if(state==='stale')return '<span class="metar-status metar-stale">METAR STALE · 70+ MIN</span>';
 return '';
}

function forecastModel(code,m){
 const station=airportInfo[code]?.icao;
 const report=tafData?.tafs?.find(item=>item.icaoId===station);
 const available=typeof forecastTimeline!=='undefined'&&typeof forecastReader!=='undefined'&&
  forecastReader.valid(report,station)&&forecastTimeline.bounds(report)&&
  forecastTimeline.periods(report).some(item=>item.kind==='BASE'||item.kind==='FM')&&
  Date.now()<forecastTimeline.bounds(report).end&&
  Date.now()-forecastTimeline.time(report.issueTime)<=forecastTimeline.STALE_MS;
 const observed=m?.observed||'unavailable';
 const selected=observedSelection.get(code);
 const rangeMode=selected?.startsWith('taf-range:');
 const rawSelected=rangeMode?forecastTimeline?.time(selected.slice(10)):selected?.startsWith('taf:')?forecastTimeline?.time(selected.slice(4)):NaN;
 const bounds=available?forecastTimeline.bounds(report):null;
 const ranges=available?forecastTimeline.ranges(report):[];
 const chosenRange=ranges.find(r=>rawSelected>=r.start&&rawSelected<r.end);
 const forecast=Boolean(available&&chosenRange&&(!rangeMode||rawSelected===chosenRange.start));
 const initial=available?forecastTimeline.initialTime(report):NaN;
 const at=forecast?rawSelected:initial;
 const state=forecast?(rangeMode?forecastTimeline.selectRange(report,chosenRange):forecastTimeline.select(report,at)):null;
 return {report,available:Boolean(available),bounds,observed,forecast,at,state,ranges,chosenRange,rangeMode};
}
function timeControl(code,m,model){
 const prefix='<div class="time-control'+(model.forecast?' forecast-active':'')+
  '"><label for="time-'+esc(code)+'">Time (UTC / Zulu)</label>'+
  '<select id="time-'+esc(code)+'" data-observed-time="'+esc(code)+'">'+
  '<option value="'+esc(model.observed)+'"'+(!model.forecast?' selected':'')+'>'+
  'Current'+'</option>';
 if(!model.available){
  return prefix+'<option disabled>Forecast unavailable</option></select></div>';
 }
 const at=Number.isFinite(model.at)?model.at:forecastTimeline.initialTime(model.report);
 const time=esc(forecastTimeline.stamp(at));
 const sliderValue=forecastTimeline.stepIndex(model.report,at);
 const max=forecastTimeline.steps(model.report);
 const range=model.bounds;
 let result=prefix+model.ranges.map(r=>'<option value="'+esc('taf-range:'+new Date(r.start).toISOString())+'"'+
  (model.forecast&&model.chosenRange===r?' selected':'')+'>'+esc(forecastTimeline.rangeLabel(r))+'</option>').join('')+'</select></div>';
 result+='<div class="forecast-controls" data-forecast-controls="'+esc(code)+'">'+
  '<label for="forecast-slider-'+esc(code)+'">Forecast timeline (UTC)</label>'+
  '<input type="range" id="forecast-slider-'+esc(code)+'" data-forecast-slider="'+esc(code)+
  '" min="0" max="'+max+'" step="1" value="'+sliderValue+
  '" aria-label="'+esc(code)+' forecast time slider">'+
  '<output data-forecast-output="'+esc(code)+'">'+time+'</output>'+
  '<label for="forecast-date-'+esc(code)+'">Exact UTC time</label>'+
  '<input id="forecast-date-'+esc(code)+'" type="datetime-local" data-forecast-date="'+esc(code)+
  '" value="'+esc(forecastTimeline.localInput(at))+'" min="'+esc(forecastTimeline.localInput(range.start))+
  '" max="'+esc(forecastTimeline.localInput(range.end-60000))+'" step="60">'+
  '<div class="forecast-range">Valid '+esc(forecastTimeline.stamp(range.start))+
  ' – '+esc(forecastTimeline.stamp(range.end))+'</div></div>';
 if(model.forecast){
  const state=model.state;
  const resultLabel=state?.status==='available'?'TAF FORECAST':state?.status==='transition'?
   'BECMG TRANSITION':state?.status==='expired'?'NO LONGER VALID':
   state?.status==='stale'?'TAF STALE':'FORECAST WIND UNAVAILABLE';
  const wind=state?.wind?windLabel(state.wind):'Wind components unavailable';
  const notes=(state?.notes||[]).map(esc).join(' · ');
  const bearing=runwayBasis(code).startsWith('Wind components unavailable')?runwayBasis(code):'';
  result+='<div class="forecast-summary" role="status"><strong>'+resultLabel+
   ' · '+(model.rangeMode?esc(forecastTimeline.rangeLabel(model.chosenRange)):time)+'</strong><div>'+esc(wind)+(notes?' · '+notes:'')+
   '</div><div>'+(bearing?esc(bearing)+' · ':'')+'Issued '+esc(forecastTimeline.stamp(forecastTimeline.time(model.report.issueTime)))+
   ' · Snapshot '+esc(utc(tafData?.updated_utc))+'</div>'+
   '<div>Forecast is not an observation. TEMPO/PROB winds are alternatives, not prevailing.</div></div>';
 }
 return result;
}

const observedSelection=new Map();
// Build one airport card from explicit inputs and existing section renderers.
function airportCardMarkup(code,{airportCount,airportInfo,metars,ends,forecastModel,metarFeedError,categoryMarkup,esc,diagramHeader,metarBadge,metarStatus,tafBlock,atisBlock,reader,icao,timeControl,runwayRow,notamTransportBlock,runwayBasis=()=>''}){
 const a=airportInfo[code],m=metars[code],r=ends(code),model=forecastModel(code,m),w=model.forecast?model.state?.wind:m?.wind;

 const observation=m?.raw||m?.error||'Observation unavailable';
 const retained=metarFeedError&&m?.raw?'<span class="metar-retained">Feed refresh failed; showing retained observation.</span>':'';
 const category=categoryMarkup(m),report=metarBadge(code,observation,Boolean(m?.raw));
 return `<article class="airport" data-airport="${code}"><div class="airport-head"><button type="button" class="airport-grip" data-airport-drag="${esc(code)}" aria-label="Reorder ${esc(code)} airport: drag or use arrow keys" title="Drag to reorder; arrow keys also work" ${airportCount<2?'disabled':''}><svg viewBox="0 0 16 24" width="16" height="24" aria-hidden="true" focusable="false" fill="currentColor"><circle cx="4" cy="5" r="1.8"/><circle cx="12" cy="5" r="1.8"/><circle cx="4" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="4" cy="19" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg></button><div class="airport-top-row"><div class="icao">${esc(code)}</div>${category.tag}</div><div class="airport-actions">${diagramHeader(code)}<button type="button" class="airport-remove" data-remove="${esc(code)}" aria-label="Remove ${esc(code)} airport" title="Remove airport">×</button></div><button type="button" class="name" data-airport-name="${esc(code)}" id="airport-name-${esc(code)}" title="${esc(a?.name||'Airport not yet configured')}" aria-expanded="false">${esc(a?.name||'Airport not yet configured')}</button></div><section class="weather-row metar-panel" aria-label="${esc(code)} METAR"><div class="weather-copy">${metarStatus(m)}<div class="metar-raw" data-scan-flow>${report.raw}</div>${retained}${report.fallback?`<div class="report-fallback">${report.fallback}</div>`:''}</div></section>${tafBlock(code)}${atisBlock(code)}${reader?.summary(icao(code),Date.now(),notamTransportBlock(code))||''}${timeControl(code,m,model)}<div class="runways">${runwayBasis(code).startsWith('Wind components unavailable')?`<div class="forecast-range">${esc(runwayBasis(code))}</div>`:''}${r.length?`<table class="rw-table${model.forecast?' forecast-table':''}"><thead><tr><th>RWY</th><th>Head/Tail</th><th>Cross</th><th>NOTAMs</th></tr></thead><tbody>${r.map(id=>runwayRow(code,id,w,model.forecast?model.state:null)+(reader?.row(icao(code),id,r)||'')).join('')}</tbody></table>`:'<div class="empty">Runway data pending.</div>'}</div></article>`;
}
function render(){const reloadFocus=document.activeElement?.dataset?.notamReload,active=document.activeElement,activeId=active?.id,removeFocus=active?.dataset?.remove,dragFocus=active?.dataset?.airportDrag;
 const namesOpen=new Set([...document.querySelectorAll('[data-airport-name][aria-expanded="true"]')].map(el=>el.dataset.airportName));
 const atisOpen=new Set([...document.querySelectorAll('.atis-full[open]')].map(el=>el.closest('[data-airport]')?.dataset.airport));
 reader?.before();
 const cardContext={airportCount:airports.length,airportInfo,metars,ends,forecastModel,metarFeedError,categoryMarkup,esc,diagramHeader,metarBadge,metarStatus,tafBlock,atisBlock,reader,icao,timeControl,runwayRow,notamTransportBlock,runwayBasis};
 document.getElementById('cards').innerHTML=airports.map(code=>airportCardMarkup(code,cardContext)).join('');
 document.querySelectorAll('[data-airport]').forEach(el=>{const details=el.querySelector('.atis-full');if(details)details.open=atisOpen.has(el.dataset.airport);});
 document.querySelectorAll('[data-airport-name]').forEach(el=>{
  el.setAttribute('aria-expanded',String(namesOpen.has(el.dataset.airportName)));
  el.addEventListener('click',()=>el.setAttribute('aria-expanded',String(el.getAttribute('aria-expanded')!=='true')));
 });
 document.querySelectorAll('[data-observed-time]').forEach(el=>el.addEventListener('change',()=>{
  observedSelection.set(el.dataset.observedTime,el.value);render();
 }));
 document.querySelectorAll('[data-forecast-slider]').forEach(el=>{
  el.addEventListener('input',()=>{
   const code=el.dataset.forecastSlider;
   const report=tafData?.tafs?.find(item=>item.icaoId===airportInfo[code]?.icao);
   const when=forecastTimeline.stepTime(report,el.value);
   const output=document.querySelector('[data-forecast-output="'+code+'"]');
   if(output&&Number.isFinite(when))output.textContent=forecastTimeline.stamp(when);
  });
  el.addEventListener('change',()=>{
   const code=el.dataset.forecastSlider;
   const report=tafData?.tafs?.find(item=>item.icaoId===airportInfo[code]?.icao);
   const when=forecastTimeline.stepTime(report,el.value);
   if(Number.isFinite(when)){observedSelection.set(code,'taf:'+new Date(when).toISOString());render();}
  });
 });
 document.querySelectorAll('[data-forecast-date]').forEach(el=>el.addEventListener('change',()=>{
  const code=el.dataset.forecastDate;
  const report=tafData?.tafs?.find(item=>item.icaoId===airportInfo[code]?.icao);
  const range=forecastTimeline.bounds(report),when=forecastTimeline.time(el.value);
  if(range&&Number.isFinite(when)&&when>=range.start&&when<range.end){
   observedSelection.set(code,'taf:'+new Date(when).toISOString());
  }
  render();
 }));
 document.querySelectorAll('[data-remove]').forEach(b=>b.addEventListener('click',()=>{const index=airports.indexOf(b.dataset.remove);airports=airports.filter(x=>x!==b.dataset.remove);save();render();const next=airports[Math.min(index,airports.length-1)];([...document.querySelectorAll('[data-remove]')].find(el=>el.dataset.remove===next)||document.getElementById('iata'))?.focus();}));reader?.after();
 document.querySelectorAll('[data-notam-reload]').forEach(b=>b.addEventListener('click',()=>notamSnapshots?.refresh()));
 attachAirportReordering();
 if(reloadFocus)[...document.querySelectorAll('[data-notam-reload]')].find(b=>b.dataset.notamReload===reloadFocus)?.focus({preventScroll:true});
 else if(removeFocus)[...document.querySelectorAll('[data-remove]')].find(b=>b.dataset.remove===removeFocus)?.focus({preventScroll:true});
 else if(dragFocus)[...document.querySelectorAll('[data-airport-drag]')].find(b=>b.dataset.airportDrag===dragFocus)?.focus({preventScroll:true});
 else if(activeId)document.getElementById(activeId)?.focus?.({preventScroll:true});
}
// Airport order is the existing spatchin-airports array, including on reload.
function moveAirport(code,targetIndex){
 if(!AirportOrder.move(airports,code,targetIndex))return false;
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
  lastFetch=PublishedSnapshots.metars(data,targets,metars,lastFetch,icao,parseMetar,Date.now);
  metarFeedError=false;
 }catch(e){
  metarFeedError=true;
  for(const code of targets){if(!metars[code])metars[code]={error:'Published METAR feed unavailable',wind:null};}
  console.error('Spatchin METAR retrieval:',e);
 }finally{loading=false;render();}
}
document.getElementById('add-form').addEventListener('submit',e=>{e.preventDefault();const f=document.getElementById('iata'),code=f.value.trim().toUpperCase();if(!approvedCatalog.includes(code)){alert('Choose an IATA code from the approved C070 catalog.');return;}if(airports.includes(code)){alert(code+' is already displayed.');return;}if(airports.length>=30){alert('Maximum 30 airports.');return;}airports.push(code);save();render();f.value='';refresh();});
// Published snapshot validation and selection; no fetch, DOM, or application state.
const PublishedSnapshots=(()=>{
 function metars(data,targets,records,previousFetch,stationFor,parse,clock){
  if(!Array.isArray(data.metars))throw new Error('Unexpected METAR response');
  const updated=Date.parse(data.updated_utc||'');
  if(!Number.isFinite(updated)||updated>clock()+5*60*1000)throw new Error('Invalid METAR retrieval timestamp');
  const found=new Set();
  for(const m of data.metars){
   if(!m||typeof m!=='object'||typeof m.icaoId!=='string'||typeof m.rawOb!=='string'||!m.rawOb.trim())continue;
   if(typeof m.obsTime==='number'&&!Number.isFinite(new Date(m.obsTime*1000).getTime()))continue;
   const code=targets.find(c=>stationFor(c)===m.icaoId);
   if(!code)continue;
   const parsed=parse(m);
   if(!parsed.wind||!Number.isFinite(Date.parse(parsed.observed||'')))continue;
   const previous=records[code];
   if(!previous?.observed || Date.parse(parsed.observed)>=Date.parse(previous.observed))records[code]=parsed;
   found.add(code);
  }
  for(const code of targets){if(!found.has(code)&&!records[code])records[code]={error:'No valid METAR returned',wind:null};}
  return !previousFetch || updated>=Date.parse(previousFetch)?data.updated_utc:previousFetch;
 }
 function atis(data){
  if(!data.airports||!data.retrieved_utc)throw new Error('Invalid ATIS snapshot');
  return data;
 }
 function runways(data,catalog){
  if(!['TRUE','MAGNETIC'].includes(data.heading_reference)||!data.airports||!data.effective_date)throw new Error('Invalid FAA runway data');
  const magnetic=data.heading_reference==='MAGNETIC';
  const eligible=new Set(catalog);
  const published=Object.entries(data.airports);
  if(!published.length)throw new Error('FAA runway inventory empty');
  if(magnetic&&published.length!==eligible.size)throw new Error('Incomplete magnetic runway inventory');
  for(const [code,list] of published){
   if(!eligible.has(code)||!Array.isArray(list)||list.length<2||list.length>64||list.length%2)throw new Error(`Invalid ${code} runway inventory`);
   const ids=new Set();
   if(magnetic){
    const m=data.airport_metadata?.[code];
    if(!m||m.heading_method!=='runway-designation-magnetic'||!((m.magnetic_variation_deg===null&&m.magnetic_variation_year===null)||
       (Number.isFinite(m.magnetic_variation_deg)&&Math.abs(m.magnetic_variation_deg)<=180&&Number.isInteger(m.magnetic_variation_year)&&m.magnetic_variation_year>=1900&&m.magnetic_variation_year<=2100)))throw new Error(`Invalid ${code} magnetic variation`);
   }
   for(const item of list){
    if(!item||!/^((0[1-9]|[12][0-9]|3[0-6])[LRC]?)$/.test(item.id)||ids.has(item.id)||
       !(magnetic?item.magnetic_heading===RunwayWind.heading(item.id):(item.true_heading===null||(Number.isFinite(item.true_heading)&&item.true_heading>=0&&item.true_heading<360)))||
       typeof item.pair!=='string'||!item.pair.split('/').includes(item.id))throw new Error(`Invalid ${code} runway end`);
    ids.add(item.id);
   }
   if(list.some(item=>item.pair.split('/').length!==2||new Set(item.pair.split('/')).size!==2||!item.pair.split('/').every(id=>ids.has(id))))throw new Error(`Incomplete ${code} runway pair`);
   if(magnetic&&list.some(item=>item.pair.split('/').some(id=>list.find(end=>end.id===id)?.pair.split('/').sort().join('/')!==item.pair.split('/').sort().join('/'))))throw new Error(`Conflicting ${code} runway pair`);
  }
  for(const [code,count] of Object.entries({ORD:16,LAX:8,JFK:8,MEM:8})){
   if(!Array.isArray(data.airports[code])||data.airports[code].length!==count)throw new Error(`Missing verified ${code} runway ends`);
  }
  if(data.airport_coverage){
   const coverage=data.airport_coverage;
   if(Object.keys(coverage).length!==eligible.size||[...eligible].some(code=>!coverage[code]||
      !['available','unavailable'].includes(coverage[code].status)||
      (coverage[code].status==='available')!==Boolean(data.airports[code])))throw new Error('Invalid C070 runway coverage');
  }
  return data;
 }
 function tafs(data,previous,stations,reader,clock){
  if(!Array.isArray(data?.tafs))throw new Error('Invalid published TAF snapshot');
  const published=reader.time(data.updated_utc);
  if(!Number.isFinite(published)||published>clock()+5*60*1000)throw new Error('Invalid TAF publication time');
  const available=new Map((previous?.tafs||[]).map(item=>[item.icaoId,item]));
  let accepted=0;
  for(const item of data.tafs){
   if(!Object.values(stations).some(a=>a.icao===item?.icaoId)||!reader.valid(item,item.icaoId,clock()))continue;
   accepted++;
   const earlier=available.get(item.icaoId);
   if(!earlier||reader.time(item.issueTime)>reader.time(earlier.issueTime)||
    (reader.time(item.issueTime)===reader.time(earlier.issueTime)&&
     (item.fcsts?.length||0)>=(earlier.fcsts?.length||0)))available.set(item.icaoId,item);
  }
  if(!accepted)throw new Error('No valid TAFs in published snapshot');
  return {tafs:[...available.values()],updated_utc:data.updated_utc};
 }
 return {metars,atis,runways,tafs};
})();
async function refreshDiagrams(){
 if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return;
 try{
  const response=await fetch('./data/airport-diagrams.json',{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(data?.schema_version!==1||!data.airports)throw new Error('Invalid diagram index');
  diagramIndex=data;render();
 }catch(e){console.info('FAA diagram index unavailable; check current edition at FAA:',e.message);}
}
async function refreshRunways(){
 if(typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return;
 try{
  const response=await fetch(`./data/runways.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  runwayData=PublishedSnapshots.runways(data,approvedCatalog);render();
 }catch(e){console.info('FAA runway data not yet available; retaining previously verified headings:',e.message);}
}
async function refreshAtis(){
 try{
  const response=await fetch(`./data/atis.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  atisData=PublishedSnapshots.atis(data);atisRetrieved=data.retrieved_utc;render();
 }catch(e){console.info('ATIS snapshot unavailable:',e.message);}
}
async function refreshTafs(){
 if(typeof forecastReader==='undefined'||typeof SPATCHIN_SYNTHETIC_PREVIEW!=='undefined')return;
 try{
  const response=await fetch(`./data/tafs.json?t=${Date.now()}`,{cache:'no-store'});
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  tafData=PublishedSnapshots.tafs(data,tafData,airportInfo,forecastReader,Date.now);tafFeedError=false;
 }catch(e){tafFeedError=true;console.info('TAF snapshot unavailable; retaining previous reports:',e.message);}
 render();
}
function clock(){document.getElementById('clock').textContent=new Date().toISOString().replace('T',' ').slice(0,19)+'Z';}
function startDashboard(){
 clock();setInterval(clock,1000);render();refresh();refreshRunways();refreshDiagrams();refreshAtis();refreshTafs();notamSnapshots?.refresh();notamSnapshots?.start();
 setInterval(refresh,120000);setInterval(render,30000);setInterval(refreshRunways,3600000);setInterval(refreshDiagrams,3600000);setInterval(refreshAtis,120000);setInterval(refreshTafs,120000);
}
async function loadForecastModules(){
 const [reader,timeline]=await Promise.allSettled([import('./taf-reader.js'),import('./taf-timeline.js')]);
 if(reader.status==='fulfilled')forecastReader=reader.value.TafReader;
 else console.info('Forecast reader module unavailable:',reader.reason?.message);
 if(timeline.status==='fulfilled')forecastTimeline=timeline.value.TafTimeline;
 else console.info('Forecast timeline module unavailable:',timeline.reason?.message);
 // Forecast availability must not delay the initial cards or the other feeds.
 if(forecastReader)refreshTafs();
}
startDashboard();
if(enableForecast)loadForecastModules();
return {render,refreshNotams:()=>notamSnapshots?.refresh()};
}

// Core dependencies were optional classic scripts. Keep their fallback behavior
// if a module fails to load; forecast loading must not delay initial cards.
async function bootstrapDashboard(){
 const [catalog,reader,snapshots]=await Promise.allSettled([
  import('./airport-catalog.js'),import('./notam-reader.js'),import('./notam-snapshots.js')
 ]);
 for(const [name,result] of [['Airport catalog',catalog],['NOTAM reader',reader],['NOTAM snapshots',snapshots]]){
  if(result.status==='rejected')console.info(name+' module unavailable:',result.reason?.message);
 }
 mountDashboard({
  AirportCatalog:catalog.value?.AirportCatalog,AirportMetadata:catalog.value?.AirportMetadata,
  NotamReader:reader.value?.NotamReader,NotamSnapshots:snapshots.value?.NotamSnapshots,enableForecast:true
 });
}
if(typeof document!=='undefined'&&document.querySelector('script[type="module"][data-forecast="true"]')){
 bootstrapDashboard();
}
