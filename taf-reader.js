'use strict';
// Pure display helper. The dashboard reads published JSON, never the live AWC API.
export const TafReader=(()=>{
  const HOUR=3600000,STALE_MS=6*HOUR;
  function time(value){
    if(typeof value==='number')return Number.isFinite(value)?value*1000:NaN;
    if(typeof value!=='string'||!value.trim())return NaN;
    let input=value.trim().replace(' ','T');
    if(!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(input))input+='Z';
    return Date.parse(input);
  }
  function esc(value){return String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  // Display-only layout: each change group starts on its own indented line.
  // Keep PROB30 TEMPO together as one combined group; do not alter rawTAF.
  function formatRaw(raw){
    const lines=[],tokens=raw.trim().split(/\s+/);
    let current=[];
    for(const token of tokens){
      const boundary=/^(?:FM\d{6}|BECMG|BCMG|TEMPO|PROB(?:\d{2})?)$/.test(token);
      const combined=token==='TEMPO'&&current.length===1&&/^PROB\d{2}$/.test(current[0]);
      if(boundary&&current.length&&!combined){
        lines.push(current.join(' '));
        current=[];
      }
      current.push(token);
    }
    if(current.length)lines.push(current.join(' '));
    return lines.map((line,index)=>index?'  '+line:line).join('\n');
  }
  function valid(report,station,now=Date.now()){
    if(!station||!report||report.icaoId!==station||typeof report.rawTAF!=='string'||!report.rawTAF.trim())return false;
    const issued=time(report.issueTime),from=time(report.validTimeFrom),to=time(report.validTimeTo);
    return [issued,from,to].every(Number.isFinite)&&issued<=now+300000&&issued<=to&&to>from&&to-from<=72*HOUR;
  }
  function stamp(ms){return new Date(ms).toISOString().slice(0,16).replace('T',' ')+'Z';}
  function render({code,station,report,feedError=false,now=Date.now()}){
    const source=station?`<a href="https://aviationweather.gov/api/data/taf?ids=${encodeURIComponent(station)}&amp;format=raw" target="_blank" rel="noopener noreferrer">AWC TAF source</a>`:'';
    const usable=valid(report,station,now);
    let content;
    if(!usable){
      content=`<div class="taf-status taf-unavailable">TAF UNAVAILABLE</div><div>${station?'No verified published forecast.':'Station mapping not verified.'}</div>${source}`;
    }else{
      const issued=time(report.issueTime),from=time(report.validTimeFrom),to=time(report.validTimeTo);
      const state=now>=to?'NO LONGER VALID':now<from?'TAF NOT YET VALID':now-issued>STALE_MS||now<issued-300000?'TAF STALE':'TAF CURRENT';
      const statusClass=state==='NO LONGER VALID'?' taf-expired':'';
      content=`<div class="taf-status${statusClass}">${state}</div><pre class="taf-raw">${esc(formatRaw(report.rawTAF))}</pre><div class="taf-meta">Issued ${stamp(issued)} · Valid ${stamp(from)}–${stamp(to)}</div>${feedError?'<div class="taf-retained">Snapshot refresh failed; retained previous TAF.</div>':''}${source}`;
    }
    return `<section class="taf" aria-label="${esc(code)} TAF"><strong>TAF</strong><div class="taf-copy">${content}</div></section>`;
  }
  return {valid,render,time,formatRaw,STALE_MS};
})();
