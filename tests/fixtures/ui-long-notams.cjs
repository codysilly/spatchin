// Entirely synthetic UI regression data. Never a provider response or production feed.
'use strict';
module.exports=()=>Array.from({length:32},(_,i)=>({
 id:`SYNTHETIC-LONG-${i}`,number:`11/${i+1}`,source:'Synthetic UI test fixture only',
 text:`SYNTHETIC RWY 36L source record ${i+1}.\r\n`+
  Array.from({length:6},(_,line)=>`Illustrative complete line ${line+1}: Unicode 🙂; <unsafe> & literal wording preserved.`).join('\r\n')+
  '\rStandalone CR\nStandalone LF'+(i===30?'\nLOWER_MATCH_A':i===31?'\nLOWER_MATCH_B':''),
 formatted_texts:[{type:'LOCAL_FORMAT',field:'simpleText',text:`SYNTHETIC LOCAL_FORMAT RWY 36L record ${i+1}.\r\n`+
  Array.from({length:6},(_,line)=>`Local line ${line+1}: complete supplied wording 🙂; <unsafe> & literal characters.`).join('\r\n')+
  '\rStandalone CR\nStandalone LF'+(i===30?'\nLOWER_MATCH_A':i===31?'\nLOWER_MATCH_B':'')},
  {type:'ICAO',field:'formattedText',text:'SYNTHETIC ICAO_HIDDEN_ONLY RWY 36L; never displayed or searched.'}],
 warnings:i===0?['SYNTHETIC supplied warning — retain this text exactly.']:[],
 effectiveStart:'2026-11-01T00:00:00Z',effectiveEnd:'2026-11-30T23:59:00Z'
}));
