// Offline: execute the actual dashboard in a VM with storage/DOM stubs and no network.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {mountInVM}=require('./dashboard-module-support.cjs');
const vm = require('node:vm');
const NEW = 'spatchin-airports', OLD = 'niltsi-airports';
const defaults = ['MEM'];
test('MEM is the only fallback, maps to KMEM, and does not write preferences', () => {
  const app = load();
  assert.deepEqual(app.airports(), ['MEM']);
  assert.equal(app.run('icao("MEM")'), 'KMEM');
  assert.equal(app.run('icao(airports[0])'), 'KMEM');
  assert.deepEqual(app.writes, []);
  assert.equal(app.stored.size, 0);
});
function load(values = {}, {readFailures = [], writeFails = false, unavailable = false} = {}) {
  const stored = new Map(Object.entries(values)), writes = [], reads = [];
  const elements = new Map();
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {addEventListener(){}, innerHTML:'', textContent:''});
        return elements.get(id);
      },
      querySelectorAll: () => [],
    },
    setInterval(){},
    // Never contact a provider or start background work.
    fetch: () => new Promise(() => {}),
  });
  Object.defineProperty(context, 'localStorage', {get() {
    if (unavailable) throw Error('Storage denied');
    return {
      getItem(key) {
        reads.push(key);
        if (readFailures.includes(key)) throw Error('Read denied');
        return stored.get(key) ?? null;
      },
      setItem(key, value) {
        if (writeFails) throw Error('Quota exceeded');
        writes.push(key); stored.set(key, value);
      },
    };
  }});
  const {run}=mountInVM(context);
  return {stored, writes, reads,
    airports: () => JSON.parse(run('JSON.stringify(airports)')),
    run,
  };
}
test('new preferences take precedence and do not read or overwrite legacy or SCAN', () => {
  const values = {[NEW]:'["JFK","ORD"]', [OLD]:'["LAX"]', 'spatchin-scan-v1':'{"keywords":"METAR"}'};
  const app = load(values);
  assert.deepEqual(app.airports(), ['JFK','ORD']);
  assert.deepEqual(app.reads, [NEW]);
  assert.deepEqual(app.writes, []);
  assert.deepEqual(Object.fromEntries(app.stored), values);
});
test('missing or invalid new value migrates legacy without changing its bytes', () => {
  for (const invalid of [undefined, '{broken', 'null', '{}', '"ORD"']) {
    const legacy = '["LAX", "ORD", "LAX", "jfk", 3, "JFK", "ABCD"]';
    const app = load({[OLD]:legacy, ...(invalid === undefined ? {} : {[NEW]:invalid})});
    assert.deepEqual(app.airports(), ['LAX','ORD','JFK']);
    assert.equal(app.stored.get(NEW), '["LAX","ORD","JFK"]');
    assert.equal(app.stored.get(OLD), legacy);
    assert.deepEqual(app.writes, [NEW]);
  }
});
test('validation retains order, first occurrence, uppercase-only rules and 30-airport limit', () => {
  const codes = Array.from({length:35}, (_, i) => 'A' + String.fromCharCode(65 + Math.floor(i/26)) + String.fromCharCode(65 + i%26));
  for (const key of [NEW, OLD]) {
    const app = load({[key]:JSON.stringify(['ord', null, 'AB', 'ABCD', codes[0], ...codes, codes[0]])});
    assert.deepEqual(app.airports(), codes.slice(0,30));
  }
});
test('preserves existing nonempty-array filtering and intentional empty-array behavior', () => {
  assert.deepEqual(load({[NEW]:'[null,"ord",42]', [OLD]:'["LAX"]'}).airports(), []);
  assert.deepEqual(load({[OLD]:'[null,"ord",42]'}).airports(), []);
  assert.deepEqual(load({[NEW]:'[]', [OLD]:'[]'}).airports(), []);
});
test('missing and malformed preferences use defaults without writing them', () => {
  for (const values of [{}, {[NEW]:'{broken', [OLD]:'{broken'}, {[NEW]:'false', [OLD]:'{}'}]) {
    const app = load(values);
    assert.deepEqual(app.airports(), defaults);
    assert.deepEqual(app.writes, []);
  }
});
test('subsequent saves use the new key and retain legacy for rollback', () => {
  const app = load({[OLD]:'["LAX"]'});
  app.run('airports.push("ATL");save();');
  assert.equal(app.stored.get(NEW), '["LAX","ATL"]');
  assert.equal(app.stored.get(OLD), '["LAX"]');
  assert.deepEqual(app.writes, [NEW, NEW]);
  app.run('airports=[];save();');
  assert.equal(app.stored.get(NEW), '[]');
  assert.deepEqual(load(Object.fromEntries(app.stored)).airports(), []);
});
test('read errors fall back independently; unavailable storage retains usable session defaults', () => {
  const app = load({[OLD]:'["JFK"]'}, {readFailures:[NEW]});
  assert.deepEqual(app.airports(), ['JFK']);
  assert.equal(app.stored.get(NEW), '["JFK"]');
  for (const options of [{readFailures:[NEW, OLD]}, {unavailable:true}]) {
    const denied = load({}, options);
    assert.deepEqual(denied.airports(), defaults);
    assert.doesNotThrow(() => denied.run('airports.push("ATL");save();'));
    assert.deepEqual(denied.airports(), [...defaults, 'ATL']);
  }
});
test('migration write failure keeps loaded preferences and legacy; later saves do not crash', () => {
  const app = load({[OLD]:'["JFK","ORD"]'}, {writeFails:true});
  assert.deepEqual(app.airports(), ['JFK','ORD']);
  assert.equal(app.stored.get(OLD), '["JFK","ORD"]');
  assert.equal(app.stored.has(NEW), false);
  assert.doesNotThrow(() => app.run('airports.push("ATL");save();'));
  assert.deepEqual(app.airports(), ['JFK','ORD','ATL']);
});

