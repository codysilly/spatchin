const {test}=require('node:test');
const assert=require('node:assert/strict');
const reader=require('../notam-reader.js').NotamReader;
const snapshots=require('../notam-snapshots.js').NotamSnapshots;
const render=(code,inventory)=>reader.summary(code)+reader.row(code,inventory[0]||'09',inventory);
test('explicit text references retain exact offsets and never infer reciprocals',()=>{
 const text='🙂 RWY 18L and 36R; TWY A near RWY 9.';
 const refs=reader.references(text,['18L','36R','09','27']);
 assert.deepEqual(refs.map(r=>r.id),['18L','36R','09']);
 for(const ref of refs)assert.equal(text.slice(ref.start,ref.end),ref.raw);
 assert.deepEqual(reader.references('RWY 18L',['18L','36R']).map(r=>r.id),['18L']);
 assert.deepEqual(reader.references('18L lights; RWY 99; RWY 18LX; RWY 018L',['18L']),[]);
});
test('duplicates, raw times, missing text, explicit scope and unmatched notices are retained',()=>{
 reader.set({retrieved_utc:'old raw retrieval',airports:{KMEM:{notices:[{id:'same',text:'RWY 18L',effectiveEnd:'PERM'},{id:'same',text:'General report'},{id:'wide',text:'Airport report',scope:'airport-wide'},{id:'missing'}]}}});
 const records=reader.records('KMEM',['18L','36R']);assert.equal(records.length,4);assert.notEqual(records[0].key,records[1].key);
 assert.equal(reader.airportRecords('KMEM').length,4);
 const html=render('KMEM',['18L','36R']);
 assert.equal(records.find(n=>n.effectiveEnd).effectiveEnd,'PERM');assert.match(html,/LOCAL_FORMAT text unavailable/);assert.match(html,/<span class="notam-title">NOTAM<\/span>/);assert.match(html,/Retrieved: Unavailable/);assert.doesNotMatch(html,/Completeness:|Historical snapshot/);
 assert.equal(records.filter(n=>!n.references.length&&n.scope!=='airport-wide').length,2);assert.equal(records.filter(n=>n.scope==='airport-wide').length,1);assert.doesNotMatch(html,/Unmatched \/ scope|airport-wide/);assert.doesNotMatch(html,/All airport snapshot notices|Literal matches/);
 assert.match(reader.cell('KMEM','36R',['18L','36R']),/NOTAMs \(0\)/);
});
test('source strings are escaped; unavailable and retained-error states are explicit',()=>{
 reader.set({airports:{KMEM:{notices:[{text:'RWY 18L <img src=x onerror=alert(1)>',source:'<script>',formatted_texts:[{type:'LOCAL_FORMAT',text:'RWY 18L <img src=x onerror=alert(1)>'}]}]}}},'Refresh failed');
 const html=render('KMEM',['18L']);assert.ok(!html.includes('<img'));assert.match(html,/&lt;img/);assert.match(html,/retained snapshot/);
 reader.set(null);assert.match(render('KMEM',[]),/NOTAM data unavailable/i);
});

// Documentation-derived grammar; not a captured live NOTAM.
test('prefix runway-end references require a complete designation and exact RWY END context',()=>{
 const text='🙂 27 RWY END ID LGT U/S; RWY 09';
 const refs=reader.references(text,['09','27']);
 assert.deepEqual(refs.map(r=>r.id),['27','09']);
 for(const r of refs)assert.equal(text.slice(r.start,r.end),r.raw);
 for(const text of ['127 RWY END','027 RWY END','27X RWY END','27 lights near RWY','27 RWY ENDING','9 aircraft RWY END'])assert.deepEqual(reader.references(text,['09','27']),[]);
 assert.deepEqual(reader.references('27 RWY END',['09']),[]);
});
test('formatted representations are escaped, indexed distinctly and never replace missing condition text',()=>{
 reader.set({airports:{KCLT:{notices:[{text:null,formatted_texts:[{type:'LOCAL_FORMAT',field:'simpleText',text:'RWY 27 <script>'}],warnings:['Condition text missing']}]}}});
 const n=reader.records('KCLT',['09','27'])[0];
 assert.equal(n.references[0].representation,'formatted_texts[0].text');
 assert.equal(n.formatted_texts[0].text.slice(n.references[0].start,n.references[0].end),'27');
 const html=render('KCLT',['27','09']);
 assert.match(html,/RWY 27 &lt;script&gt;/);assert.doesNotMatch(html,/Original text unavailable|Condition text missing|reference evidence/);assert.deepEqual(n.warnings,['Condition text missing']);
 assert.ok(!html.includes('<script>'));assert.match(html,/&lt;script&gt;/);
 assert.match(reader.cell('KCLT','27',['09','27']),/NOTAMs \(1\)/);
});

