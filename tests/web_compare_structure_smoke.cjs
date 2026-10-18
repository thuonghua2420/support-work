/* Save requests are intercepted; this test never changes the real config. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  const writes = [];
  let fixture;
  let rejectSave = false;
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/bootstrap') {
        const response = await route.fetch();
        const data = await response.json();
        return route.fulfill({ json: { ...data, job: null, database_connections: {}, database_connection_history: [], database_tables: {} } });
      }
      if (url.pathname === '/api/compare-structure') {
        if (!fixture) fixture = await (await route.fetch()).json();
        return route.fulfill({ json: fixture });
      }
      if (url.pathname === '/api/compare-structure/save') {
        writes.push(route.request().postDataJSON());
        if (rejectSave) return route.fulfill({ status: 409, json: { error: 'Cấu hình đã thay đổi. Nhấn Tải lại.' } });
        fixture = { ...writes.at(-1), revision: `test-revision-${writes.length}` };
        return route.fulfill({ json: fixture });
      }
      if (route.request().method() !== 'GET') throw new Error(`Unexpected mutation: ${url.pathname}`);
      return route.continue();
    });
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8799');
    await page.waitForSelector('#compare-workflows input');
    await page.locator('#open-compare-structure').click();
    const dialog = page.locator('#compare-structure-dialog');
    const save = page.locator('#save-compare-structure');
    const input = key => page.locator(`[data-cs-key="${key}"]`);
    await input('input_dir').waitFor();
    assert.equal(await dialog.locator('input').count(), 10);
    assert.equal(await input('input_dir').inputValue(), fixture.folders.input_dir);
    assert.equal(await save.isDisabled(), true);
    assert.equal(await dialog.locator('svg').count() > 10, true);
    const screenshots = path.resolve('.tmp/compare-structure-screenshots');
    await fs.mkdir(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, 'desktop.png') });

    const originalOutput = fixture.folders.output_dir;
    await input('output_dir').fill('Output Updated');
    assert.equal(await save.isEnabled(), true);
    assert.match(await page.locator('#cs-path-preview').innerText(), /Output Updated/);
    await save.click();
    await page.waitForFunction(() => document.querySelector('#save-compare-structure').disabled
      && !document.querySelector('[data-cs-key="output_dir"]').disabled
      && document.querySelector('#cs-edit-state').textContent === 'Đồng bộ với file config');
    assert.equal(writes.length, 1);
    assert.equal(writes[0].folders.output_dir, 'Output Updated');
    assert.match(await page.locator('#compare-output-hint').innerText(), /Output Updated/);
    assert.equal(writes[0].folders.input_dir, fixture.folders.input_dir);
    await page.locator('#close-compare-structure').click();
    await page.locator('#open-compare-structure').click();
    await input('output_dir').waitFor();
    assert.equal(await input('output_dir').inputValue(), 'Output Updated');
    assert.equal(await save.isDisabled(), true);

    await input('output_dir').fill('Unsaved');
    await page.keyboard.press('Escape');
    await page.locator('#confirm-dialog').waitFor();
    await page.locator('#confirm-dialog button[value="cancel"]').click();
    assert.equal(await dialog.isVisible(), true);
    assert.equal(await input('output_dir').inputValue(), 'Unsaved');
    await page.locator('#reload-compare-structure').click();
    await page.locator('#confirm-accept').click();
    await page.waitForFunction(() => document.querySelector('[data-cs-key="output_dir"]').value === 'Output Updated');
    rejectSave = true;
    await input('output_dir').fill('Draft conflict');
    await save.click();
    await page.locator('#cs-error:not(.hidden)').waitFor();
    assert.equal(await input('output_dir').inputValue(), 'Draft conflict');
    assert.equal(await save.isEnabled(), true);
    await page.locator('#reload-compare-structure').click();
    await page.locator('#confirm-accept').click();
    await page.waitForFunction(() => document.querySelector('[data-cs-key="output_dir"]').value === 'Output Updated');
    assert.equal(await page.locator('#cs-error').isVisible(), false);

    const outputNode = input('output_dir').locator('xpath=ancestor::li[1]');
    await outputNode.locator(':scope > .cs-node-row .cs-collapse').click();
    assert.equal(await input('before_htm_dir').isVisible(), false);
    await outputNode.locator(':scope > .cs-node-row .cs-collapse').click();
    assert.equal(await input('before_htm_dir').isVisible(), true);

    for (const width of [960, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await input('after_htc_vs_htm_file').focus();
      const geometry = await dialog.evaluate(element => {
        const bounds = element.getBoundingClientRect();
        return { left: bounds.left, right: bounds.right, width: innerWidth,
          overflow: [...element.querySelectorAll('input')].some(input => input.getBoundingClientRect().right > bounds.right),
          footer: element.querySelector('footer').getBoundingClientRect().bottom,
          viewportHeight: innerHeight };
      });
      assert.ok(geometry.left >= 0 && geometry.right <= geometry.width + 1);
      assert.equal(geometry.overflow, false);
      assert.ok(geometry.footer <= geometry.viewportHeight);
      await page.screenshot({ path: path.join(screenshots, `width-${width}.png`) });
    }
    assert.deepEqual(errors, []);
    console.log(`PASS: tree, load/save/reopen, dirty state, cancel/reload, conflict recovery, collapse, desktop/mobile; ${writes.length} intercepted saves. Original output: ${originalOutput}`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
