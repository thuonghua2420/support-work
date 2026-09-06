/* Run with Playwright installed and AUTOCOMPARE_URL pointing at the local app. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const base = process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8770';
  const output = path.resolve('.tmp/ui-screenshots');
  await fs.mkdir(output, { recursive: true });
  try {
    // Isolate initial empty-state checks from previous test runs; keep real APIs for export.
    await page.route('**/api/bootstrap', async route => {
      const response = await route.fetch();
      const data = await response.json();
      await route.fulfill({ response, json: { ...data, compare_view: { cases: [] }, fixmes: [], job: null } });
    });
    await page.goto(base);
    await page.waitForSelector('#compare-workflows input');
    assert.equal(await page.locator('.nav-item svg').count(), 6);
    for (const width of [1440, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const key of ['compare', 'folder-compare', 'file-tools', 'copy-ut', 'excel-format', 'database']) {
        if (width <= 900) await page.locator('#menu-toggle').click();
        await page.locator(`.nav-item[data-page="${key}"]`).click();
        await page.screenshot({ path: path.join(output, `${width}-${key}.png`), fullPage: true });
        const size = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
          overflow: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width).slice(0, 8).map(el => el.outerHTML.slice(0, 250)) }));
        if (size.scroll > size.width + 1) console.log(size);
        assert.ok(size.scroll <= size.width + 1, `${key} overflow at ${width}: ${size.scroll}`);
      }
      for (const tab of await page.locator('.database-tabs .tab').all()) {
        await tab.click();
        const key = await tab.getAttribute('data-tab');
        await page.screenshot({ path: path.join(output, `${width}-database-${key}.png`), fullPage: true });
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `DB ${key} overflow at ${width}`);
      }
      await page.locator('#db-open-connections').click();
      assert.ok(await page.locator('dialog[open]').isVisible());
      await page.screenshot({ path: path.join(output, `${width}-connections.png`) });
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('.nav-item[data-page="compare"]').click();
    await page.locator('#compare-root').fill('D:\\test-root');
    await page.locator('#tab-compare-preview-card').click();
    assert.ok(await page.locator('.workbench-empty').isVisible());
    await page.locator('#tab-compare-form').click();
    assert.equal(await page.locator('#compare-root').inputValue(), 'D:\\test-root');
    await page.locator('#tab-compare-form').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#tab-compare-preview-card').getAttribute('aria-selected'), 'true');
    await page.locator('#tab-fixme-expand-card').click();
    await page.locator('#fixme-expand-card .expand-panel').click();
    assert.ok(await page.locator('.panel-expanded').isVisible());
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.panel-expanded').count(), 0);
    await page.locator('#menu-toggle').click();
    assert.ok(await page.locator('body.nav-collapsed').count());
    await page.locator('#menu-toggle').click();
    const fixtureRoot = path.resolve('.tmp/ui-fixtures');
    await fs.mkdir(path.join(fixtureRoot, 'before'), { recursive: true });
    await fs.mkdir(path.join(fixtureRoot, 'after'), { recursive: true });
    await fs.writeFile(path.join(fixtureRoot, 'before', 'orders.csv'), 'id,name,status\n1,Order A,old\n2,Order B,old\n');
    await fs.writeFile(path.join(fixtureRoot, 'after', 'orders.csv'), 'id,name,status\n1,Order A,new\n2,Order B,new\n');
    await page.locator('.nav-item[data-page="folder-compare"]').click();
    await page.locator('#folder-left').fill(path.join(fixtureRoot, 'before'));
    await page.locator('#folder-right').fill(path.join(fixtureRoot, 'after'));
    await page.locator('#folder-output').fill(path.join(fixtureRoot, 'compare.xlsx'));
    await page.locator('#folder-compare-form button[type="submit"]').click();
    await page.locator('#compare-preview-table:not(.hidden)').waitFor({ timeout: 30000 });
    assert.equal(await page.locator('#tab-compare-preview-card').getAttribute('aria-selected'), 'true');
    if (await page.locator('#activity-panel:not(.collapsed)').count()) await page.locator('#activity-toggle').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('#tab-compare-preview-card').click();
      await page.screenshot({ path: path.join(output, `${width}-workbook-data.png`), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.locator('#tab-fixme-expand-card').click();
      await page.locator('[data-fixme-filter="column_name"]').fill('status');
      assert.equal(await page.locator('#fixme-body tr').count(), 2);
      await page.screenshot({ path: path.join(output, `${width}-fixme-data.png`), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    assert.deepEqual(errors, []);
    console.log('PASS: 6 pages, 4 widths, database tabs/dialog, compare tabs, input retention, keyboard, expanded results, real CSV export and FIXME filters.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
