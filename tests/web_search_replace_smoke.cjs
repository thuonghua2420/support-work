/* Writes only generated .tmp fixtures. Run with Playwright and the local server. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  await fs.mkdir('.tmp/search-replace-screenshots', { recursive: true });
  const root = await fs.mkdtemp(path.resolve('.tmp/search-replace-test-'));
  const original = Buffer.from('const foo = "foo";\r\n// FOO\n');
  await fs.writeFile(path.join(root, 'sample.js'), original);
  const sjis = Buffer.concat([Buffer.from('93fa967b8cea', 'hex'), Buffer.from(' foo\r\n')]);
  await fs.writeFile(path.join(root, 'japanese.txt'), sjis);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  async function waitSearch(count = 4) {
    await page.waitForFunction(expected => document.querySelector('#sr-cancel').disabled && document.querySelectorAll('.sr-match-row').length === expected && /[0-9]s$/.test(document.querySelector('#sr-summary').textContent), count);
  }
  async function capture(name) {
    await page.screenshot({ path: `.tmp/search-replace-screenshots/${name}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: horizontal page overflow`);
  }
  try {
    await page.goto((process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8799') + '/#search-replace');
    await page.waitForSelector('#page-search-replace.active');
    await page.locator('#sr-root').fill(root);
    await page.locator('#sr-load').click();
    await page.locator('#sr-query').fill('foo');
    await page.locator('#sr-query').press('Enter');
    await waitSearch();
    assert.equal(await page.locator('.sr-match-row').count(), 4);
    await page.locator('.sr-match').last().click();
    await page.waitForSelector('#sr-editor .CodeMirror');
    await capture('search');
    await page.locator('#sr-toggle-replace').click();
    await page.locator('#sr-replacement').fill('bar');
    await page.locator('#sr-preserve').click();
    await page.locator('#sr-replace-all').click();
    await page.waitForSelector('#sr-review-bar:not(.hidden)');
    await page.waitForFunction(() => document.querySelectorAll('#sr-editor .CodeMirror').length === 2);
    assert.match(await page.locator('#sr-review-label').textContent(), /4 matches.*2 file/);
    assert.deepEqual(await fs.readFile(path.join(root, 'sample.js')), original, 'Preview must not write');
    await capture('replace-preview');
    await page.locator('#sr-apply-plan').click();
    await page.locator('#confirm-accept').click();
    await page.waitForFunction(() => !document.querySelector('#sr-undo').disabled);
    await waitSearch(0);
    assert.equal(await fs.readFile(path.join(root, 'sample.js'), 'utf8'), 'const bar = "bar";\r\n// BAR\n');
    assert.deepEqual(await fs.readFile(path.join(root, 'japanese.txt')), Buffer.concat([Buffer.from('93fa967b8cea', 'hex'), Buffer.from(' bar\r\n')]));
    await page.locator('#sr-undo').click();
    await page.locator('#confirm-accept').click();
    await waitSearch();
    assert.deepEqual(await fs.readFile(path.join(root, 'sample.js')), original);
    assert.deepEqual(await fs.readFile(path.join(root, 'japanese.txt')), sjis);
    await page.locator('#sr-case').click();
    assert.ok(await page.locator('#sr-replace-all').isDisabled(), 'Changing search options invalidates replace');
    await page.locator('#sr-include').fill('*.js');
    await page.locator('#sr-search').click();
    await waitSearch(2);
    assert.equal(await page.locator('.sr-match-row').count(), 2);
    await page.locator('.sr-match-row').first().getByRole('button', { name: 'Replace kết quả này', exact: true }).click();
    await page.waitForSelector('#sr-review-bar:not(.hidden)');
    assert.match(await page.locator('#sr-review-label').textContent(), /1 matches.*1 file/);
    await page.locator('#sr-discard-plan').click();
    await page.locator('.sr-match-row').first().getByRole('button', { name: 'Bỏ kết quả này', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('.sr-match-row').length === 1);
    await page.locator('#sr-replace-all').click();
    await page.waitForSelector('#sr-review-bar:not(.hidden)');
    assert.match(await page.locator('#sr-review-label').textContent(), /1 matches.*1 file/);
    await page.setViewportSize({ width: 1100, height: 800 });
    await capture('compact');
    assert.deepEqual(errors, []);
    console.log('Search/Replace browser smoke passed: search, preview, replace, CP932, undo, scope, dismiss, layout.');
  } finally { await browser.close(); }
})();
