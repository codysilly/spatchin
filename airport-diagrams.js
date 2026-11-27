// A catalog entry identifies a source PDF; it does not validate the chart contents.
export function currentDiagram(index, code, icao, now=Date.now()){
 if(index?.schema_version!==1||typeof index.cycle!=='string'||!/^\d{2}(0[1-9]|1[0-3])$/.test(index.cycle))return null;
 const utc=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
 if(!utc.test(index.effective_from_utc)||!utc.test(index.effective_to_utc))return null;
 const start=Date.parse(index.effective_from_utc),end=Date.parse(index.effective_to_utc);
 if(!Number.isFinite(now)||!Number.isFinite(start)||!Number.isFinite(end)||end-start!==28*86400000||now<start||now>=end)return null;
 if(typeof code!=='string'||!/^([A-Z]{3})$/.test(code)||typeof icao!=='string'||!(/^[A-Z0-9]{4}$/).test(icao))return null;
 const entry=index.airports?.[code];
 if(entry?.icao!==icao||typeof entry.pdf_name!=='string'||!(/^[A-Za-z0-9_-]+\.PDF$/i).test(entry.pdf_name))return null;
 return {url:'https://aeronav.faa.gov/d-tpp/'+index.cycle+'/'+entry.pdf_name,cycle:index.cycle,effective_from_utc:index.effective_from_utc,effective_to_utc:index.effective_to_utc};
}
export function currentDiagramMarkup(index, code, icao, esc, now=Date.now()){
 const diagram=currentDiagram(index,code,icao,now);
 if(!diagram)return '';
 const dates='FAA d-TPP cycle '+diagram.cycle+'; effective '+diagram.effective_from_utc+' until '+diagram.effective_to_utc+'; check FAA for corrections';
 return `<div class="airport-diagram"><a href="${esc(diagram.url)}" target="_blank" rel="noopener" title="${esc(dates)}" aria-label="Airport diagram for ${esc(code)}; ${esc(dates)}; opens in a new tab"><span class="diagram-link-text">Airport diagram </span><span aria-hidden="true">↗</span></a></div>`;
}

// User-initiated FAA search, not evidence of an available/current PDF.
export function diagramSearchMarkup(icao,esc){
 if(typeof icao!=='string'||!(/^[A-Z0-9]{4}$/).test(icao))return '';
 const url='https://www.faa.gov/air_traffic/flight_info/aeronav/digital_products/dtpp/search/?ident='+encodeURIComponent(icao);
 const label='Find FAA diagram for '+icao+'; select current edition and search for '+icao+'; opens in a new tab';
 return `<div class="airport-diagram"><a href="${esc(url)}" target="_blank" rel="noopener" title="${esc(label)}" aria-label="${esc(label)}"><span class="diagram-link-text">Find FAA diagram </span><span aria-hidden="true">↗</span></a></div>`;
}
