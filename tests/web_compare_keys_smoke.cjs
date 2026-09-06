const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const actions = [];
  let job;
  try {
    await page.route('**/api/bootstrap', async route => {
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({ json: { ...data, job: null, update_compare_keys: {},
        database_connections: { target: { database: 'UT_Test', schema: 'dbo' } },
        database_connection_history: [], database_tables: {} } });
    });
    await page.route('**/api/actions', async route => {
      const payload = route.request().postDataJSON();
      actions.push(payload);
      assert.ok(['compare_keys_extract', 'compare_keys_remove'].includes(payload.action));
      const extracting = payload.action === 'compare_keys_extract';
      job = { id: String(actions.length), action: payload.action, label: 'Compare keys',
        state: 'succeeded', logs: [], next_cursor: 0, result: extracting
          ? { update_compare_keys: { customers: ['CustomerId'], orders: ['OrderNo', 'LineNo'] }, saved_count: 2, existing_count: 0, skipped: [] }
          : { update_compare_keys: {}, removed_count: 2 } };
      await route.fulfill({ json: { job: { ...job, state: 'queued' } } });
    });
    await page.route('**/api/jobs/current*', route => route.fulfill({ json: { job } }));
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8774');
    await page.waitForSelector('#compare-workflows input');
    assert.ok(await page.locator('#remove-compare-keys').isDisabled());
    await page.locator('#compare-root').fill('D:\\test-root');
    await page.locator('#compare-key-role').selectOption('target');
    await page.locator('#extract-compare-keys').click();
    await page.waitForFunction(() => document.querySelector('#compare-key-count').textContent.includes('2 table'));
    assert.deepEqual(actions[0], { action: 'compare_keys_extract', root: 'D:\\test-root', role: 'target' });
    assert.equal(await page.locator('#compare-key-body tr').count(), 2);
    assert.match(await page.locator('#compare-key-body').textContent(), /OrderNo, LineNo/);
    assert.equal(await page.locator('#extract-compare-keys svg').count(), 1);
    const output = path.resolve('.tmp/ui-screenshots');
    await fs.mkdir(output, { recursive: true });
    await page.locator('.toast').waitFor({ state: 'detached' });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      assert.ok(await page.locator('.compare-key-table-wrap').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
      await page.screenshot({ path: path.join(output, `compare-keys-${width}.png`), fullPage: true });
    }
    await page.locator('#remove-compare-keys').click();
    await page.waitForSelector('#confirm-dialog[open]');
    assert.match(await page.locator('#confirm-message').textContent(), /2 table/);
    await page.keyboard.press('Escape');
    assert.equal(actions.length, 1);
    await page.locator('#remove-compare-keys').click();
    await page.locator('#confirm-dialog button[value="confirm"]').click();
    await page.waitForFunction(() => document.querySelector('#compare-key-count').textContent.includes('0 table'));
    assert.deepEqual(actions[1], { action: 'compare_keys_remove', confirmed: true });
    assert.ok(await page.locator('#remove-compare-keys').isDisabled());
    assert.deepEqual(errors, []);
    console.log('PASS: key extraction payload, composite-key display, desktop/mobile layout, clear cancel/confirm, no live DB or config writes.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
