/* Reading only: text references do not establish applicability or availability. */
'use strict';
export const NotamReader = (() => {
 // Character references avoid HTML's CR/CRLF normalization of source text.
 const esc=s=>String(s??'Not supplied').replace(/[&<>"'\r]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','\r':'&#13;'}[c]));
 let snapshot=null, error=null;
 const opened=new Set(),scrollPositions=new Map(); let focus=null;
 function references(text, inventory){
  const found=[]; const known=new Set(inventory);
  const pattern=/\bRWYS?\s+((?:3[0-6]|[12][0-9]|0?[1-9])[LRC]?(?:(?:\s*[/,]\s*|\s+AND\s+)(?:RWYS?\s+)?(?:3[0-6]|[12][0-9]|0?[1-9])[LRC]?)*)\b/gi;
  for(const match of String(text??'').matchAll(pattern)){
   const start=match.index+match[0].indexOf(match[1]);
   for(const token of match[1].matchAll(/(?:3[0-6]|[12][0-9]|0?[1-9])[LRC]?/gi)){
    const raw=token[0], id=raw.toUpperCase().padStart(/[LRC]$/i.test(raw)?3:2,'0');
    if(known.has(id))found.push({id,start:start+token.index,end:start+token.index+raw.length,raw});
   }
  }
  // Narrow prefix grammar from the OpenAPI example: "27 RWY END ...".
  // Do not recognize bare numbers, arbitrary text before RWY, or reciprocal ends.
  for(const match of String(text??'').matchAll(/\b((?:3[0-6]|[12][0-9]|0?[1-9])[LRC]?)\s+RWY\s+END\b/gi)){
   const raw=match[1], id=raw.toUpperCase().padStart(/[LRC]$/i.test(raw)?3:2,'0');
   if(known.has(id))found.push({id,start:match.index,end:match.index+raw.length,raw});
  }
  return found.filter(r=>!/[A-Z0-9_]/i.test(String(text)[r.start-1]||'')&&!/[A-Z0-9_]/i.test(String(text)[r.end]||'')).sort((a,b)=>a.start-b.start);
 }
 // Fixed family order and numeric tokens make this comparator transitive. Never
 // derive a source year from retrieval/effective dates or expand two-digit years.
 const natural=(a,b)=>{const aa=String(a).match(/\d+|\D+/g)||[],bb=String(b).match(/\d+|\D+/g)||[];for(let i=0;i<Math.min(aa.length,bb.length);i++){const x=aa[i],y=bb[i];const c=/^\d+$/.test(x)&&/^\d+$/.test(y)?Number(x)-Number(y):(x<y?-1:x>y?1:0);if(c)return c;}return aa.length-bb.length;};
 function sortKey(n){const raw=String(n.number||n.id||'').toUpperCase(),year=n.year??n.original_feature?.properties?.coreNOTAMData?.notam?.year;const explicit=/^\d{4}$/.test(String(year));const d=raw.match(/^(?:![A-Z0-9]{3,4}\s+)?(0?[1-9]|1[0-2])\/(\d+)$/),intl=raw.match(/^([A-Z]+)(\d+)\/(\d{2}|\d{4})$/);return [explicit?0:1,explicit?Number(year):0,d?0:intl?1:raw?2:3,d?`${Number(d[1])}/${Number(d[2])}`:intl?`${intl[1]}/${intl[3]}/${Number(intl[2])}`:raw];}
 function compare(a,b){const x=sortKey(a),y=sortKey(b);for(let i=0;i<x.length;i++){const c=i<3?x[i]-y[i]:natural(x[i],y[i]);if(c)return c;}return 0;}
 function records(code,inventory){return (snapshot?.airports?.[code]?.notices||[]).map((n,i)=>({...n,key:`${code}-${i}`,references:[...references(n.text,inventory),...(Array.isArray(n.formatted_texts)?n.formatted_texts:[]).flatMap((t,i)=>typeof t?.text==='string'?references(t.text,inventory).map(r=>({...r,representation:`formatted_texts[${i}].text` })):[])]})).sort(compare);}
 function airportRecords(code){return (snapshot?.airports?.[code]?.notices||[]).map((n,i)=>({...n,key:`${code}-${i}`})).sort(compare);}
 function verifiedZero(code){const e=snapshot?.airports?.[code];return Boolean(e&&e.notices.length===0&&e.completeness==='VERIFIED'&&e.zero_verified===true&&typeof e.verification_reference==='string'&&e.verification_reference.trim());}
 function availability(code){const e=snapshot?.airports?.[code];return !e?'Unavailable — no accepted airport snapshot':verifiedZero(code)?'Explicitly verified zero airport notices; not an operational status':'Coverage UNKNOWN — snapshot references only';}
 function summary(code){
  const entry=snapshot?.airports?.[code],stamp=Date.parse(snapshot?.retrieved_utc);
  const retrieved=Number.isFinite(stamp)?new Date(stamp).toISOString().slice(0,16).replace('T',' ')+' UTC':'Unavailable';
  const all=entry?airportRecords(code):[];
  return `<section id="coverage-${esc(code)}" class="notam-summary" aria-label="${esc(code)} NOTAM coverage"><strong>${!entry?'NOTAM data unavailable':'NOTAM snapshot'}</strong>${entry?`<p>Retrieved: ${esc(retrieved)}</p>`:''}${snapshot?.synthetic?'<p>SYNTHETIC — NO LIVE DATA</p>':''}${error?`<p role="status">${esc(error)}</p>${entry?'<p>Showing retained snapshot after reader error.</p>':''}`:''}${entry?`<details class="airport-notam-list" id="airport-notams-${esc(code)}"><summary>All airport snapshot notices (${all.length})</summary>${all.length?list(all):'<p>No notices in this airport snapshot.</p>'}</details>`:''}</section>`;
 }
 function cell(code,id,inventory){const n=records(code,inventory).filter(n=>n.references.some(r=>r.id===id)).length;return `<td class="unknown"><button id="toggle-${esc(code)}-${esc(id)}" type="button" data-reader-open="${esc(code)}-${esc(id)}" aria-label="NOTAMs (${n}) for runway ${esc(id)} at ${esc(code)}" aria-describedby="coverage-${esc(code)}" aria-expanded="false" aria-controls="reader-${esc(code)}-${esc(id)}">NOTAMs (${n})</button><small class="reader-note">${esc(!snapshot?.airports?.[code]?'Unavailable':n?'Literal matches':verifiedZero(code)?'Verified zero':'No literal matches')}</small></td>`;}
 function localTexts(n){return (Array.isArray(n.formatted_texts)?n.formatted_texts:[]).filter(t=>t?.type==='LOCAL_FORMAT'&&typeof t.text==='string').map(t=>t.text);}
 function list(items){return `<div class="notice-list">${items.map(n=>{const texts=localTexts(n);return `<article class="reader-notice" data-reader-key="${esc(n.key)}">${texts.length?texts.map(text=>`<p class="reader-raw">${esc(text)}</p>`).join(''):'<p class="local-unavailable">LOCAL_FORMAT text unavailable.</p>'}</article>`;}).join('')}</div>`;}
 function row(code,id,inventory){const items=records(code,inventory).filter(n=>n.references.some(r=>r.id===id));return `<tr id="reader-${esc(code)}-${esc(id)}" class="notam-detail-row" data-reader-inline hidden><td colspan="4"><section id="scroll-${esc(code)}-${esc(id)}" class="inline-reader" data-reader-scroll tabindex="0" role="region" aria-label="${esc(code)} runway ${esc(id)} source notices" aria-describedby="coverage-${esc(code)}"><div class="reader-scroll-title" data-scan-ignore>${esc(code)} / Runway ${esc(id)} source notices</div>${items.length?list(items):`<p>${!snapshot?.airports?.[code]?'NOTAM data unavailable.':verifiedZero(code)?'Verified zero notices in this airport snapshot.':'No literal references in this snapshot.'}</p>`}</section></td></tr>`;}
 function before(){
  if(typeof document==='undefined'||!document.querySelectorAll)return;
  opened.clear();
  document.querySelectorAll('[data-reader-inline]').forEach(el=>{if(!el.hidden)opened.add(el.id);});
  document.querySelectorAll('[data-reader-scroll]').forEach(el=>{if(!el.closest('[data-reader-inline]')?.hidden)scrollPositions.set(el.id,el.scrollTop);});
  const active=document.activeElement;
  focus=active?.matches?.('[data-reader-scroll]')?{scroll:active.id}:active?.dataset?.readerOpen?{button:active.dataset.readerOpen}:null;
 }
 function after(){
  if(typeof document==='undefined'||!document.querySelectorAll)return;
  document.querySelectorAll('[data-reader-inline]').forEach(el=>{el.hidden=!opened.has(el.id);});
  document.querySelectorAll('[data-reader-scroll]').forEach(el=>{if(!el.closest('[data-reader-inline]')?.hidden)el.scrollTop=scrollPositions.get(el.id)||0;});
  document.querySelectorAll('[data-reader-open]').forEach(b=>{
   const panel=document.getElementById('reader-'+b.dataset.readerOpen);
   const sync=()=>b.setAttribute('aria-expanded',String(Boolean(panel&&!panel.hidden)));
   sync();panel?.addEventListener('scan:reveal',sync);
   b.addEventListener('click',()=>{
   const el=document.getElementById('reader-'+b.dataset.readerOpen);
   if(el){el.hidden=!el.hidden;if(!el.hidden){const region=el.querySelector('[data-reader-scroll]');if(region)region.scrollTop=scrollPositions.get(region.id)||0;}sync();}
  });});
  if(focus){const target=focus.scroll?document.getElementById(focus.scroll):focus.button?[...document.querySelectorAll('[data-reader-open]')].find(el=>el.dataset.readerOpen===focus.button):null;target?.focus({preventScroll:true});}
 }
 function set(data,problem=null){snapshot=data;error=problem;}
 return {references,records,airportRecords,compare,availability,summary,cell,row,localTexts,before,after,set};
})();
