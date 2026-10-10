const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'autocompare_tool', 'web', 'app.js'), 'utf8');
const context = vm.createContext({ document: { addEventListener() {} }, window: {} });
vm.runInContext(source, context);
vm.runInContext(String.raw`
  let visibleTestIndices = ['0', '1', '2'];
  visibleCompareFixmeIndices = () => visibleTestIndices;
  valueOf = () => 'NOTE_1';
  renderFixmes = () => {};
  syncFixmeRowChecks = () => {};
  syncComparePreviewNoteControls = () => {};
  updateFixmeToolbarState = () => {};
  updateCompareBulkToolbarState = () => {};
  showToast = () => {};
  state.fixmes = [
    { index: 0, record_number: 1, workbook_path: 'UT01/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F6' },
    { index: 1, record_number: 2, workbook_path: 'UT01/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F6' },
    { index: 2, record_number: 2, workbook_path: 'UT01/compare.xlsx', sheet_name: 'customers', fixme_cell: 'F7' },
  ];
  state.compareView.sheet = {
    record_count_mismatch_pair_starts: [5],
    rows: [
      { number: 6, cells: [{ fixme_indices: [0, 1] }] },
      { number: 7, cells: [{ fixme_indices: [2] }] },
    ],
  };

  // All rows receive the first note, then their ticks are cleared.
  state.fixmeCheckedRows = new Set(['0', '1', '2']);
  assignCompareBulkNote();
  globalThis.firstRound = { notes: { ...state.fixmeSelections }, checked: [...state.fixmeCheckedRows] };

  // Record 2 is hidden, but its FIXME cell is shared with visible record 1.
  state.compareExcludeRecordCountDifferences = true;
  globalThis.filteredRaw = compareVisibleFixmeIndices([0, 1]);
  visibleTestIndices = filteredRaw;
  state.fixmeCheckedRows.add('0');
  valueOf = () => 'NOTE_2';
  assignCompareBulkNote();
  globalThis.filteredRound = { notes: { ...state.fixmeSelections }, checked: [...state.fixmeCheckedRows] };
  globalThis.filteredCell = compareCellContent({ value: 'FIXME', fixme_indices: [0, 1] }, filteredRaw);

  state.compareExcludeRecordCountDifferences = false;
  visibleTestIndices = ['0', '1', '2'];
  globalThis.unfilteredCell = compareCellContent({ value: 'FIXME', fixme_indices: [0, 1] }, [0, 1]);
  startAction = (action, payload) => { globalThis.applyPayload = { action, payload }; };
  applySelectedFixmeNotes();
  globalThis.secondRoundPayload = globalThis.applyPayload;

  // A later assignment also replaces every record sharing the selected cell.
  state.fixmeCheckedRows.add('0');
  valueOf = () => 'NOTE_3';
  assignCompareBulkNote();
  globalThis.latestRound = { notes: { ...state.fixmeSelections }, checked: [...state.fixmeCheckedRows] };
`, context);

assert.deepEqual({ ...context.firstRound.notes }, { 0: 'NOTE_1', 1: 'NOTE_1', 2: 'NOTE_1' });
assert.deepEqual([...context.firstRound.checked], []);
assert.deepEqual([...context.filteredRaw], ['0']);
assert.deepEqual({ ...context.filteredRound.notes }, { 0: 'NOTE_2', 1: 'NOTE_2', 2: 'NOTE_1' });
assert.deepEqual([...context.filteredRound.checked], []);
assert.match(context.filteredCell, /value="NOTE_2"/);
assert.match(context.unfilteredCell, /value="NOTE_2"/);
assert.match(context.unfilteredCell, /data-compare-fixme-indices="0,1"/);
assert.match(context.unfilteredCell, /class="compare-note-summary hidden"/);
assert.deepEqual({ ...context.secondRoundPayload.payload.selections }, { 0: 'NOTE_2', 1: 'NOTE_2', 2: 'NOTE_1' });
assert.deepEqual({ ...context.latestRound.notes }, { 0: 'NOTE_3', 1: 'NOTE_3', 2: 'NOTE_1' });
assert.deepEqual([...context.latestRound.checked], []);
console.log('PASS: filtered assignment replaces the whole selected FIXME cell and survives removing the filter.');
