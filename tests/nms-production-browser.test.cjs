const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { createInterface } = require('node:readline');
const { test } = require('node:test');
const { chromium } = require('playwright');
const { pythonCommand } = require('./python-launcher.cjs');

test('accepted and deployed synthetic NMS bytes reach the root dashboard and SCAN', async (t) => {
  const fixture = [
    'from tests.test_nms_operations import offline_delivery_fixture',
    'from nms_review_server import serve_review',
    'serve_review(offline_delivery_fixture())',
  ].join('\n');
  const server = spawn(pythonCommand(), ['-B', '-c', fixture], { stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(() => server.kill());
  const output = createInterface({ input: server.stdout });
  let stderr = '';
  server.stderr.on('data', (chunk) => { stderr += chunk; });
  const [url] = await Promise.race([
    once(output, 'line'),
    once(server, 'exit').then(([code]) => { throw Error(`Offline delivery fixture exited ${code}\n${stderr}`); }),
  ]);
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, headless: true });
  t.after(() => browser.close());
  const origin = new URL(url).origin;
  assert.equal((await fetch(`${origin}/data/notams.json`)).status, 404);
  assert.equal((await fetch(`${url}scripts/notam/nms_operations.py`)).status, 404);
  const deployed = await (await fetch(`${url}data/notams.json`)).json();
  assert.equal(Object.keys(deployed.airports).length, 130);
  assert.equal(deployed.airports.KATL.completeness, 'UNKNOWN');
  assert.equal(deployed.airports.KATL.notices.length, 0);

  for (const width of [1440, 390]) {
    await t.test(`${width}px`, async () => {
      const context = await browser.newContext({ viewport: { width, height: 900 } });
      const page = await context.newPage();
      const external = [];
      let failed = false;
      await context.route('**/*', (route) => {
        const target = new URL(route.request().url());
        if (target.origin !== origin) {
          external.push(target.origin);
          return route.abort();
        }
        if (failed && target.pathname.endsWith('/data/notams.json')) {
          return route.fulfill({ status: 503, body: '' });
        }
        return route.continue();
      });
      try {
        await page.goto(url);
        const summary = page.locator('#coverage-KMEM');
        await summary.locator('.notam-meta').filter({hasText:'RETRIEVED 1803Z'}).waitFor();
        assert.match(await summary.innerText(), /STALE/);
        assert.equal(await summary.locator('.notam-metadata').isVisible(), false);
        await summary.locator('summary').click();
        await summary.getByText('Source: NMS-API snapshot', { exact: true }).waitFor();
        assert.match(await summary.innerText(), /Retrieved: 2026-01-02 18:03 UTC/);
        assert.match(await summary.innerText(), /Coverage UNKNOWN/);
        assert.match(await summary.innerText(), /Freshness: STALE/);
        assert.match(await summary.innerText(), /LOCAL_FORMAT text unavailable/);
        const text = 'SYNTHETIC RWY 18L lighting report\r\nSECOND ORIGINAL LINE\rTHIRD';
        assert.ok((await summary.locator('.reader-raw').allTextContents()).includes(text));
        await page.locator('[data-reader-open="KMEM-18L"]').click();
        assert.ok((await page.locator('#reader-KMEM-18L .reader-raw').allTextContents()).includes(text));
        assert.ok(!(await page.locator('#reader-KMEM-36R .reader-raw').allTextContents()).includes(text));
        await page.locator('#scan-toggle').click();
        await page.locator('#scan-terms').fill('SECOND ORIGINAL LINE');
        await page.locator('.reader-raw mark').first().waitFor({ state: 'attached' });
        failed = true;
        await page.locator('[data-notam-reload="MEM"]').click();
        await summary.getByText('Showing retained snapshot after reader error.').waitFor();
        assert.equal(await summary.locator('details').getAttribute('open'), '');
        assert.equal(await page.locator('#reader-KMEM-18L').getAttribute('hidden'), null);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        assert.deepEqual(external, []);
      } finally {
        await context.close();
      }
    });
  }
});
