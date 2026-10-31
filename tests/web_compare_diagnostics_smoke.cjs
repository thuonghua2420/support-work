/* UI diagnostics fixtures only; no compare, CSV mutation or DB writes. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const detail = 'Giá trị vượt giới hạn ký tự của một ô Excel.\nWorkbook: D:\\cases\\Case01\\Compare.xlsx\nCSV trái: D:\\cases\\Case01\\before\\orders.csv\nCSV phải: D:\\cases\\Case01\\after\\orders.csv\nSheet: orders\nFile CSV: D:\\cases\\Case01\\after\\orders.csv\nRecord CSV: 27\nDòng vật lý CSV: 31–33\nCột CSV: 4\nTên column: notes<script>\nÔ Excel: BD6\nSố ký tự thực tế: 41000\nGiới hạn ký tự Excel: 32767\nCách kiểm tra: Kiểm tra giá trị và quote của ô CSV.';
  try {
    await page.route('**/api/bootstrap', async route => {
      const data = await (await route.fetch()).json();
      await route.fulfill({ json: { ...data, job: null, compare_view: { cases: [] }, fixmes: [], database_connections: {}, database_connection_history: [], database_tables: {} } });
    });
    await page.route('**/api/**', async route => {
      if (route.request().method() !== 'GET') throw new Error('Unexpected mutation');
      await route.fallback();
    });
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8799');
    await page.waitForSelector('#compare-workflows input');
    const job = { id: 'partial-compare-fixture', action: 'compare', state: 'succeeded', result: {
      processed_count: 10, workbook_count: 9, error_count: 1, errors: [detail], warnings: [], fixmes: [], compare_view: { cases: [] },
    } };
    await page.evaluate(value => updateJobState(value), job);
    const panel = page.locator('#compare-diagnostics');
    assert.equal(await panel.isVisible(), true);
    assert.match(await panel.locator('strong').innerText(), /1 lỗi/);
    assert.equal(await panel.locator('pre').innerText(), detail);
    assert.equal(await panel.locator('script').count(), 0);
    assert.equal(await page.locator('#job-status-text').innerText(), 'Hoàn tất có lỗi');
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await panel.locator('button').click();
    await page.waitForFunction(expected => navigator.clipboard.readText().then(value => value === expected), detail);
    await fs.mkdir('.tmp/compare-diagnostics-screenshots', { recursive: true });
    await page.locator('#activity-toggle').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.ok(await panel.evaluate(element => element.scrollWidth <= element.clientWidth + 1));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await panel.screenshot({ path: `.tmp/compare-diagnostics-screenshots/width-${width}.png` });
    }
    await page.evaluate(value => updateJobState({ id: 'folder-failure-fixture', action: 'folder_compare', state: 'failed', error: value }), detail);
    assert.equal(await page.locator('#folder-compare-diagnostics pre').innerText(), detail);
    await page.evaluate(() => renderCompareDiagnostics('compare', [], ['Header hai file khác nhau.\nCSV trái: before.csv\nCSV phải: after.csv']));
    assert.equal(await panel.evaluate(element => element.classList.contains('warnings-only')), true);
    assert.match(await panel.locator('strong').innerText(), /0 lỗi · 1 cảnh báo/);
    await page.evaluate(() => renderCompareDiagnostics('compare'));
    assert.equal(await panel.isVisible(), false);
    assert.deepEqual(errors, []);
    console.log('PASS: fatal/partial errors, warnings, escaped details, clipboard, reset, desktop/mobile; no data writes.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
