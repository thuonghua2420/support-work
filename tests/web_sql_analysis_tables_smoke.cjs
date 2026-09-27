/* Run with Playwright installed and AUTOCOMPARE_URL pointing at the local app. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const base = process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8765';
  try {
    await page.goto(`${base}/#database`, { waitUntil: 'networkidle' });
    await page.locator('[data-tab-group="database"][data-tab="sql-workspace"]').click();
    await page.evaluate(() => renderSqlAnalysis({
      dialect: 'tsql',
      statement_count: 3,
      statements: [
        { index: 1, statement_type: 'select', scope_count: 1, sql: 'SELECT * FROM Customers c JOIN Orders o ON o.CustomerId = c.Id' },
        { index: 2, statement_type: 'select', scope_count: 1, sql: 'SELECT * FROM Customers customer JOIN Products p ON p.Id = customer.ProductId' },
        { index: 3, statement_type: 'select', scope_count: 1, sql: 'SELECT 1' },
      ],
      tables: [
        { statement_index: 1, qualified_name: 'Customers', name: 'Customers', alias: 'c', role: 'FROM', source_type: 'TABLE', scope_id: 'S1.Q1', scope_name: 'Main query', depth: 0 },
        { statement_index: 1, qualified_name: 'Orders', name: 'Orders', alias: 'o', role: 'INNER JOIN', source_type: 'TABLE', scope_id: 'S1.Q1', scope_name: 'Main query', depth: 0 },
        { statement_index: 2, qualified_name: 'Customers', name: 'Customers', alias: 'customer', role: 'FROM', source_type: 'TABLE', scope_id: 'S2.Q1', scope_name: 'Main query', depth: 0 },
        { statement_index: 2, qualified_name: 'Products', name: 'Products', alias: 'p', role: 'INNER JOIN', source_type: 'TABLE', scope_id: 'S2.Q1', scope_name: 'Main query', depth: 0 },
      ],
      conditions: [], ctes: [], subqueries: [], projections: [], clauses: [],
    }));
    await page.locator('#sql-analysis-tab').click();
    await page.locator('#sql-analysis').evaluate((node) => { node.open = true; });

    assert.equal(await page.locator('.sql-statement-table-group').count(), 3);
    assert.deepEqual(
      await page.locator('.sql-statement-table-group > header .sql-statement-number').allTextContents(),
      ['Câu SQL 1', 'Câu SQL 2', 'Câu SQL 3'],
    );
    assert.deepEqual(
      await page.locator('.sql-statement-table-actions .count-badge').allTextContents(),
      ['2 table / reference', '2 table / reference', '0 table / reference'],
    );
    assert.deepEqual(
      await page.locator('[data-sql-copy-statement-tables]').allTextContents(),
      ['Sao chép 2 table', 'Sao chép 2 table', 'Sao chép 0 table'],
    );
    await assert.doesNotReject(page.locator('[data-sql-statement-index="1"]').evaluate((button) => {
      const names = JSON.parse(decodeURIComponent(button.dataset.sqlCopyStatementTables));
      if (names.join(', ') !== 'Customers, Orders') throw new Error(names.join(', '));
    }));
    await assert.doesNotReject(page.locator('[data-sql-statement-index="2"]').evaluate((button) => {
      const names = JSON.parse(decodeURIComponent(button.dataset.sqlCopyStatementTables));
      if (names.join(', ') !== 'Customers, Products') throw new Error(names.join(', '));
    }));
    assert.equal(await page.locator('[data-sql-statement-index="3"]').isDisabled(), true);
    assert.equal((await page.locator('#copy-sql-tables').innerText()).trim(), 'Sao chép 3 table');
    assert.equal(await page.locator('#sql-table-body > tr').count(), 3);
    assert.equal((await page.locator('#sql-table-summary-count').textContent()).trim(), '3');

    const customerRow = page.locator('#sql-table-body > tr').filter({ hasText: 'Customers' });
    assert.equal(await customerRow.count(), 1);
    const customerText = await customerRow.innerText();
    assert.ok(customerText.includes('c'));
    assert.ok(customerText.includes('customer'));
    assert.ok(customerText.includes('SQL 1'));
    assert.ok(customerText.includes('SQL 2'));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    console.log('SQL analysis table grouping smoke test passed.');
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
