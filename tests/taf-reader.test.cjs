'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { TafReader } = require('../taf-reader.js');
const NOW = Date.parse('2026-11-20T08:00:00Z');
function report(overrides = {}) {
  return {
    icaoId: 'KMEM',
    issueTime: '2026-11-20T06:00:00Z',
    validTimeFrom: NOW / 1000 - 3600,
    validTimeTo: NOW / 1000 + 22 * 3600,
    rawTAF: 'TAF KMEM 200600Z 2006/2106 09005KT P6SM SKC',
    ...overrides,
  };
}
test('valid current TAF shows unchanged raw text without duplicate times', () => {
  const html = TafReader.render({ code: 'MEM', station: 'KMEM', report: report(), now: NOW });
  assert.doesNotMatch(html, /TAF CURRENT|<strong>TAF<\/strong>/);
  assert.match(html, /<a class="report-source"[^>]*>TAF KMEM<\/a>/);
  assert.doesNotMatch(html, /taf-meta|Issued 2026|Valid 2026/);
  assert.match(html, /2006\/2106 09005KT/);
  assert.match(html, /ids=KMEM/);
  assert.doesNotMatch(html, /forecast wind|Headwind/);
});
test('source text is escaped without rewriting its contents', () => {
  const html = TafReader.render({
    code: 'MEM',
    station: 'KMEM',
    report: report({ rawTAF: 'TAF KMEM </pre><script>alert(1)</script> & X' }),
    now: NOW,
  });
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&lt;\/pre&gt;/);
  assert.match(html, /&amp; X/);
  assert.doesNotMatch(html, /<script>/);
});
test('expired forecasts are NO LONGER VALID, while old issues are STALE', () => {
  const expired = report({
    issueTime: new Date(NOW - 3 * 3600000).toISOString(),
    validTimeTo: NOW / 1000 - 1,
  });
  const html = TafReader.render({ code: 'MEM', station: 'KMEM', report: expired, now: NOW });
  assert.match(html, /<div class="taf-status taf-expired">NO LONGER VALID<\/div>/);
  assert.match(html, /2006\/2106 09005KT/, 'retain raw TAF for provenance');
  assert.doesNotMatch(html, /TAF STALE/);
  assert.match(
    TafReader.render({
      code: 'MEM',
      station: 'KMEM',
      report: report({ issueTime: '2026-11-19T06:00:00Z' }),
      now: NOW,
    }),
    /TAF STALE/,
  );
});
test('validity end is exclusive: NO LONGER VALID starts at the exact end', () => {
  const issued = new Date(NOW - 3 * 3600000).toISOString();
  const current = report({ issueTime: issued, validTimeTo: (NOW + 1) / 1000 });
  const ended = report({ issueTime: issued, validTimeTo: NOW / 1000 });
  assert.doesNotMatch(
    TafReader.render({ code: 'MEM', station: 'KMEM', report: current, now: NOW }),
    /taf-status/,
  );
  assert.match(
    TafReader.render({ code: 'MEM', station: 'KMEM', report: ended, now: NOW }),
    /NO LONGER VALID/,
  );
});
test('missing station and malformed reports are unavailable, not current', () => {
  for (const r of [
    null,
    report({ icaoId: 'KLAX' }),
    report({ rawTAF: '' }),
    report({ issueTime: 'tomorrow' }),
    report({ validTimeTo: 0 }),
  ]) {
    assert.match(
      TafReader.render({ code: 'MEM', station: 'KMEM', report: r, now: NOW }),
      /TAF UNAVAILABLE/,
    );
  }
  assert.match(
    TafReader.render({ code: 'ATL', station: null, report: null, now: NOW }),
    /Station mapping not verified/,
  );
});
test('future issue rejected and future valid window marked clearly', () => {
  assert.equal(TafReader.valid(report({ issueTime: '2026-11-20T10:00:00Z' }), 'KMEM', NOW), false);
  assert.match(
    TafReader.render({
      code: 'MEM',
      station: 'KMEM',
      report: report({ validTimeFrom: NOW / 1000 + 3600 }),
      now: NOW,
    }),
    /TAF NOT YET VALID/,
  );
});
test('retained forecast has a refresh failure notice', () => {
  const html = TafReader.render({
    code: 'MEM',
    station: 'KMEM',
    report: report(),
    feedError: true,
    now: NOW,
  });
  assert.match(html, /retained previous TAF/);
});

