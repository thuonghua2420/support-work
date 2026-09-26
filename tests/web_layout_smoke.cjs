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
    assert.equal(await page.locator('.nav-item svg').count(), 9);
    for (const width of [1440, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const key of ['compare', 'folder-compare', 'excel-compare', 'pdf-compare', 'image-compare', 'file-tools', 'copy-ut', 'excel-format', 'database']) {
        if (width <= 900) await page.locator('#menu-toggle').click();
        await page.locator(`.nav-item[data-page="${key}"]`).click();
        assert.ok(!(await page.locator(`#page-${key} > .page-intro h2`).isVisible()), `${key} duplicate page heading is visible`);
        await page.screenshot({ path: path.join(output, `${width}-${key}.png`), fullPage: true });
        const size = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
          overflow: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width).slice(0, 8).map(el => el.outerHTML.slice(0, 250)) }));
        if (size.scroll > size.width + 1) console.log(size);
        assert.ok(size.scroll <= size.width + 1, `${key} overflow at ${width}: ${size.scroll}`);
      }
      for (const tab of await page.locator('.database-tabs .tab').all()) {
        await tab.click();
        const key = await tab.getAttribute('data-tab');
        if (key === 'csv') {
          assert.ok(await page.locator('#db-import-tables').evaluate(el => Math.round(el.getBoundingClientRect().height) === 380));
          assert.ok(await page.locator('#db-export-tables').evaluate(el => Math.round(el.getBoundingClientRect().height) === 380));
          assert.equal(await page.locator('#db-copy-all-tables').count(), 1);
          for (const mode of ['delete_matching_keys', 'truncate_table', 'append']) {
            await page.locator(`input[name="db-import-mode"][value="${mode}"]`).check();
            assert.ok(await page.locator(`input[name="db-import-mode"][value="${mode}"]`).isChecked());
            assert.equal(await page.locator('#db-import svg').count(), 1);
          }
          const optionHeights = await page.locator('#db-csv-form .import-mode-card').evaluateAll(els => els.map(el => el.getBoundingClientRect().height));
          assert.ok(optionHeights.every(height => height <= 36), `Import options too tall at ${width}`);
        }
        if (key === 'sql-workspace') {
          assert.equal(await page.locator('#db-connection-hub').evaluate(el => el.parentElement?.id), 'database-tabbar');
          const tabGap = await page.evaluate(() => {
            const outer = document.querySelector('#page-database > .database-tabs').getBoundingClientRect();
            const inner = document.querySelector('#sql-workspace-tabs').getBoundingClientRect();
            return Math.round(inner.top - outer.bottom);
          });
          assert.ok(tabGap <= 8, `SQL nested tabs gap is ${tabGap}px at ${width}`);
          const tools = page.locator('.sql-toolbar-actions button');
          assert.equal(await tools.count(), 5);
          assert.equal(await page.locator('#sql-write-mode').count(), 0);
          assert.equal((await page.locator('#copy-current-sql').innerText()).trim(), 'Copy SQL');
          assert.ok(await page.locator('#sql-page-toolbar').isVisible());
          assert.equal(await page.locator('#sql-page-toolbar').evaluate(el => el.parentElement?.classList.contains('sql-editor-toolbar')), true);
          assert.equal(await page.locator('#sql-page-toolbar').evaluate(el => el.previousElementSibling?.classList.contains('sql-editor-header-controls')), true);
          assert.deepEqual(
            await page.locator('#sql-workspace-tabs .tab').allTextContents(),
            ['Input SQL', 'Results SQL', 'Analysis SQL'],
          );
          assert.equal(await page.locator('#sql-highlight-layer').count(), 1);
          assert.equal(await page.locator('#sql-source-list').count(), 0);
          assert.ok(await page.locator('#sql-input-panel').isVisible());
          await page.locator('#sql-results-tab').click();
          assert.ok(await page.locator('#sql-results-panel').isVisible());
          assert.ok(!(await page.locator('#sql-input-panel').isVisible()));
          await page.locator('#sql-analysis-tab').click();
          await page.locator('#sql-input-tab').click();
          const rows = await tools.evaluateAll(els => new Set(els.map(el => Math.round(el.getBoundingClientRect().top))).size);
          assert.ok(rows <= (width < 600 ? 3 : 2), `SQL tools spread across ${rows} rows at ${width}`);
          await page.locator('.sql-excel-details summary').click();
          assert.ok(await page.locator('#sql-load-excel').isVisible());
          await page.locator('.sql-excel-details summary').click();
        }
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
    assert.equal(await page.locator('#tab-fixme-expand-card').count(), 0);
    await page.locator('#menu-toggle').click();
    assert.ok(await page.locator('body.nav-collapsed').count());
    await page.locator('#menu-toggle').click();
    const fixtureRoot = path.resolve('.tmp/ui-fixtures');
    await fs.mkdir(path.join(fixtureRoot, 'before'), { recursive: true });
    await fs.mkdir(path.join(fixtureRoot, 'after'), { recursive: true });
    const fixtureRows = Array.from({ length: 30 }, (_, index) => `${index + 1},Order ${index + 1}`);
    await fs.writeFile(path.join(fixtureRoot, 'before', 'orders.csv'), `id,name,status\n${fixtureRows.map(row => `${row},old`).join('\n')}\n`);
    await fs.writeFile(path.join(fixtureRoot, 'after', 'orders.csv'), `id,name,status\n${fixtureRows.map(row => `${row},new`).join('\n')}\n`);
    await page.locator('.nav-item[data-page="folder-compare"]').click();
    await page.locator('#folder-left').fill(path.join(fixtureRoot, 'before'));
    await page.locator('#folder-right').fill(path.join(fixtureRoot, 'after'));
    await page.locator('#folder-output').fill(path.join(fixtureRoot, 'compare.xlsx'));
    await page.locator('#folder-compare-form button[type="submit"]').click();
    await page.locator('#compare-preview-table:not(.hidden)').waitFor({ timeout: 30000 });
    assert.equal(await page.locator('#tab-compare-preview-card').getAttribute('aria-selected'), 'true');
    await page.locator('#compare-preview-card.panel-expanded').waitFor({ timeout: 5000 });
    await page.keyboard.press('Escape');
    assert.ok(await page.locator('#compare-workbook-tabs').evaluate((workbooks, sheets) =>
      workbooks.getBoundingClientRect().top < sheets.getBoundingClientRect().top,
      await page.locator('#compare-sheet-tabs').elementHandle()));
    assert.ok(await page.locator('#compare-sheet-tabs').evaluate((sheets, grid) =>
      sheets.getBoundingClientRect().top < grid.getBoundingClientRect().top,
      await page.locator('.compare-grid-wrap').elementHandle()));
    const naturalGridHeight = await page.locator('.compare-grid-wrap').evaluate(el => el.getBoundingClientRect().height);
    const tableHeight = await page.locator('#compare-preview-table').evaluate(el => el.getBoundingClientRect().height);
    assert.ok(naturalGridHeight >= tableHeight, 'Normal workbook view should expand to the full sheet height');
    await page.locator('#compare-page-toolbar .expand-panel').click();
    const fullscreen = await page.locator('#compare-preview-card').evaluate(el => {
      const rect = el.getBoundingClientRect();
      return { top: rect.top, left: rect.left, width: rect.width, height: rect.height, viewportWidth: innerWidth, viewportHeight: innerHeight };
    });
    assert.ok(fullscreen.top <= 1 && fullscreen.left <= 1);
    assert.ok(fullscreen.width >= fullscreen.viewportWidth - 2 && fullscreen.height >= fullscreen.viewportHeight - 2);
    await page.screenshot({ path: path.join(output, '1440-workbook-fullscreen.png') });
    await page.keyboard.press('Escape');
    if (await page.locator('#activity-panel:not(.collapsed)').count()) await page.locator('#activity-toggle').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.locator('#tab-compare-preview-card').click();
      await page.screenshot({ path: path.join(output, `${width}-workbook-data.png`), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      if (!await page.locator('#compare-filter-differences').isChecked()) await page.locator('#compare-filter-differences').check();
      assert.equal(await page.locator('#compare-preview-table tbody tr').count(), 3);
      assert.equal(await page.locator('[data-compare-fixme-check]').count(), 1);
      await page.screenshot({ path: path.join(output, `${width}-fixme-values.png`), fullPage: true });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    assert.deepEqual(errors, []);
    console.log('PASS: 9 pages, 4 widths, database tabs/dialog, compare tabs, input retention, keyboard, expanded results, real CSV export and value-difference filters.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
