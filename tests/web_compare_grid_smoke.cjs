/* Run with Playwright installed: node tests/web_compare_grid_smoke.cjs */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
    await page.setContent('<div class="compare-grid-wrap"><table id="compare-preview-table" class="compare-grid"></table></div>');
    await page.addStyleTag({ path: path.resolve('autocompare_tool/web/app.css') });
    await page.addScriptTag({ path: path.resolve('autocompare_tool/web/app.js') });

    const result = await page.evaluate(() => {
      const original = `${'A'.repeat(5000)}\r\n${'B'.repeat(5000)}`;
      const rows = [1, 2].map((number) => ({
        number,
        cells: [1, 2, 3].map((column) => ({
          row: number,
          column,
          value: number === 1 && column === 1 ? original : `cell ${number}/${column}`,
          style: { wrap: true },
        })),
      }));
      rows[1].cells[2].value = 'Note 1\nNote 2';
      rows[1].cells[2].fixme_indices = [0, 1];
      state.fixmeSelections = { 0: 'Note 1', 1: 'Note 2' };
      const sheet = {
        key: 'fixture', column_widths: [180, 180, 180], column_letters: ['A', 'B', 'C'], rows,
      };
      state.compareView.sheet = sheet;
      const table = document.querySelector('#compare-preview-table');
      table.innerHTML = buildCompareSheetHtml(sheet);
      setCompareGridWidth(table);
      bindCompareCellCopyControls(table);

      const value = table.querySelector('.compare-cell-value');
      value.focus();
      const clipboardData = new DataTransfer();
      value.dispatchEvent(new ClipboardEvent('copy', { clipboardData, bubbles: true, cancelable: true }));
      return {
        tableWidth: table.getBoundingClientRect().width,
        valueWidths: [...table.querySelectorAll('tbody tr:first-child td.compare-cell')]
          .map((cell) => cell.getBoundingClientRect().width),
        rowHeights: [...table.querySelectorAll('tbody tr')].map((row) => row.getBoundingClientRect().height),
        copiedValue: clipboardData.getData('text/plain'),
        original,
      };
    });

    assert.ok(Math.abs(result.tableWidth - 628) < 1, `Grid width: ${result.tableWidth}`);
    assert.ok(result.valueWidths.every((width) => Math.abs(width - 180) < 1), `Column widths: ${result.valueWidths}`);
    assert.ok(result.rowHeights.every((height) => Math.abs(height - 27) < 1), `Row heights: ${result.rowHeights}`);
    assert.equal(result.copiedValue, result.original);
    console.log('PASS: long multiline values keep 180px columns and 27px rows; copy retains the complete CRLF value.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
