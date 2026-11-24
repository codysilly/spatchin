// Generate the existing browser catalog from the reviewed offline registry.
import { readFileSync, writeFileSync } from 'node:fs';
const file = p => new URL('../'+p, import.meta.url);
const codes = readFileSync(file('docs/reference/c070-airports.csv'),'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
const entries = JSON.parse(readFileSync(file('docs/reference/c070-airport-registry.json'),'utf8')).airports;
if (codes.length!==130 || new Set(codes).size!==130 || !Array.isArray(entries) || entries.length!==130) throw Error('Invalid C070 count');
const lookup = new Map(entries.map(a=>[a.iata,a]));
if (lookup.size!==130 || new Set(entries.map(a=>a.icao)).size!==130 || codes.some(c=>!(/^[A-Z]{3}$/.test(c)) || !lookup.has(c) || !/^[A-Z0-9]{4}$/.test(lookup.get(c).icao) || typeof lookup.get(c).name!=='string' || !lookup.get(c).name.trim())) throw Error('Invalid C070 identity');
const metadata = Object.fromEntries(codes.map(c=>[c,{name:lookup.get(c).name,icao:lookup.get(c).icao}]));
const content = '/* Generated from reviewed C070 registry; run node scripts/build_airport_catalog.mjs. */\n'+
 "'use strict';\n"+
 'const AirportCatalog=Object.freeze('+JSON.stringify(codes)+');\n'+
 'const AirportMetadata=Object.freeze('+JSON.stringify(metadata,null,2)+');\n'+
 "if(typeof module!=='undefined')module.exports=AirportCatalog;\n";
const output=file('airport-catalog.js');
if(process.argv.includes('--check')){
 if(readFileSync(output,'utf8')!==content)throw Error('Airport catalog differs from reviewed registry');
}else writeFileSync(output,content);
