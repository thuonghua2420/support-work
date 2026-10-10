const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'autocompare_tool', 'web', 'app.js'), 'utf8');
const controls = new Map();
const document = {
  addEventListener() {},
  body: { classList: { contains: () => false } },
  querySelector(selector) {
    if (!controls.has(selector)) controls.set(selector, {
      classList: { remove() {} }, textContent: '', disabled: false, checked: false, indeterminate: false,
    });
    return controls.get(selector);
  },
  querySelectorAll() { return []; },
};
const context = vm.createContext({ document, window: {} });
vm.runInContext(source, context);
vm.runInContext(String.raw`
  let visibleIndices = ['0', '1'];
  visibleCompareFixmeIndices = () => visibleIndices;
  valueOf = () => 'NOTE_2';
  renderFixmes = () => {};
  syncFixmeRowChecks = () => {};
  syncComparePreviewNoteControls = () => {};
  updateFixmeToolbarState = () => {};
  showToast = () => {};
  state.fixmes = [
    { index: 0, workbook_path: 'UT01/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F6' },
    { index: 1, workbook_path: 'UT01/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F6' },
    { index: 2, workbook_path: 'UT01/compare.xlsx', sheet_name: 'orders', fixme_cell: 'F6' },
    { index: 3, workbook_path: 'UT02/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F6' },
  ];

  // Tick a row on customers, then navigate to orders. The toolbar must still
  // count and allow assigning the off-sheet selection.
  state.fixmeCheckedRows = new Set(['0']);
  state.compareView.activeSheetName = 'orders';
  visibleIndices = ['2'];
  updateCompareBulkToolbarState();
  globalThis.afterSwitch = {
    count: $('#compare-checked-count').textContent,
    assignDisabled: $('#compare-bulk-assign').disabled,
    currentSheetChecked: $('#compare-check-visible').checked,
  };

  assignCompareBulkNote();
  globalThis.offSheetAssign = {
    notes: { ...state.fixmeSelections },
    checked: [...state.fixmeCheckedRows],
  };

  state.fixmeCheckedRows.add('0');
  state.fixmeCheckedRows.add('2');
  updateCompareBulkToolbarState();
  globalThis.beforeAssign = $('#compare-checked-count').textContent;
  assignCompareBulkNote();
  globalThis.afterAssign = {
    notes: { ...state.fixmeSelections },
    checked: [...state.fixmeCheckedRows],
    count: $('#compare-checked-count').textContent,
  };

  // Bỏ tick from either sheet clears the global selection shown by the toolbar.
  state.fixmeCheckedRows.add('0');
  state.compareView.activeSheetName = 'orders';
  clearCompareRowSelection();
  globalThis.afterClear = [...state.fixmeCheckedRows];
`, context);

assert.equal(context.afterSwitch.count, '1 dòng đã tick');
assert.equal(context.afterSwitch.assignDisabled, false);
assert.equal(context.afterSwitch.currentSheetChecked, false);
assert.deepEqual({ ...context.offSheetAssign.notes }, { 0: 'NOTE_2', 1: 'NOTE_2' });
assert.deepEqual([...context.offSheetAssign.checked], []);
assert.equal(context.beforeAssign, '2 dòng đã tick');
assert.deepEqual({ ...context.afterAssign.notes }, { 0: 'NOTE_2', 1: 'NOTE_2', 2: 'NOTE_2' });
assert.deepEqual([...context.afterAssign.checked], []);
assert.equal(context.afterAssign.count, '0 dòng đã tick');
assert.deepEqual([...context.afterClear], []);
console.log('PASS: checked rows survive sheet changes, bulk note spans sheets, and clear resets all ticks.');
