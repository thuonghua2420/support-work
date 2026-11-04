/* Only writes generated fixtures under .tmp. No real DB or user file mutation. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const root = await fs.mkdtemp(path.resolve('.tmp/text-compare-test-'));
  const left = path.join(root, 'left'), right = path.join(root, 'right');
  await fs.mkdir(left); await fs.mkdir(right);
  const a = path.join(left, 'sample.js'), b = path.join(right, 'sample.js');
  const eolA = path.join(root, 'LF.txt'), eolB = path.join(root, 'CRLF.txt');
  await fs.writeFile(eolA, 'equal\n'); await fs.writeFile(eolB, 'equal\r\n');
  await fs.writeFile(a, 'const label = "old";\r\nconsole.log(label);\r\n');
  await fs.writeFile(b, 'const label = "new";\nconsole.log(label);\n');
  // Case-only and whitespace-only differences plus one real change, to exercise the "ignore" options.
  const caseA = path.join(root, 'case-a.txt'), caseB = path.join(root, 'case-b.txt');
  await fs.writeFile(caseA, 'Hello World\nsame\nreal old\n  indented\n');
  await fs.writeFile(caseB, 'hello world\nsame\nreal new\nindented\n');
  await fs.writeFile(path.join(left, 'left-only.txt'), 'left');
  await fs.mkdir(path.join(left, 'nested')); await fs.mkdir(path.join(right, 'nested'));
  for (const dir of [left, right]) await fs.writeFile(path.join(dir, 'nested', 'same.bin'), Buffer.from([0, 1, 2]));
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--disable-gpu-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await fs.mkdir('.tmp/text-compare-screenshots', { recursive: true });
  const capture = async name => {
    await page.screenshot({ path: `.tmp/text-compare-screenshots/${name}.png`, fullPage: true });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), `${name}: page overflow`);
  };
  const summary = () => page.locator('#tc-summary').innerText();
  const openFiles = async paths => {
    await page.locator('#tc-count').selectOption(String(paths.length));
    for (const [index, file] of paths.entries()) await page.locator(`#tc-path-${index}`).fill(file);
    await page.locator('#tc-open').click();
    await page.locator('#tc-files-view:not(.hidden) .CodeMirror').first().waitFor();
  };
  const backToSelect = async () => {
    await page.locator('#tc-back').click();
    if (await page.locator('#confirm-dialog[open]').count()) await page.locator('#confirm-accept').click();
    await page.locator('#tc-select-view:not(.hidden)').waitFor();
  };
  try {
    await page.goto('http://127.0.0.1:8799/#text-compare');
    await page.waitForSelector('#page-text-compare.active');
    if (await page.locator('#tc-folder-view:not(.hidden)').count()) await page.locator('#tc-folder-back').click();
    assert.ok(await page.locator('#tc-select-view').isVisible(), 'Paths are chosen on their own page');
    assert.equal(await page.locator('#tc-files-view').isVisible(), false, 'The diff is not shown until files are opened');
    await capture('select');

    // Equal content, different line endings, then byte-identical.
    await openFiles([eolA, eolB]);
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('xuống dòng khác'));
    await backToSelect();
    await openFiles([eolA, eolA]);
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('100% về byte'));
    await backToSelect();

    // Two files: syntax, navigation, merge arrows, undo, save.
    await openFiles([a, b]);
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('sai khác'));
    assert.equal(await page.locator('#tc-editor .CodeMirror').count(), 2);
    assert.ok(await page.locator('#tc-editor .cm-keyword').count() > 0, 'Syntax highlighting enabled for JS');
    assert.ok(await page.locator('.CodeMirror-merge-copy').count() > 0, 'Merge arrows sit between the panes');
    assert.match(await page.locator('#tc-position').innerText(), /^1 \/ 1$/);
    await capture('two-files');
    await page.locator('#tc-copy-right').click();
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('Nội dung giống nhau'));
    assert.match(await fs.readFile(b, 'utf8'), /new/, 'Merging alone does not write the file');
    await page.locator('#tc-undo').click();
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('1 sai khác'));
    await page.locator('#tc-copy-left').click();                       // B -> A
    await page.waitForFunction(() => document.querySelector('.tc-title.tc-dirty'));
    assert.match(await fs.readFile(a, 'utf8'), /old/, 'Merging alone does not write the file');
    await page.locator('#tc-save-all').click();
    await page.locator('#confirm-accept').click();
    await page.waitForFunction(() => document.querySelector('#tc-message').textContent.includes('Đã lưu'));
    assert.equal(await fs.readFile(a, 'utf8'), 'const label = "new";\r\nconsole.log(label);\r\n', 'CRLF is preserved on save');
    await fs.writeFile(a, 'external change');
    await page.evaluate(() => document.querySelector('#tc-editor .CodeMirror').CodeMirror.setValue('do not overwrite external'));
    await page.locator('[data-tc-save="0"]').click();
    await page.locator('#confirm-accept').click();
    await page.waitForFunction(() => document.querySelector('#tc-message').textContent.includes('bên ngoài'));
    assert.equal(await fs.readFile(a, 'utf8'), 'external change');
    await backToSelect();

    // Ignore options and copy-all.
    await openFiles([caseA, caseB]);
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('3 sai khác'));
    await page.locator('#tc-options-btn').click();
    await page.locator('#tc-opt-case').check(); await page.locator('#tc-opt-ws').check();
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('1 sai khác'));
    await page.locator('#tc-copy-all-right').click();
    await page.waitForFunction(() => !document.querySelector('#tc-summary').textContent.includes('1 sai khác'));
    await page.locator('#tc-options-btn').click();
    await page.locator('#tc-opt-case').uncheck(); await page.locator('#tc-opt-ws').uncheck();
    await page.keyboard.press('Escape');
    await backToSelect();

    // Three files with a moved block.
    await openFiles([a, b, b]);
    assert.equal(await page.locator('#tc-editor .CodeMirror').count(), 3);
    assert.equal(await page.locator('.tc-title').count(), 3);
    await page.evaluate(() => {
      const editors = [...document.querySelectorAll('#tc-editor .CodeMirror')].map(node => node.CodeMirror);
      editors[0].setValue('function movedBlock() {\n  return "move me";\n}\nconst a = 1;\nconst b = 2;\nconst c = 3;\n');
      editors[1].setValue('const a = 1;\nconst b = 2;\nconst c = 3;\nfunction movedBlock() {\n  return "move me";\n}\n');
      editors[2].setValue('const a = 1;\nconst b = 200;\nconst c = 3;\nfunction movedBlock() {\n  return "move me";\n}\n');
    });
    await page.waitForFunction(() => document.querySelector('#tc-summary').textContent.includes('dòng di chuyển'));
    await capture('three-files-moved');
    assert.ok(await page.locator('#tc-copy-all-right').isDisabled(), 'Copy-all is only for two files');
    await page.locator('#tc-expand').click(); await capture('three-files-fullscreen');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tc-expand').getAttribute('aria-pressed'), 'false');
    await page.locator('#tc-options-btn').click();
    await page.locator('#tc-editable').uncheck();
    assert.ok(await page.evaluate(() => [...document.querySelectorAll('#tc-editor .CodeMirror')].every(node => node.CodeMirror.getOption('readOnly'))));
    assert.equal(await page.locator('.CodeMirror-merge-copy:visible').count(), 0, 'No merge arrows while editing is off');
    await page.locator('#tc-editable').check(); await page.locator('#tc-wrap').uncheck(); await page.locator('#tc-wrap').check();
    await page.keyboard.press('Escape');
    // Leaving with unsaved drafts is confirmed, and cancelling keeps them.
    await page.locator('#tc-back').click();
    await page.locator('#confirm-dialog button[value="cancel"]').click();
    assert.equal(await page.locator('#tc-editor .CodeMirror').count(), 3, 'Cancelling keeps all drafts');
    await page.locator('#tc-back').click(); await page.locator('#confirm-accept').click();

    // Folder comparison.
    await page.locator('[data-tc-mode="folders"]').click();
    await page.locator('#tc-folder-left').fill(left); await page.locator('#tc-folder-right').fill(right);
    await page.locator('#tc-folder-run').click();
    await page.locator('#tc-folder-view:not(.hidden)').waitFor({ timeout: 15000 });
    await page.getByRole('button', { name: /Tất cả/ }).click();
    await page.locator('#tc-grid-body tr', { hasText: 'same.bin' }).waitFor();
    await capture('folder-tree');
    await page.getByRole('button', { name: /^Khác nhau/ }).click();
    assert.equal(await page.locator('#tc-grid-body tr[data-i]').count(), 1);
    await page.locator('#tc-tree').uncheck();
    await capture('folder-filtered');
    await page.locator('#tc-grid-body tr', { hasText: 'sample.js' }).dblclick();
    await page.locator('#tc-files-view:not(.hidden) .CodeMirror').first().waitFor();
    assert.equal(await page.locator('#tc-editor .CodeMirror').count(), 2, 'Folder pair opens in two panes');
    assert.equal(await page.locator('#tc-file-nav').isVisible(), true, 'Pair navigation shows when opened from a folder');
    await page.locator('#tc-back').click();
    await page.locator('#tc-folder-view:not(.hidden)').waitFor();
    for (const width of [1920, 1024, 768, 390]) {
      await page.setViewportSize({ width, height: 960 });
      await capture(`${width}-folder`);
      await page.locator('#tc-folder-back').click(); await capture(`${width}-select`);
      await page.locator('#tc-recent-list button').first().click();
      await page.locator('#tc-folder-view:not(.hidden)').waitFor({ timeout: 15000 });
    }
    assert.deepEqual(errors, []);
    console.log('Text compare smoke passed: separate path page, 2/3 panes, syntax, merge arrows + toolbar merge, undo, copy-all, ignore options, confirmed save, CRLF preservation, conflict protection, folder grid/filter/open and four widths.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
