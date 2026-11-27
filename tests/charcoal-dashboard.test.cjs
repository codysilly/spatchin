'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

const app = readFileSync('app.js', 'utf8');
const css = readFileSync('charcoal-dashboard.css', 'utf8');
const html = readFileSync('index.html', 'utf8');

// Exercise exactly the pure functions used by the current dashboard renderer.
const from = app.search(/^const\s+flightCategories\s*=/m);
const to = app.search(/^const\s+observedSelection\s*=/m);
const metarStart = app.search(/^function\s+parseMetar\s*\(\s*m\s*\)\s*\{/m);
const metarEnd = app.search(/^async\s+function\s+refresh\s*\(\s*\)\s*\{/m);
assert.ok(from >= 0 && to > from && metarStart > 0 && metarEnd > metarStart);
// Load the real threshold, rather than injecting the expected value into the test.
const threshold = app.match(/^const\s+METAR_STALE_MS\s*=\s*(\d+\s*\*\s*\d+\s*\*\s*\d+)\s*;/m);
assert.ok(threshold, 'METAR staleness threshold declaration');
const code = threshold[0] + '\n' + app.slice(from, to) + '\n' + app.slice(metarStart, metarEnd);
const context = vm.createContext({ Date, Number });
new vm.Script(code, { filename: 'dashboard-flight-categories.js' }).runInContext(context);
const record = (category, minutesAgo = 0) =>
  context.parseMetar({
    icaoId: 'KMEM',
    obsTime: Math.floor((Date.now() - minutesAgo * 60000) / 1000),
    wdir: 150,
    wspd: 6,
    wgst: null,
    rawOb: 'SYNTHETIC TEST DATA',
    fltCat: category,
  });

test('only the four AWC flight-category values are accepted', () => {
  for (const category of ['VFR', 'MVFR', 'IFR', 'LIFR']) {
    const metar = record(category);
    assert.equal(metar.flightCategory, category);
    const markup = context.categoryMarkup(metar);
    assert.match(markup.tag, new RegExp('>' + category + '<'));
    assert.equal(markup.strip, undefined, 'four-part legend is removed');
  }
  for (const value of [undefined, null, '', 'NO DATA', 'UNKNOWN', 'vfr', 'SYNTHETIC']) {
    const metar = record(value);
    assert.equal(metar.flightCategory, null);
    const markup = context.categoryMarkup(metar);
    assert.match(markup.tag, /NO DATA/);
    assert.equal(markup.strip, undefined);
  }
});

test('METAR becomes stale at 70 minutes, not 65', () => {
  assert.equal(vm.runInContext('METAR_STALE_MS', context), 70 * 60 * 1000);
  assert.equal(context.metarState(record('VFR', 65)), 'current');
  assert.equal(context.metarState(record('VFR', 69)), 'current');
  assert.equal(context.metarStatus(record('VFR', 69)), '');
  assert.equal(context.metarState(record('VFR', 70)), 'stale');
  assert.match(context.metarStatus(record('VFR', 70)), /STALE · 70\+ MIN/);
});

test('stale categories remain marked as observation-based, not live', () => {
  const metar = record('VFR', 120);
  assert.equal(context.metarState(metar), 'stale');
  assert.match(context.categoryMarkup(metar).tag, /stale METAR observation/);
  assert.equal(context.categoryMarkup(metar).strip, undefined);
  assert.match(context.metarStatus(metar), /STALE/);
});

test('approved palette and fonts are attached after original styles', () => {
  for (const token of [
    '--bg:#1b1d1f',
    '--panel2:#151617',
    '--line:#3a3d40',
    '--muted:#a3a6a8',
    '--text:#e6e6e1',
    '--blue:#4fd1e6',
    '--amber:#ffb000',
    '--green:#b4e33d',
    '--flight-ifr:#ff6b6b',
    '--flight-lifr:#ff4fd8',
  ]) {
    const [property, value] = token.split(':');
    assert.match(css, new RegExp(property + '\\s*:\\s*' + value + '\\s*(?:;|})'), token);
  }
  assert.match(css, /background-image\s*:\s*none\s*!\s*important\b/);
  assert.match(html, /fonts\.googleapis\.com\/css2\?family=Inconsolata/);
  assert.match(html, /family=Overpass/);
  assert.ok(html.indexOf('charcoal-dashboard.css') > html.indexOf('styles.css'));
  assert.ok(!html.includes('href="dashboard.css"'), 'retired stylesheet must not be loaded');
  assert.match(html, /class="brand-wordmark">SPATCHIN/);
  assert.match(html, /v0\.9/);
});

// SCAN, NOTAM disclosures and reload, and airport limit/persistence are exercised by
// charcoal-dashboard-browser, notam-snapshot-browser and c070-metar-dashboard.
test('SCAN controls and responsive layout retain their configuration', () => {
  assert.ok(html.includes('id="scan-toggle"'));
  assert.ok(html.includes('id="scan-terms"'));
  assert.match(
    css,
    /\.cards\s*\{\s*display\s*:\s*grid\s*;\s*grid-template-columns\s*:\s*repeat\(\s*3\s*,\s*minmax\(\s*0\s*,\s*1fr\s*\)\s*\)/,
  );
  assert.match(css, /@media\s*\(\s*max-width\s*:\s*760px\s*\)/);
});

// Keyboard, pointer and touch reordering, and absence of the flight strip, are
// verified against the rendered dashboard by charcoal-dashboard-browser.
test('compact airport and METAR markup retain their structural and font contracts', () => {
  assert.match(app, /class="airport-top-row"/);
  assert.match(app, /data-airport-drag="/);
  assert.match(app, /data-remove="/);
  assert.match(app, /class="weather-row metar-panel"/);
  assert.match(css, /\.icao\s*\{\s*font\s*:\s*700\s+20px\s*\/\s*0?\.95\s+var\(\s*--font-data/);
  assert.match(css, /font\s*:\s*400\s+15px\s*\/\s*1\.3\s+var\(\s*--font-data/);
  assert.match(html, /id="airport-order-status"/);
});

test('SPA-68 uses a single structural foundation and removes old theme rules', () => {
  const foundation = readFileSync('styles.css', 'utf8');
  assert.equal((html.match(/rel="stylesheet" href="[^"]+\.css"/g) || []).length, 2);
  assert.ok(html.indexOf('styles.css') < html.indexOf('charcoal-dashboard.css'));
  assert.ok(!html.includes('href="dashboard.css"'));
  assert.doesNotMatch(foundation, /--bg\s*:\s*(?:#0b1520|#061321)\b/i);
  assert.doesNotMatch(foundation, /radial-gradient|linear-gradient/);
  assert.doesNotMatch(css, /\.(?:flight-strip|flight-segment|airport-code-line)\s*\{/);
  for (const active of [
    'scan-toggle',
    'scan-panel',
    'notam-reader',
    'atis-runways',
    'inline-reader',
    'sr-only',
  ])
    assert.match(
      foundation,
      new RegExp('\\.' + active + '\\s*\\{'),
      'preserved structural rule ' + active,
    );
});
