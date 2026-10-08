/* Run with the local app and Playwright installed: node tests/web_import_csv_selection_smoke.cjs */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8784');
    await page.waitForSelector('#compare-workflows input');
    await page.locator('.nav-item[data-page="database"]').click();
    await page.evaluate(() => {
      state.importCsvTables = Array.from({ length: 100 }, (_, index) => ({
        table_name: `table_${index + 1}`, row_count: 1, has_header: true,
      }));
      renderImportCsvTables();
    });

    await page.locator('[data-import-table="table_1"]').click();
    await page.keyboard.press('Control+A');
    assert.equal(await page.locator('.import-table-chip.selected').count(), 100);
    await page.locator('#db-export-tables').click();
    assert.equal(await page.locator('.import-table-chip.selected').count(), 0);
    assert.ok(await page.locator('#db-import-selected').isDisabled());

    await page.locator('[data-import-table="table_1"]').click();
    await page.locator('#db-import-selected').click();
    assert.equal(await page.locator('.import-table-chip.selected').count(), 1);
    await page.locator('#db-export-tables').focus();
    assert.equal(await page.locator('.import-table-chip.selected').count(), 0);
    console.log('PASS: clicking or focusing outside clears 100 CSV table selections; Import Single keeps them.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