test('collection warning metadata is not displayed; reload failures remain visible',()=>{
 const warning='Fixed snapshot <unsafe>; complete airport coverage unknown; no automatic updates.';
 reader.set({retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{warning,completeness:'UNKNOWN',notices:[{text:'RWY 18L SYNTHETIC'}]}}},'Reload <failed>');
 const html=render('KMEM',['18L']);
 assert.doesNotMatch(html,/Fixed snapshot|complete airport coverage unknown|no automatic updates/);
 assert.match(html,/Reload &lt;failed&gt;/);
 assert.ok(!html.includes('<unsafe>')&&!html.includes('<failed>'));
 assert.match(html,/Showing retained snapshot after reader error/);
 reader.set(null,'Reload failed');
 const missing=render('KMEM',[]);
 assert.match(missing,/NOTAM data unavailable/i);
 assert.match(missing,/Reload failed/);
});

test('loader failure and recovery preserve collection warning and original snapshot',async()=>{
 const warning='Fixed snapshot; UNKNOWN coverage; no automatic updates.';
 const data={retrieved_utc:'2020-01-01T00:00:00Z',airports:{KMEM:{warning,completeness:'UNKNOWN',notices:[{text:'SYNTHETIC RWY 18L\r\nunchanged'}]}}};
 let failed=false;const states=[];
 const loader=snapshots.create({baseURL:'https://snapshot.invalid/',fetchFn:async()=>({ok:!failed,status:failed?503:200,json:async()=>data}),onChange:state=>{
  reader.set(state.snapshot,state.error);states.push({state,html:render('KMEM',['18L'])});
 }});
 await loader.refresh();failed=true;await loader.refresh();failed=false;await loader.refresh();
 const loaded=states.filter(s=>s.state.snapshot);
 for(const {state,html} of loaded){
  assert.equal(state.snapshot,data);
  assert.ok(!html.includes(warning));
  assert.equal(state.snapshot.airports.KMEM.notices[0].text,'SYNTHETIC RWY 18L\r\nunchanged');
 }
 assert.ok(loaded.some(({html})=>!html.includes(warning)&&html.includes('HTTP 503')&&html.includes('Showing retained snapshot')));
 assert.ok(!states.at(-1).html.includes('HTTP 503'));
 assert.ok(!states.at(-1).html.includes('Showing retained snapshot'));
});

test('omit alternate-only notice placeholders but preserve records and runway reference counts',()=>{
 reader.set({retrieved_utc:'2026-11-27T22:44:00Z',airports:{KMEM:{completeness:'UNKNOWN',notices:[
  {text:'RWY 18L',formatted_texts:[{type:'ICAO',text:'RWY 18L HIDDEN'}]},
  {text:'RWY 18L',formatted_texts:[{type:'LOCAL_FORMAT',text:'RWY 18L LOCAL'}]},
  {text:'RWY 18L',formatted_texts:[]}
 ]}}});
 const html=reader.summary('KMEM');
 assert.match(html,/RETRIEVED 2244Z/);
 assert.match(html,/RWY 18L LOCAL/);
 assert.doesNotMatch(html,/HIDDEN|All airport snapshot notices/);
 assert.equal((html.match(/LOCAL_FORMAT text unavailable\./g)||[]).length,1);
 assert.match(html,/Counts include these notices/);
 assert.equal(reader.records('KMEM',['18L']).length,3);
 assert.match(reader.cell('KMEM','18L',['18L']),/NOTAMs \(3\)/);
 assert.doesNotMatch(reader.cell('KMEM','18L',['18L']),/Literal matches/);
});
