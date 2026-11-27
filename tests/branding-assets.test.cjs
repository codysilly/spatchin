'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync, existsSync, readdirSync } = require('node:fs');
const { inflateSync } = require('node:zlib');

const svg = readFileSync('assets/branding/paperplane-cyan-magenta-fade.svg', 'utf8');
const html = readFileSync('index.html', 'utf8');
const css = readFileSync('charcoal-dashboard.css', 'utf8');
const spec = readFileSync('docs/BRANDING.md', 'utf8');

test('approved vector and wordmark remain the single canonical brand', () => {
  assert.match(svg, /id="tailToNose"/);
  assert.match(svg, /<path fill="url\(#bodyFade\)" fill-rule="evenodd"/);
  assert.match(svg, /<path fill="url\(#tailToNose\)" fill-rule="evenodd"/);
  assert.equal((svg.match(/<path /g) || []).length, 2, 'preserve both owner-supplied filled paths');
  assert.match(svg, /x1="356" y1="1039" x2="1179" y2="154"/);
  for (const color of ['#04e3ed', '#31bafc', '#8979fe', '#c837f2', '#f312d9'])
    assert.ok(svg.includes(color), color);
  assert.match(html, /class="brand-logo" src="assets\/branding\/paperplane-cyan-magenta-fade\.svg" width="18" height="18"/);
  assert.match(
    html,
    /rel="icon" type="image\/svg\+xml" href="assets\/branding\/paperplane-cyan-magenta-fade\.svg"/,
  );
  assert.match(
    html,
    /rel="apple-touch-icon" sizes="180x180" href="assets\/branding\/paperplane-180\.png"/,
  );
  assert.match(
    css,
    /\.brand\s+h1\s*,\s*\.brand-wordmark\s*\{\s*letter-spacing\s*:\s*0?\.0325em\s*;?\s*\}/,
  );
  assert.match(
    css,
    /\.brand\s+h1\s*,\s*\.brand-wordmark\s*\{\s*letter-spacing\s*:\s*0?\.0175em\s*;?\s*\}/,
  );
  assert.match(spec, /owner.*original source material/);
  assert.match(html, /v0\.9/);
});

function pngPixels(filename, size) {
  const b = readFileSync(filename);
  assert.deepEqual([...b.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10], filename);
  const chunks = { IDAT: [] };
  let pos = 8;
  while (pos < b.length) {
    const length = b.readUInt32BE(pos),
      type = b.toString('ascii', pos + 4, pos + 8);
    const data = b.subarray(pos + 8, pos + 8 + length);
    if (type === 'IDAT') chunks.IDAT.push(data);
    else chunks[type] = data;
    pos += 12 + length;
    if (type === 'IEND') break;
  }
  assert.ok(chunks.IHDR && chunks.PLTE && chunks.tRNS && chunks.IDAT.length, filename);
  assert.equal(chunks.IHDR.readUInt32BE(0), size);
  assert.equal(chunks.IHDR.readUInt32BE(4), size);
  assert.equal(chunks.IHDR[8], 8, '8-bit color index');
  assert.equal(chunks.IHDR[9], 3, 'indexed color');
  const stream = inflateSync(Buffer.concat(chunks.IDAT));
  const pixels = [],
    last = new Uint8Array(size);
  let at = 0;
  const paeth = (a, b, c) => {
    const p = a + b - c,
      da = Math.abs(p - a),
      db = Math.abs(p - b),
      dc = Math.abs(p - c);
    return da <= db && da <= dc ? a : db <= dc ? b : c;
  };
  for (let y = 0; y < size; y++) {
    const filter = stream[at++],
      row = new Uint8Array(size);
    for (let x = 0; x < size; x++) {
      const v = stream[at++],
        a = x ? row[x - 1] : 0,
        up = last[x],
        upleft = x ? last[x - 1] : 0;
      const delta =
        filter === 0
          ? 0
          : filter === 1
            ? a
            : filter === 2
              ? up
              : filter === 3
                ? Math.floor((a + up) / 2)
                : filter === 4
                  ? paeth(a, up, upleft)
                  : NaN;
      assert.ok(Number.isFinite(delta), 'supported PNG filter');
      const index = (v + delta) & 255;
      row[x] = index;
      pixels.push({
        x,
        y,
        r: chunks.PLTE[index * 3],
        g: chunks.PLTE[index * 3 + 1],
        b: chunks.PLTE[index * 3 + 2],
        a: chunks.tRNS[index] ?? 255,
      });
    }
    last.set(row);
  }
  return pixels;
}
test('all icon sizes are valid transparent PNGs from the current gradient', () => {
  for (const size of [16, 32, 180]) {
    const pixels = pngPixels('assets/branding/paperplane-' + size + '.png', size);
    assert.ok(
      pixels.some((x) => x.a === 0),
      'transparent background ' + size,
    );
    assert.ok(
      pixels.some((x) => x.a > 200),
      'visible logo ' + size,
    );
    if (size === 16) continue; // Single-pixel antialiasing affects tiny favicon colors.
    const cyan = pixels.filter((x) => x.a > 160 && x.g > 120 && x.b > 170 && x.r < 130);
    const magenta = pixels.filter((x) => x.a > 160 && x.r > 140 && x.b > 140 && x.g < 115);
    assert.ok(cyan.length > 0 && magenta.length > 0, 'both ends of gradient ' + size);
    const avg = (list, key) => list.reduce((sum, x) => sum + x[key], 0) / list.length;
    assert.ok(
      avg(cyan, 'x') + size * 0.1 < avg(magenta, 'x'),
      'cyan to magenta toward nose in x at ' + size,
    );
    assert.ok(
      avg(cyan, 'y') > avg(magenta, 'y') + size * 0.1,
      'cyan tail below magenta nose at ' + size,
    );
  }
});

test('only the new paperplane files remain in the branding directory', () => {
  const expected = [
    'paperplane-cyan-magenta-fade.svg',
    'paperplane-16.png',
    'paperplane-32.png',
    'paperplane-180.png',
  ];
  assert.deepEqual(readdirSync('assets/branding').sort(), expected.sort());
  const legacy = [
    'logo-cyan-magenta.svg',
    'spatchin-logo-source.png',
    ...[16, 32, 64, 128, 180].map((n) => 'logo-' + n + '.png'),
  ];
  for (const old of legacy) {
    assert.equal(
      existsSync('assets/branding/' + old),
      false,
      'legacy asset must be retired: ' + old,
    );
  }
  for (const page of ['index.html', 'dashboard/index.html']) {
    const markup = readFileSync(page, 'utf8');
    assert.ok(!markup.includes('assets/branding/logo-'), page);
    assert.ok(markup.includes('paperplane-cyan-magenta-fade.svg'), page);
  }
});
