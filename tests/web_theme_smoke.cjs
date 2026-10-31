/* Read-only UI regression checks; requires Playwright and a running local app. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu-sandbox'] });
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  const errors = [];
  const overflows = [];
  const mutations = [];
  let workbookFixture = false;
  const compareView = { cases: [{ id: 'demo', name: 'UT01-001', workbooks: [
    { id: 'demo-book', name: 'Compare_Before_After.xlsx', sheets: [{ name: 'customer_data' }, { name: 'transactions' }] },
  ] }] };
  const sheet = {
    column_widths: Array(8).fill(180), column_letters: ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
    rows: Array.from({ length: 40 }, (_, row) => ({ number: row + 1,
      cells: Array.from({ length: 8 }, (_, col) => ({ column: col + 1, value: row < 2 ? (row ? `Record ${col + 1}` : '') : col < 2 ? `customer_field_${row}` : `Value ${row}-${Math.floor(col / 2)}`, fill: row === 1 ? '#C6EFCE' : '', font_color: '#233832' })),
    })),
  };
  page.on('pageerror', error => errors.push(error.message));
  const output = path.resolve('.tmp/theme-screenshots');
  await fs.mkdir(output, { recursive: true });
  try {
    await page.route('**/api/**', async route => {
      if (route.request().method() !== 'GET') {
        mutations.push(route.request().url());
        return route.abort();
      }
      if (route.request().url().endsWith('/bootstrap')) {
        const response = await route.fetch();
        const data = await response.json();
        return route.fulfill({ response, json: { ...data, compare_view: workbookFixture ? compareView : { cases: [] }, fixmes: [], job: null } });
      }
      if (route.request().url().includes('/compare-view/sheet?')) return route.fulfill({ json: sheet });
      return route.continue();
    });
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8799');
    await page.waitForSelector('#compare-workflows input');
    assert.equal(await page.locator('.nav-item[data-page="copy-ut"], #page-copy-ut, #copy-ut-form').count(), 0);
    assert.ok(await page.locator('.feature-guide').count() >= 20, 'Help covers features and subfeatures');
    assert.equal(await page.locator('#db-connection-dialog .feature-guide').count(), 0, 'Connection dialog has no usage guide');
    assert.equal(await page.locator('#page-file-tools .tool-heading .tool-icon svg').count(), 6, 'All file tools use vector icons');
    for (const id of ['folder-compare-form', 'excel-compare-form', 'pdf-compare-form', 'excel-format-form']) {
      assert.equal(await page.locator(`#${id} > .feature-guide`).count(), 1, 'Guide belongs inside its feature card');
    }
    async function capture(name) {
      await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
      const overflow = await page.evaluate(() => ({
        viewport: document.documentElement.clientWidth,
        width: document.documentElement.scrollWidth,
        elements: [...document.querySelectorAll('.page.active *')].filter(el => {
          const r = el.getBoundingClientRect();
          return r.width && r.right > document.documentElement.clientWidth + 1;
        }).slice(0, 10).map(el => `${el.tagName}#${el.id}.${el.className}`),
      }));
      if (overflow.width > overflow.viewport + 1) overflows.push({ name, ...overflow });
      const guideOverflow = await page.locator('.page.active .feature-guide').evaluateAll(guides => guides.filter(guide => {
        const box = guide.getBoundingClientRect();
        const parent = guide.parentElement.getBoundingClientRect();
        return box.width && (box.left < parent.left - 1 || box.right > parent.right + 1);
      }).length);
      assert.equal(guideOverflow, 0, `${name}: guides stay within their feature`);
    }
    for (const width of [1440, 1920, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: 960 });
      for (const key of ['compare', 'excel-compare', 'pdf-compare', 'image-compare', 'file-tools', 'excel-format', 'database']) {
        if (width <= 900) await page.locator('#menu-toggle').click();
        await page.locator(`.nav-item[data-page="${key}"]`).click();
        await capture(`${width}-${key}`);
        if (['excel-compare', 'pdf-compare', 'excel-format'].includes(key) && [1920, 390].includes(width)) {
          const guide = page.locator('.page.active form > .feature-guide');
          await guide.locator('summary').click();
          await capture(`${width}-${key}-guide`);
          await guide.locator('summary').click();
        }
        if (key === 'file-tools') {
          for (const tab of await page.locator('[data-tab-group="file"]').all()) {
            await tab.click();
            const layoutErrors = await page.locator('#page-file-tools .tool-card:visible').evaluateAll(cards => cards.flatMap(card => {
              const actions = card.querySelector('.tool-actions');
              const previous = actions.previousElementSibling;
              const errors = [];
              if (actions.getBoundingClientRect().top - previous.getBoundingClientRect().bottom < 16) errors.push('Missing action spacing');
              const columns = card.querySelector('.two-column');
              if (columns && getComputedStyle(columns).gridTemplateColumns.split(' ').length === 2) {
                const inputs = [...columns.querySelectorAll('input')];
                if (Math.abs(inputs[0].getBoundingClientRect().top - inputs[1].getBoundingClientRect().top) > 1) errors.push('Inputs are misaligned');
              }
              return errors;
            }));
            assert.deepEqual(layoutErrors, [], 'File tools have separate action rows and aligned fields');
            await capture(`${width}-file-${await tab.getAttribute('data-tab')}`);
          }
        }
      }
      for (const tab of await page.locator('.database-tabs .tab').all()) {
        await tab.click();
        const key = await tab.getAttribute('data-tab');
        if (key === 'sync') {
          assert.equal(await page.locator('.sync-workspace-grid > section').count(), 2);
          const advanced = page.locator('.sync-advanced');
          await advanced.locator('summary').click();
          assert.equal(await page.locator('#sync-step-timeout').inputValue(), '120');
          assert.equal(await page.locator('#sync-step-timeout').getAttribute('min'), '10');
          assert.equal(await page.locator('#sync-step-timeout').getAttribute('max'), '3600');
          assert.equal(await page.locator('#sync-batch-size').getAttribute('max'), '500');
          await capture(`${width}-sync-advanced`);
          await advanced.locator('summary').click();
          for (const mode of ['append', 'truncate_table', 'condition', 'incremental']) {
            await page.locator(`input[name="sync-mode"][value="${mode}"]`).check();
            assert.equal(await page.locator('#sync-condition-panel').isVisible(), mode === 'condition');
            assert.equal(await page.locator('#sync-delete-target-only').isDisabled(), mode !== 'incremental');
            assert.equal(await page.locator('#sync-record-limit').isDisabled(), ['incremental', 'condition'].includes(mode));
            await capture(`${width}-sync-${mode}`);
          }
          const help = page.locator('[data-tab-panel="database:sync"] > .feature-guide');
          await help.locator('summary').click();
          assert.ok(await help.locator('.guide-topics').isVisible());
          await capture(`${width}-sync-guide`);
          await help.locator('summary').click();
        }
        if (key === 'sql-workspace') {
          await page.locator('#sql-input').fill(Array.from({ length: 40 }, (_, i) => `SELECT c.CustomerId, 'Record ${i}' AS label FROM Customers c WHERE c.Id = ${i};`).join('\n'));
          await page.locator('#sql-input').evaluate(el => { el.scrollTop = 220; el.dispatchEvent(new Event('scroll')); });
          const metrics = await page.evaluate(() => {
            const input = document.querySelector('#sql-input');
            const layer = document.querySelector('#sql-highlight-layer');
            return [input, layer].map(el => {
              const css = getComputedStyle(el);
              return [css.fontFamily, css.fontSize, css.lineHeight, css.padding];
            });
          });
          assert.deepEqual(metrics[0], metrics[1], 'SQL editor and highlighting must align');
          await page.locator('#sql-results-tab').click();
          assert.ok(await page.locator('#sql-results-panel').isVisible());
          await capture(`${width}-database-results`);
          await page.locator('#sql-analysis-tab').click();
          await capture(`${width}-database-analysis`);
          await page.locator('#sql-input-tab').click();
        }
        await capture(`${width}-database-${key}`);
      }
      await page.locator('#db-open-connections').click();
      assert.ok(await page.locator('dialog[open]').isVisible());
      if (width >= 1440) {
        assert.equal(await page.locator('#db-connection-dialog').evaluate(dialog =>
          [dialog, ...dialog.querySelectorAll('*')].some(el => ['auto', 'scroll'].includes(getComputedStyle(el).overflowY) && el.scrollHeight > el.clientHeight + 1)
        ), false, 'Desktop connection dialog fits without an inner scrollbar');
      }
      await capture(`${width}-connections`);
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    // Exercise the real render/selection handlers with browser-only fixture data.
    await page.evaluate(() => {
      state.sourceTables = Array.from({ length: 80 }, (_, i) => `table_${i}`);
      state.importCsvTables = state.sourceTables.map(table_name => ({ table_name, row_count: 100, has_header: true }));
      renderTables(); renderImportCsvTables();
    });
    await page.locator('.database-tabs [data-tab="sync"]').click();
    await page.locator('[data-add-table="table_0"]').click();
    assert.equal(await page.locator('[data-remove-table="table_0"]').count(), 1);
    await page.locator('#sync-table-filter').fill('table_1, table_2');
    await page.locator('#sync-table-filter').press('Enter');
    assert.equal(await page.locator('#selected-tables .table-tag').count(), 3);
    await page.locator('#sync-all-tables').check();
    assert.equal(await page.locator('#selected-table-count').innerText(), '80 table');
    await page.locator('#sync-all-tables').uncheck();
    await page.locator('#clear-selected-tables').click();
    await capture('1440-sync-populated');
    await page.locator('.database-tabs [data-tab="csv"]').click();
    await page.locator('[data-import-table="table_0"]').click();
    await page.keyboard.press('Control+a');
    assert.equal(await page.locator('.import-table-chip.selected').count(), 80);
    await capture('1440-csv-populated');
    assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 2));
    for (const height of [768, 900, 1080]) {
      await page.setViewportSize({ width: 1366, height });
      for (const key of ['csv', 'sql-workspace']) {
        await page.locator(`.database-tabs [data-tab="${key}"]`).click();
        await page.waitForTimeout(120);
        await capture(`1366-${height}-${key}`);
        assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 2), `Database ${key} should fit desktop height ${height}`);
      }
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator('#activity-toggle').click();
    assert.ok(await page.locator('#activity-panel').isVisible());
    await capture('1440-log');
    await page.locator('#close-activity').click();
    await page.locator('#menu-toggle').click();
    await capture('1440-collapsed-nav');
    await page.locator('#menu-toggle').click();
    await page.locator('.nav-item[data-page="compare"]').click();
    const choice = page.locator('#compare-workflows input').first();
    const checked = await choice.isChecked();
    await choice.setChecked(!checked);
    assert.equal(await choice.isChecked(), !checked);
    await choice.setChecked(checked);
    await page.locator('.nav-item[data-page="excel-format"]').click();
    await page.locator('.excel-advanced summary').click();
    await capture('1440-format-expanded');
    workbookFixture = true;
    await page.reload();
    await page.locator('.nav-item[data-page="compare"]').click();
    await page.locator('#tab-compare-preview-card').click();
    await page.locator('#compare-preview-card.panel-expanded').waitFor();
    await page.locator('#compare-preview-table:not(.hidden)').waitFor();
    assert.ok(!(await page.locator('#activity-toggle').isVisible()), 'LOG must not cover full workspace');
    assert.ok(await page.locator('#compare-preview-card').evaluate(el => el.getBoundingClientRect().right <= document.documentElement.clientWidth + 1), 'Fullscreen controls must fit inside the viewport gutter');
    await page.locator('#compare-filter-differences').check();
    assert.equal(await page.locator('#compare-preview-table tbody tr').count(), 2);
    await page.locator('#compare-filter-differences').uncheck();
    assert.equal(await page.locator('#compare-preview-table tbody tr').count(), 40);
    await capture('1440-workbook-fullscreen');
    await page.keyboard.press('Escape');
    assert.ok(await page.locator('#activity-toggle').isVisible());
    await capture('1440-workbook-normal');
    assert.deepEqual(overflows, [], 'Pages must not overflow horizontally');
    assert.deepEqual(errors, [], 'No browser runtime errors');
    assert.deepEqual(mutations, [], 'UI checks must not execute workflow APIs');
    console.log('Theme smoke passed: 8 pages, 5 widths, 3 desktop heights, sync modes/guides, SQL alignment, log, sidebar and workbook fullscreen/filter.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
