import test from 'node:test';
import assert from 'node:assert/strict';
import { AirportCatalog, AirportMetadata } from '../airport-catalog.js';
import { diagramSearchMarkup } from '../app.js';

const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;');

test('all 130 C070 airports have an explicit FAA diagram search link', () => {
  assert.equal(AirportCatalog.length, 130);
  const identifiers = new Set();
  for (const airport of AirportCatalog) {
    const icao = AirportMetadata[airport].icao;
    const markup = diagramSearchMarkup(icao, escape);
    const href = markup.match(/href="([^"]+)"/)[1];
    const url = new URL(href);
    assert.equal(url.origin, 'https://www.faa.gov');
    assert.equal(url.pathname, '/air_traffic/flight_info/aeronav/digital_products/dtpp/search/');
    assert.equal(url.searchParams.get('ident'), icao);
    assert.equal(url.searchParams.has('cycle'), false);
    assert.match(markup, /Find FAA diagram/);
    assert.match(markup, /select current edition/);
    assert.match(markup, /target="_blank" rel="noopener"/);
    identifiers.add(icao);
  }
  assert.equal(identifiers.size, 130);
});

test('unknown or malformed ICAO identifiers do not produce misleading links', () => {
  for (const value of [undefined, null, '', 'MEM', 'Kmem', 'KORD?cycle=2611', '<svg>', 1234]) {
    assert.equal(diagramSearchMarkup(value, escape), '');
  }
});
