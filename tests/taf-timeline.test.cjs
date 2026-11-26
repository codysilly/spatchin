'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../taf-timeline.js');
const Z = (t) => Date.parse('2026-11-' + t + 'Z') / 1000;
const NOW = Z('20T08:00:00') * 1000;
function period(kind, from, to, wind = {}, extra = {}) {
  return { fcstChange: kind, timeFrom: Z(from), timeTo: Z(to), ...wind, ...extra };
}
const base = period(null, '20T06:00:00', '21T06:00:00', { wdir: 270, wspd: 18, wgst: 26 });
const fm = period('FM', '20T12:00:00', '21T06:00:00', { wdir: 90, wspd: 10 });
function report(fcsts = [base, fm], options = {}) {
  return {
    issueTime: '2026-11-20T06:00:00Z',
    validTimeFrom: Z('20T06:00:00'),
    validTimeTo: Z('21T06:00:00'),
    fcsts,
    ...options,
  };
}
const at = (r, time) => T.select(r, Z(time) * 1000, NOW);
test('uses BASE until a later FM takes precedence at exact start', () => {
  assert.equal(at(report(), '20T11:59:00').wind.direction, 270);
  const chosen = at(report(), '20T12:00:00');
  assert.equal(chosen.wind.direction, 90);
  assert.equal(chosen.source, 'FM');
  assert.equal(chosen.wind.speed, 10);
});
test('wind gusts retained independently from sustained wind', () => {
  assert.deepEqual(T.windOf(base), { direction: 270, speed: 18, gust: 26, variable: false });
  assert.equal(T.windOf({ wdir: 360, wspd: 5 }).direction, 0);
  assert.equal(T.windOf({ wdir: 0, wspd: 0 }).speed, 0);
});
test('VRB direction is never treated as a runway bearing', () => {
  const v = T.windOf({ wdir: 'VRB', wspd: 12, wgst: 20 });
  assert.equal(v.direction, null);
  assert.equal(v.variable, true);
  assert.equal(T.windOf({ wspd: 12 }), null);
});
test('TEMPO creates an alternate wind without replacing prevailing', () => {
  const tempo = period('TEMPO', '20T14:00:00', '20T16:00:00', { wdir: 160, wspd: 22, wgst: 34 });
  const state = at(report([base, fm, tempo]), '20T15:00:00');
  assert.equal(state.wind.direction, 90);
  assert.equal(state.alternatives[0].label, 'TEMPO');
  assert.equal(state.alternatives[0].wind.gust, 34);
  assert.match(state.notes.join(' '), /may occur/);
});
test('PROB windows retain their probability and alternate wind', () => {
  const prob = period(
    'PROB',
    '20T14:00:00',
    '20T17:00:00',
    { wdir: 200, wspd: 15 },
    { probability: 30 },
  );
  const x = at(report([base, fm, prob]), '20T14:30:00');
  assert.equal(x.wind.direction, 90);
  assert.equal(x.alternatives[0].label, 'PROB 30%');
  assert.equal(x.alternatives[0].wind.direction, 200);
});
test('TEMPO without a wind forecast reports other weather, no invented wind', () => {
  const tempo = period('TEMPO', '20T14:00:00', '20T16:00:00', {});
  const state = at(report([base, fm, tempo]), '20T15:00:00');
  assert.equal(state.alternatives[0].wind, null);
  assert.match(state.notes.join(' '), /no alternate wind specified/);
});
test('BECMG wind transition is unknown during its window and changes afterward', () => {
  const becoming = period('BECMG', '20T09:00:00', '20T11:00:00', { wdir: 180, wspd: 12 });
  const sample = report([base, becoming, fm]);
  assert.equal(at(sample, '20T08:30:00').wind.direction, 270);
  assert.equal(at(sample, '20T10:00:00').status, 'transition');
  assert.equal(at(sample, '20T10:00:00').wind, null);
  assert.equal(at(sample, '20T11:00:00').wind.direction, 180);
  assert.equal(at(sample, '20T12:00:00').wind.direction, 90);
});
test('BECMG timeBec is the transition end when AWC supplies it', () => {
  const change = period(
    'BECMG',
    '20T09:00:00',
    '21T06:00:00',
    { wdir: 180, wspd: 12 },
    { timeBec: Z('20T11:00:00') },
  );
  assert.equal(at(report([base, change]), '20T10:00:00').status, 'transition');
  assert.equal(at(report([base, change]), '20T11:15:00').wind.direction, 180);
});
test('BECMG without wind does not make up a new wind', () => {
  const change = period('BECMG', '20T09:00:00', '20T11:00:00', {});
  assert.equal(at(report([base, change]), '20T10:00:00').wind.direction, 270);
});
test('unsupported groups never override FM conditions', () => {
  const custom = period('INTER', '20T13:00:00', '20T15:00:00', { wdir: 150, wspd: 20 });
  const state = at(report([base, fm, custom]), '20T14:00:00');
  assert.equal(state.wind.direction, 90);
  assert.match(state.notes.join(' '), /Unrecognized/);
});
test('unusable/stale/outside decoded forecasts never produce computed wind', () => {
  assert.equal(at(report([]), '20T09:00:00').status, 'missing');
  assert.equal(at(report(), '21T06:00:00').status, 'outside');
  assert.equal(at(report(), '20T05:59:00').wind, null);
  const old = report([base], { issueTime: '2026-11-19T06:00:00Z' });
  assert.equal(at(old, '20T10:00:00').status, 'stale');
  assert.equal(at(old, '20T10:00:00').wind, null);
});
test('short forecast validity never silently rounds into next day', () => {
  const r = report([base], { validTimeTo: Z('20T10:00:00') });
  assert.equal(T.steps(r), 7);
  assert.equal(T.stepTime(r, 99), Z('20T09:30:00') * 1000);
  assert.equal(T.stepIndex(r, Z('20T09:42:00') * 1000), 7);
});
test('UTC date-time input and times remain independent of system time zone', () => {
  assert.equal(T.localInput(Z('20T13:30:00') * 1000), '2026-11-20T13:30');
  assert.equal(T.time('2026-11-20T13:30'), Z('20T13:30:00') * 1000);
  assert.equal(T.stamp(Z('20T13:30:00') * 1000), '2026-11-20 13:30Z');
});
test('missing, malformed and unknown wind values do not produce fictitious calculations', () => {
  assert.equal(T.windOf({ wdir: 90, wspd: -1 }), null);
  assert.equal(T.windOf({ wdir: 90, wspd: 15, wgst: 12 }), null);
  assert.equal(T.windOf({ wdir: 'VAR', wspd: 12 }), null);
  assert.equal(T.windOf({ wdir: 50, wspd: null }), null);
  assert.equal(
    T.select({ validTimeFrom: 1, validTimeTo: 0, fcsts: [base] }, NOW, NOW).status,
    'outside',
  );
});

test('six-hour issuance cutoff applies to projected winds, with exact boundary current', () => {
  const atSix = report([base], { issueTime: new Date(NOW - 6 * 3600000).toISOString() });
  const overdue = report([base], { issueTime: new Date(NOW - 6 * 3600000 - 1).toISOString() });
  assert.equal(at(atSix, '20T10:00:00').status, 'available');
  assert.equal(at(atSix, '20T10:00:00').wind.direction, 270);
  assert.equal(at(overdue, '20T10:00:00').status, 'stale');
  assert.equal(at(overdue, '20T10:00:00').wind, null);
  assert.equal(T.STALE_MS, 6 * 3600000);
});

test('expired TAF is distinct from issue-age staleness and gives no wind', () => {
  const expired = report([base], {
    issueTime: '2026-11-20T08:30:00Z',
    validTimeTo: Z('20T10:00:00'),
  });
  const atEnd = T.select(expired, Z('20T09:00:00') * 1000, Z('20T10:00:00') * 1000);
  assert.equal(atEnd.status, 'expired');
  assert.equal(atEnd.wind, null);
  assert.match(atEnd.notes.join(' '), /no longer valid/);
});
