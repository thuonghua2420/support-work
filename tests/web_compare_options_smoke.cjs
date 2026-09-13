const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const actions = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.route('**/api/bootstrap', async route => {
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({ json: { ...data, job: null, database_connections: {},
        database_connection_history: [], database_tables: {} } });
    });
    await page.route('**/api/actions', async route => {
      actions.push(route.request().postDataJSON());
      await route.fulfill({ status: 400, json: { error: 'UI test intercepted; no files changed.' } });
    });
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8784');
    await page.waitForSelector('#compare-workflows input');
    const copy = page.locator('#compare-copy-input');
    const sort = page.locator('#compare-sort-by-key');
    assert.equal(await copy.isChecked(), false);
    assert.equal(await sort.isChecked(), false);
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/actions')),
      page.locator('#compare-form button[type="submit"]').click(),
    ]);
    assert.equal(actions[0].copy_input, false);
    assert.equal(actions[0].sort_by_key, false);
    await copy.check();
    await sort.check();
    await page.waitForFunction(() => {
      const cache = JSON.parse(localStorage.getItem('autocompare:last-inputs:v1'));
      return cache?.fields['compare-copy-input'] === true && cache?.fields['compare-sort-by-key'] === true;
    });
    await page.reload();
    await page.waitForSelector('#compare-workflows input');
    assert.equal(await copy.isChecked(), true);
    assert.equal(await sort.isChecked(), true);
    await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/actions')),
      page.locator('#compare-form button[type="submit"]').click(),
    ]);
    assert.equal(actions[1].copy_input, true);
    assert.equal(actions[1].sort_by_key, true);
    const output = path.resolve('.tmp/ui-screenshots');
    await fs.mkdir(output, { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      if (width < 700) {
        await page.keyboard.press('Escape');
        await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().right <= 0);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      for (const selector of ['#compare-copy-input', '#compare-sort-by-key']) {
        assert.ok(await page.locator(selector).isVisible());
        assert.ok(await page.locator(selector).locator('..').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
      }
      await page.screenshot({ path: path.join(output, `compare-options-${width}.png`), fullPage: true });
    }
    assert.deepEqual(errors, []);
    console.log('PASS: checkbox defaults, persistence, API payloads, desktop/mobile layout; no CSV or DB writes.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