test('TAF is current through exactly six hours after issue and stale afterward', () => {
  const within = report({ issueTime: new Date(NOW - 6 * 3600000 + 60000).toISOString() });
  const exact = report({ issueTime: new Date(NOW - 6 * 3600000).toISOString() });
  const overdue = report({ issueTime: new Date(NOW - 6 * 3600000 - 1).toISOString() });
  for (const r of [within, exact])
    assert.doesNotMatch(
      TafReader.render({ code: 'MEM', station: 'KMEM', report: r, now: NOW }),
      /taf-status/,
    );
  assert.match(
    TafReader.render({ code: 'MEM', station: 'KMEM', report: overdue, now: NOW }),
    /TAF STALE/,
  );
  assert.equal(TafReader.STALE_MS, 6 * 3600000);
});

test('TAF change groups start on indented lines without changing any tokens', () => {
  const raw =
    'TAF KMEM 250244Z 2503/2606 02009KT P6SM BKN040 PROB30 2511/2515 6SM -SHRA SCT025 OVC035 FM251600 36011KT 4SM -RA BR BKN009 OVC015 FM260500 35008KT P6SM OVC015';
  const formatted = [
    'TAF KMEM 250244Z 2503/2606 02009KT P6SM BKN040',
    '  PROB30 2511/2515 6SM -SHRA SCT025 OVC035',
    '  FM251600 36011KT 4SM -RA BR BKN009 OVC015',
    '  FM260500 35008KT P6SM OVC015',
  ].join('\n');
  assert.equal(TafReader.formatRaw(raw), formatted);
  assert.deepEqual(formatted.split(/\s+/), raw.split(/\s+/));
  const html = TafReader.render({
    code: 'MEM',
    station: 'KMEM',
    report: report({ rawTAF: raw }),
    now: NOW,
  });
  assert.ok(
    html
      .replace(/<a[^>]*>|<\/a>/g, '')
      .includes('<pre class="taf-raw" data-scan-flow>' + formatted + '</pre>'),
  );
  assert.ok(!html.includes('TAF KMEM 250244Z 2503/2606 02009KT P6SM BKN040 PROB30'));
});
test('BECMG, BCMG, TEMPO, and PROB groups break at token boundaries', () => {
  const raw =
    'TAF KORD 250000Z 2500/2606 18010KT P6SM SKC BECMG 2502/2504 22012KT TEMPO 2505/2508 3SM -RA PROB40 2509/2512 1SM TSRA FM251200 27015KT BCMG 2514/2516 30007KT';
  assert.equal(
    TafReader.formatRaw(raw),
    [
      'TAF KORD 250000Z 2500/2606 18010KT P6SM SKC',
      '  BECMG 2502/2504 22012KT',
      '  TEMPO 2505/2508 3SM -RA',
      '  PROB40 2509/2512 1SM TSRA',
      '  FM251200 27015KT',
      '  BCMG 2514/2516 30007KT',
    ].join('\n'),
  );
});
test('combined PROB30 TEMPO remains one forecast group', () => {
  const raw = 'TAF KMEM 250000Z 2500/2606 18005KT PROB30 TEMPO 2503/2507 2SM TSRA FM250800 27011KT';
  assert.equal(
    TafReader.formatRaw(raw),
    [
      'TAF KMEM 250000Z 2500/2606 18005KT',
      '  PROB30 TEMPO 2503/2507 2SM TSRA',
      '  FM250800 27011KT',
    ].join('\n'),
  );
});
test('formatting is idempotent, avoids partial words, and still escapes HTML', () => {
  const raw =
    'TAF KORD 250000Z 2500/2606 09008KT FM250600 18010KT NOTFM250900 XPROB30 PROB30 2507/2509 <danger>&';
  const formatted = TafReader.formatRaw(raw);
  assert.equal(TafReader.formatRaw(formatted), formatted);
  assert.match(formatted, /FM250600 18010KT NOTFM250900 XPROB30/);
  assert.equal((formatted.match(/\n/g) || []).length, 2);
  const html = TafReader.render({
    code: 'MEM',
    station: 'KMEM',
    report: report({ rawTAF: raw }),
    now: NOW,
  });
  assert.match(html, /&lt;danger&gt;&amp;/);
  assert.doesNotMatch(html, /<danger>/);
});
