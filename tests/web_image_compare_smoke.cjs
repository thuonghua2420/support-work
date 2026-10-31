/* Run against a local server with Playwright available via NODE_PATH. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  const output = path.resolve('.tmp/ui-screenshots/image-compare');
  await fs.mkdir(output, { recursive: true });
  try {
    await page.goto(process.env.AUTOCOMPARE_URL || 'http://127.0.0.1:8785');
    await page.locator('[data-page="image-compare"]').click();
    assert.equal(await page.locator('.nav-item svg').count(), 9);
    const images = await page.evaluate(() => {
      function image(changed) {
        const c = document.createElement('canvas'); c.width = 960; c.height = 560;
        const ctx = c.getContext('2d');
        ctx.fillStyle = '#f0f4f9'; ctx.fillRect(0, 0, 960, 560);
        ctx.fillStyle = '#183b5b'; ctx.font = 'bold 30px Arial'; ctx.fillText('INVOICE / UT-001', 40, 60);
        ctx.fillStyle = '#fff'; ctx.fillRect(30, 100, 900, 410);
        ctx.fillStyle = '#385572'; ctx.font = '24px Arial';
        ctx.fillText('Customer: AUTOCOMPARE', 55, 155);
        ctx.fillText('Order: 2026-001', 55, 205);
        ctx.fillText(`Total: ${changed ? '125.00' : '100.00'}`, 55, 315);
        ctx.fillText(`Status: ${changed ? 'APPROVED' : 'PENDING'}`, 55, 445);
        return c.toDataURL('image/png');
      }
      return { old: image(false), new: image(true) };
    });
    const oldFile = { name: 'old.png', mimeType: 'image/png', buffer: Buffer.from(images.old.split(',')[1], 'base64') };
    const newFile = { name: 'new.png', mimeType: 'image/png', buffer: Buffer.from(images.new.split(',')[1], 'base64') };
    await page.locator('#ic-file-old').setInputFiles(oldFile);
    await page.locator('#ic-file-new').setInputFiles(newFile);
    // The comparison starts by itself once both images are present.
    await page.locator('#ic-results:not(.hidden)').waitFor();
    assert.match(await page.locator('#ic-verdict').innerText(), /Hai ảnh khác nhau/);
    const manifest = JSON.parse(await page.locator('#ic-evidence').textContent());
    assert.ok(manifest.changed_pixels > 0);
    assert.ok(manifest.regions.length >= 2);
    await page.locator('#ic-next').click();
    assert.equal(await page.locator('#ic-zoom').inputValue(), '1');
    assert.match(await page.locator('#ic-region').innerText(), /^2 /);
    await page.locator('[data-image-view="wipe"]').click();
    await page.locator('#ic-wipe').fill('25');
    assert.match(await page.locator('#ic-view-b').getAttribute('style'), /25%/);
    for (const width of [1440, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const mode of ['split', 'wipe', 'diff']) {
        await page.locator(`[data-image-view="${mode}"]`).click();
        await page.locator('#ic-zoom').selectOption('fit');
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
        assert.equal(overflow, false, `${mode} overflow at ${width}`);
      }
      await page.locator('#ic-results').screenshot({ path: path.join(output, `${width}-results.png`) });
    }
    for (const [id, filename] of [['html','Compare_Image_Report.html'], ['png','Compare_Image_Diff.png'], ['json','Compare_Image.json']]) {
      const downloadEvent = page.waitForEvent('download');
      await page.locator(`#ic-export-${id}`).click();
      const download = await downloadEvent;
      assert.equal(download.suggestedFilename(), filename);
      const file = path.join(output, filename);
      await download.saveAs(file);
      if (id === 'html') {
        const content = await fs.readFile(file, 'utf8');
        assert.ok(content.includes(manifest.old.file_sha256));
        assert.ok(content.includes('data:image/png;base64,'));
      }
      if (id === 'json') assert.equal(JSON.parse(await fs.readFile(file, 'utf8')).changed_pixels, manifest.changed_pixels);
    }
    // Exercise the Ctrl+V event handler into the selected side, without replacing
    // the user's real system clipboard during a smoke test.
    await page.locator('#ic-drop-new').click();
    await page.evaluate((dataUrl) => {
      const bytes = Uint8Array.from(atob(dataUrl.split(',')[1]), c => c.charCodeAt(0));
      const transfer = new DataTransfer(); transfer.items.add(new File([bytes], 'pasted.png', { type: 'image/png' }));
      document.dispatchEvent(new ClipboardEvent('paste', { clipboardData: transfer, bubbles: true, cancelable: true }));
    }, images.old);
    await page.waitForFunction(() => document.querySelector('#ic-info-new').textContent.includes('pasted.png'));
    await page.locator('#ic-results:not(.hidden)').waitFor();
    assert.match(await page.locator('#ic-verdict').innerText(), /Hai ảnh giống nhau/);
    assert.ok(await page.locator('#ic-next').isDisabled());
    await page.locator('[data-image-clear="new"]').click();
    assert.ok(await page.locator('#ic-compare').isDisabled());
    assert.ok(await page.locator('#ic-results').evaluate(el => el.classList.contains('hidden')));
    // Exercise Paste button with browser clipboard adapter, without touching OS clipboard.
    await page.evaluate((dataUrl) => {
      const bytes = Uint8Array.from(atob(dataUrl.split(',')[1]), c => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: 'image/png' });
      Object.defineProperty(navigator.clipboard, 'read', { configurable: true, value: async () => [{ types: ['image/png'], getType: async () => blob }] });
    }, images.new);
    await page.locator('[data-image-paste="new"]').click();
    await page.waitForFunction(() => document.querySelector('#ic-info-new').textContent.includes('Clipboard-new.png'));
    await page.evaluate((dataUrl) => {
      const bytes = Uint8Array.from(atob(dataUrl.split(',')[1]), c => c.charCodeAt(0));
      const transfer = new DataTransfer(); transfer.items.add(new File([bytes], 'dropped.png', { type: 'image/png' }));
      document.querySelector('#ic-drop-old').dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, bubbles: true, cancelable: true }));
    }, images.new);
    await page.waitForFunction(() => document.querySelector('#ic-info-old').textContent.includes('dropped.png'));
    await page.locator('#ic-results:not(.hidden)').waitFor();
    assert.match(await page.locator('#ic-verdict').innerText(), /Hai ảnh giống nhau/);
    assert.deepEqual(errors, []);
    console.log('PASS: real image API, import, paste event/button, drag-drop, exact verdicts, 3 views, region navigation, zoom, 3 downloads, 4 widths, invalidation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