test('reorder saves existing airport preference order without changing membership',()=>{
 const app=load({[NEW]:'["MEM","IND","OAK"]'});
 assert.equal(app.run('moveAirport("MEM",2)'),true);
 assert.deepEqual(app.airports(),['IND','OAK','MEM']);
 assert.equal(app.stored.get(NEW),'["IND","OAK","MEM"]');
 assert.equal(app.run('moveAirport("OAK",0)'),true);
 assert.deepEqual(app.airports(),['OAK','IND','MEM']);
 assert.equal(app.run('moveAirport("OAK",0)'),false);
 assert.equal(app.run('moveAirport("MEM",99)'),false);
 assert.equal(app.run('moveAirport("FOO",0)'),false);
 assert.deepEqual(app.airports(),['OAK','IND','MEM']);
 assert.deepEqual(load(Object.fromEntries(app.stored)).airports(),['OAK','IND','MEM']);
});

test('airport ordering helpers normalize and move without storage or DOM side effects',()=>{
 const app=load({[NEW]:'["MEM","IND","OAK"]'});
 const result=JSON.parse(app.run(`JSON.stringify((()=>{
  const input=['OAK','MEM','OAK','ind',null,'IND'];
  const normalized=AirportOrder.normalize(input);
  const changed=AirportOrder.move(normalized,'IND',0);
  const rejected=[AirportOrder.move(normalized,'IND',0),AirportOrder.move(normalized,'MEM',-1),AirportOrder.move(normalized,'MEM',1.5),AirportOrder.move(normalized,'XXX',0)];
  return {input,normalized,changed,rejected,invalid:AirportOrder.normalize({})};
 })())`));
 assert.deepEqual(result.input,['OAK','MEM','OAK','ind',null,'IND']);
 assert.deepEqual(result.normalized,['IND','OAK','MEM']);
 assert.equal(result.changed,true);
 assert.deepEqual(result.rejected,[false,false,false,false]);
 assert.equal(result.invalid,null);
 assert.deepEqual(app.airports(),['MEM','IND','OAK']);
 assert.deepEqual(app.writes,[]);
});
