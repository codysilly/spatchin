'use strict';
// SPA-13: interpretation of saved AWC decoded TAF periods. No provider calls.
// All times are UTC. Uncertain changes remain distinct from prevailing winds.
export const TafTimeline=(()=>{
  const STEP=30*60000,HOUR=3600000,STALE_MS=6*HOUR;
  function time(value){
    // AWC fields use Unix seconds; internal slider/Date values use milliseconds.
    if(typeof value==='number')return Number.isFinite(value)?(Math.abs(value)>=1e11?value:value*1000):NaN;
    if(typeof value!=='string'||!value.trim())return NaN;
    const text=value.trim().replace(' ','T');
    return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)?text:text+'Z');
  }
  function bounds(report){
    if(!report)return null;
    const start=time(report.validTimeFrom),end=time(report.validTimeTo);
    return Number.isFinite(start)&&Number.isFinite(end)&&end>start&&end-start<=72*HOUR?{start,end}:null;
  }
  function stamp(ms){return new Date(ms).toISOString().slice(0,16).replace('T',' ')+'Z';}
  function localInput(ms){return Number.isFinite(ms)?new Date(ms).toISOString().slice(0,16):'';}
  function windOf(group){
    if(!group||group.wspd===null||group.wspd===undefined||group.wspd==='')return null;
    const speed=Number(group.wspd);
    if(!Number.isFinite(speed)||speed<0||speed>250)return null;
    const raw=group.wdir,variable=typeof raw==='string'&&raw.toUpperCase()==='VRB';
    const direction=raw===null||raw===undefined||raw===''||variable?null:Number(raw);
    if(!variable&&speed>0&&(!Number.isFinite(direction)||direction<0||direction>360))return null;
    const rawGust=group.wgst;
    const gust=rawGust===null||rawGust===undefined||rawGust===''?null:Number(rawGust);
    if(gust!==null&&(!Number.isFinite(gust)||gust<speed||gust>300))return null;
    return {speed,direction:speed===0?0:direction===360?0:direction,gust,variable:variable&&speed>0};
  }
  function periods(report){
    const validity=bounds(report);
    if(!validity||!Array.isArray(report.fcsts))return [];
    return report.fcsts.slice(0,64).map((value,index)=>{
      if(!value||typeof value!=='object'||Array.isArray(value))return null;
      const start=time(value.timeFrom),end=time(value.timeTo);
      if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end||start>validity.end||end<validity.start)return null;
      const raw=typeof value.fcstChange==='string'?value.fcstChange.trim().toUpperCase():'';
      const kind=raw===''?'BASE':raw==='FM'?'FM':raw==='TEMPO'?'TEMPO':raw==='BECMG'?'BECMG':raw.startsWith('PROB')?'PROB':'OTHER';
      const bec=time(value.timeBec);
      const transitionEnd=kind==='BECMG'&&Number.isFinite(bec)&&bec>start&&bec<=end?bec:end;
      return {kind,index,start:Math.max(start,validity.start),end:Math.min(end,validity.end),
        transitionEnd,wind:windOf(value),probability:value.probability,raw};
    }).filter(Boolean);
  }
  function label(period){
    if(period.kind==='PROB'){
      const parsed=Number(period.probability);
      const fromName=period.raw.match(/^PROB(\d{2})/);
      const percentage=Number.isFinite(parsed)&&parsed>0&&parsed<=100?parsed:fromName?Number(fromName[1]):null;
      return percentage===null?'PROB (probability unspecified)':`PROB ${percentage}%`;
    }
    return period.kind;
  }
  function select(report,instant,now=Date.now()){
    const validity=bounds(report),at=time(instant);
    if(!validity||!Number.isFinite(at)||at<validity.start||at>=validity.end)
      return {status:'outside',wind:null,alternatives:[],notes:['Time outside TAF validity']};
    if(now>=validity.end)
      return {status:'expired',wind:null,alternatives:[],notes:['TAF no longer valid']};
    const issued=time(report.issueTime);
    if(!Number.isFinite(issued)||issued>now+300000||now-issued>STALE_MS)
      return {status:'stale',wind:null,alternatives:[],notes:['TAF issue time is stale or invalid']};
    if(!Array.isArray(report.fcsts)||report.fcsts.length===0)
      return {status:'missing',wind:null,alternatives:[],notes:['Decoded forecast periods unavailable']};
    const list=periods(report);
    if(!list.length)return {status:'missing',wind:null,alternatives:[],notes:['No valid forecast periods']};
    const prev=list.filter(p=>(p.kind==='BASE'||p.kind==='FM')&&p.start<=at&&at<p.end)
      .sort((a,b)=>b.start-a.start||(b.kind==='FM')-(a.kind==='FM')||b.index-a.index)[0];
    const notes=[], alternatives=[];
    let wind=prev?.wind||null, source=prev?.kind||'UNKNOWN',latest=prev?.start??-Infinity;
    // BECMG is not an instantaneous change. No single prevailing value is
    // asserted during a transition that contains a forecast wind change.
    const changes=list.filter(p=>p.kind==='BECMG'&&p.wind&&p.start>=latest)
      .sort((a,b)=>a.start-b.start||a.index-b.index);
    let transition=false;
    for(const change of changes){
      if(at>=change.start&&at<change.transitionEnd){
        transition=true;
        notes.push('BECMG wind transition: change time unknown');
      }else if(at>=change.transitionEnd&&change.transitionEnd>=latest){
        wind=change.wind;source='BECMG';latest=change.transitionEnd;
        transition=false;
      }
    }
    for(const period of list){
      if((period.kind==='TEMPO'||period.kind==='PROB')&&period.start<=at&&at<period.end){
        const name=label(period);
        alternatives.push({label:name,wind:period.wind,from:period.start,to:period.end});
        notes.push(period.wind?`${name} alternate wind may occur`:`${name} other weather; no alternate wind specified`);
      }
      if(period.kind==='OTHER'&&period.start<=at&&at<period.end){
        notes.push('Unrecognized TAF group; verify raw TAF');
      }
    }
    return {status:transition?'transition':wind?'available':'missing',wind:transition?null:wind,
      source,alternatives,notes,at,issued,validity};
  }
  // Split only at prevailing boundaries and BECMG transitions, not at temporary
  // alternatives. The latter are evaluated over the entire selected interval.
  function ranges(report){
    const validity=bounds(report);
    if(!validity)return [];
    const points=new Set([validity.start,validity.end]);
    const add=ms=>{if(ms>validity.start&&ms<validity.end)points.add(ms);};
    for(const p of periods(report)){
      if(p.kind==='BASE'||p.kind==='FM'){add(p.start);add(p.end);}
      if(p.kind==='BECMG'&&p.wind){add(p.start);add(p.transitionEnd);}
    }
    const times=[...points].sort((a,b)=>a-b);
    return times.slice(0,-1).map((start,i)=>({start,end:times[i+1]}));
  }
  function rangeLabel(range){
    const part=ms=>{const s=new Date(ms).toISOString();return {day:s.slice(0,10),label:s.slice(8,10),clock:s.slice(11,16).replace(':','')};};
    const a=part(range.start),b=part(range.end);
    return a.label+'/'+a.clock+'–'+(a.day===b.day?'':b.label+'/')+b.clock+'Z';
  }
  function selectRange(report,range,now=Date.now()){
    if(!ranges(report).some(r=>r.start===range.start&&r.end===range.end))
      return {status:'outside',wind:null,alternatives:[],notes:['Time outside TAF validity']};
    const state=select(report,range.start,now);
    if(['outside','expired','stale'].includes(state.status))return state;
    const points=new Set([range.start]);
    for(const p of periods(report)){
      for(const ms of [p.start,p.end,p.transitionEnd])if(ms>range.start&&ms<range.end)points.add(ms);
    }
    const samples=[...points].sort((a,b)=>a-b).map(at=>select(report,at,now));
    const alternatives=new Map(),notes=new Set();
    for(const sample of samples){
      for(const note of sample.notes)notes.add(note);
      for(const alt of sample.alternatives){
        const key=JSON.stringify(alt);
        if(!alternatives.has(key))alternatives.set(key,{...alt,label:alt.label+' '+rangeLabel({start:Math.max(alt.from,range.start),end:Math.min(alt.to,range.end)})});
      }
    }
    // A range must not claim one prevailing wind if the decoded values disagree.
    const uniform=samples.every(s=>s.status===state.status&&JSON.stringify(s.wind)===JSON.stringify(state.wind));
    if(!uniform)notes.add('Prevailing wind varies or is unavailable within this range; verify exact UTC time');
    return {...state,status:uniform?state.status:samples.some(s=>s.status==='transition')?'transition':'missing',
      wind:uniform?state.wind:null,alternatives:[...alternatives.values()],notes:[...notes]};
  }
  function steps(report){
    const range=bounds(report);
    return range?Math.max(0,Math.floor((range.end-range.start-1)/STEP)):0;
  }
  function stepTime(report,index){
    const range=bounds(report);
    if(!range)return NaN;
    return range.start+Math.max(0,Math.min(steps(report),Number(index)||0))*STEP;
  }
  function stepIndex(report,instant){
    const range=bounds(report),at=time(instant);
    return range&&Number.isFinite(at)?Math.max(0,Math.min(steps(report),Math.round((at-range.start)/STEP))):0;
  }
  function initialTime(report,now=Date.now()){
    const range=bounds(report);
    if(!range)return NaN;
    return now>=range.start&&now<range.end?stepTime(report,stepIndex(report,now)):range.start;
  }
  return {time,bounds,stamp,localInput,windOf,periods,select,ranges,rangeLabel,selectRange,steps,stepTime,stepIndex,initialTime,STEP,STALE_MS};
})();
