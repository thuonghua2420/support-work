"use strict";

const state = {
  bootstrap: null,
  notes: [],
  fixmes: [],
  job: null,
  jobCursor: 0,
  handledJobs: new Set(),
  pollTimer: null,
  dbVerified: { main: false, source: false, target: false },
  databaseNames: { main: [], source: [], target: [] },
  sourceTables: [],
  selectedTables: [],
  picker: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindNavigation();
  bindMobileMenu();
  bindTabs();
  bindActivityPanel();
  bindForms();
  bindDialogs();
  try {
    state.bootstrap = await api("/api/bootstrap");
    state.notes = state.bootstrap.notes || [];
    state.fixmes = state.bootstrap.fixmes || [];
    hydrateDefaults();
    renderWorkflows();
    renderConnectionForms();
    renderNotes();
    renderFixmes();
    renderTables();
    if (state.bootstrap.job) {
      state.job = state.bootstrap.job;
      state.jobCursor = 0;
      await pollJob();
    } else {
      setJobVisual("idle", "Sẵn sàng");
    }
  } catch (error) {
    showToast(error.message, "error", 7000);
    setJobVisual("error", "Không thể khởi tạo");
  }
}

function bindNavigation() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page, true)));
  const initialPage = window.location.hash.slice(1);
  if ($(`.nav-item[data-page="${initialPage}"]`)) showPage(initialPage, false);
  window.addEventListener("hashchange", () => {
    const pageKey = window.location.hash.slice(1);
    if ($(`.nav-item[data-page="${pageKey}"]`)) showPage(pageKey, false);
  });
}

function showPage(pageKey, updateHash) {
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === pageKey));
    $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${pageKey}`));
    const page = $(`#page-${pageKey}`);
    $("#page-title").textContent = page.dataset.title;
    $("#page-eyebrow").textContent = page.dataset.eyebrow;
    $("#sidebar").classList.remove("open");
    if (updateHash) history.replaceState(null, "", `#${pageKey}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindMobileMenu() {
  $("#menu-toggle").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
}

function bindTabs() {
  $$(".tab").forEach((button) => button.addEventListener("click", () => {
    const group = button.dataset.tabGroup;
    const tab = button.dataset.tab;
    $$(`.tab[data-tab-group="${group}"]`).forEach((item) => item.classList.toggle("active", item === button));
    $$(`[data-tab-panel^="${group}:"]`).forEach((panel) => panel.classList.toggle("active", panel.dataset.tabPanel === `${group}:${tab}`));
  }));
}

function bindActivityPanel() {
  const panel = $("#activity-panel");
  $("#activity-toggle").addEventListener("click", () => panel.classList.toggle("collapsed"));
  $("#job-status-button").addEventListener("click", () => panel.classList.remove("collapsed"));
  $("#clear-log").addEventListener("click", () => { $("#activity-log").textContent = ""; });
}

function bindForms() {
  $("#compare-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const workflows = $$("input[name='compare-workflow']:checked").map((item) => item.value);
    startAction("compare", { root: valueOf("compare-root"), workflows });
  });
  $("#toggle-workflows").addEventListener("click", () => {
    const boxes = $$("input[name='compare-workflow']");
    const selectAll = boxes.some((box) => !box.checked);
    boxes.forEach((box) => { box.checked = selectAll; });
  });
  $("#folder-compare-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("folder_compare", {
      left: valueOf("folder-left"),
      right: valueOf("folder-right"),
      output: valueOf("folder-output"),
    });
  });
  $("#copy-ut-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("copy_ut", { source: valueOf("copy-source"), target: valueOf("copy-target") });
  });

  $("#rename-exact-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("rename_exact", {
      root: valueOf("utility-root"), old_name: valueOf("rename-exact-old"), new_name: valueOf("rename-exact-new"),
      include_files: checked("rename-exact-files"), include_folders: checked("rename-exact-folders"),
    });
  });
  $("#rename-contains-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("rename_contains", {
      root: valueOf("utility-root"), contains_text: valueOf("rename-contains-text"), replacement_text: valueOf("rename-replacement"),
      include_files: checked("rename-contains-files"), include_folders: checked("rename-contains-folders"),
    });
  });
  $("#delete-contains-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const keyword = valueOf("delete-contains-text");
    const confirmed = await confirmAction(
      "Xóa file/folder phù hợp?",
      `Mọi file/folder bên dưới “${valueOf("utility-root")}” có tên chứa “${keyword}” sẽ bị xóa. Thao tác này không thể hoàn tác.`
    );
    if (confirmed) startAction("delete_contains", {
      root: valueOf("utility-root"), contains_text: keyword,
      include_files: checked("delete-contains-files"), include_folders: checked("delete-contains-folders"), confirmed: true,
    });
  });
  $("#rename-sheets-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("rename_sheets", {
      excel_path: valueOf("sheet-excel-path"), contains_text: valueOf("sheet-contains-text"), replacement_text: valueOf("sheet-replacement"),
    });
  });
  $("#move-files-form").addEventListener("submit", (event) => {
    event.preventDefault();
    startAction("move_files", {
      root: valueOf("utility-root"), contains_text: valueOf("move-contains-text"), target_folder_name: valueOf("move-target-folder"),
    });
  });
  $("#find-empty").addEventListener("click", () => startAction("find_empty_folders", { root: valueOf("utility-root") }));
  $("#delete-empty").addEventListener("click", async () => {
    if (await confirmAction("Xóa toàn bộ folder trống?", `Các folder trống bên dưới “${valueOf("utility-root")}” sẽ bị xóa. Folder gốc được giữ nguyên.`)) {
      startAction("delete_empty_folders", { root: valueOf("utility-root"), confirmed: true });
    }
  });

  $("#db-normalize").addEventListener("click", () => {
    if (!requireVerified("main")) return;
    startAction("db_normalize", { csv_path: valueOf("db-csv-path"), settings: getDbSettings("main") });
  });
  $("#db-import").addEventListener("click", async () => {
    if (!requireVerified("main")) return;
    const importMode = selectedImportMode();
    const confirmations = {
      append: {
        title: "Import thêm CSV vào cơ sở dữ liệu?",
        message: "Toàn bộ CSV hợp lệ trong folder đã chọn sẽ được INSERT vào table tương ứng. Dữ liệu hiện có được giữ nguyên.",
      },
      delete_matching_keys: {
        title: "Xóa record trùng key rồi import?",
        message: "Với từng CSV, hệ thống sẽ xóa record trong database có cùng toàn bộ primary key rồi mới INSERT dữ liệu CSV. CSV phải chứa đầy đủ primary key; nếu key là identity, cần bật “Giữ giá trị identity”.",
      },
      truncate_table: {
        title: "Truncate toàn table rồi import?",
        message: "CẢNH BÁO: Mỗi table tương ứng với CSV sẽ bị TRUNCATE, xóa sạch toàn bộ dữ liệu hiện có, rồi mới INSERT dữ liệu CSV. Một số database tự commit lệnh TRUNCATE nên không thể rollback nếu bước insert sau đó lỗi.",
      },
    };
    const confirmation = confirmations[importMode] || confirmations.append;
    if (await confirmAction(confirmation.title, confirmation.message)) {
      startAction("db_import", {
        csv_path: valueOf("db-csv-path"),
        settings: getDbSettings("main"),
        keep_identity: checked("db-keep-identity"),
        existing_row_mode: importMode,
        confirmed: true,
      });
    }
  });
  $$('input[name="db-import-mode"]').forEach((input) => input.addEventListener("change", syncImportButtonLabel));
  syncImportButtonLabel();
  $("#db-export").addEventListener("click", async () => {
    if (!requireVerified("main")) return;
    if (await confirmAction("Export dữ liệu ra CSV?", "Các file CSV trong folder đích có cùng tên table có thể bị ghi đè bằng dữ liệu mới.")) {
      startAction("db_export", { csv_path: valueOf("db-csv-path"), settings: getDbSettings("main"), table_names: valueOf("db-export-tables"), confirmed: true });
    }
  });
  $("#db-sync-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!requireVerified("source") || !requireVerified("target")) return;
    const allTables = checked("sync-all-tables");
    const tableNames = allTables ? state.sourceTables : state.selectedTables;
    if (!tableNames.length) {
      showToast("Vui lòng chọn ít nhất một table hoặc bật đồng bộ toàn bộ table.", "error");
      return;
    }
    const syncMode = selectedSyncMode();
    const limit = valueOf("sync-record-limit");
    const batchSize = valueOf("sync-batch-size");
    const deleteTargetOnly = syncMode === "incremental" && checked("sync-delete-target-only");
    const modeDetails = {
      incremental: deleteTargetOnly
        ? "Chỉ INSERT/UPDATE record khác biệt và DELETE record chỉ có ở đích. Table phải có primary key."
        : "Chỉ INSERT/UPDATE record khác biệt; record chỉ có ở đích sẽ được giữ lại.",
      append: "Toàn bộ record nguồn sẽ được INSERT thêm; dữ liệu hiện có ở đích được giữ nguyên.",
      truncate_table: "CẢNH BÁO: table đích sẽ bị TRUNCATE rồi INSERT lại toàn bộ dữ liệu nguồn.",
    };
    const detail = [
      `Đồng bộ ${allTables ? "toàn bộ table nguồn" : `${tableNames.length} table đã chọn`} từ nguồn sang đích.`,
      modeDetails[syncMode],
      syncMode === "incremental"
        ? `Dữ liệu được đọc và ghi theo batch ${batchSize || "5000"} record; không nạp toàn bộ table vào RAM.`
        : (limit ? `Mỗi table chỉ đồng bộ tối đa ${limit} record.` : "Đồng bộ toàn bộ record trong mỗi table."),
    ].join("\n\n");
    if (await confirmAction("Xác nhận đồng bộ cơ sở dữ liệu", detail)) {
      startAction("db_sync", {
        source_settings: getDbSettings("source"), target_settings: getDbSettings("target"), table_names: tableNames,
        record_limit: limit, keep_identity: checked("sync-keep-identity"), sync_mode: syncMode,
        batch_size: batchSize, delete_target_only: deleteTargetOnly,
        truncate_before_sync: syncMode === "truncate_table", confirmed: true,
      });
    }
  });

  $$('input[name="sync-mode"]').forEach((input) => input.addEventListener("change", syncSyncModeControls));
  syncSyncModeControls();
  $("#sync-all-tables").addEventListener("change", renderTables);
  $("#sync-table-filter").addEventListener("input", renderTables);
  $("#clear-selected-tables").addEventListener("click", () => { state.selectedTables = []; renderTables(); });
  $("#apply-fixmes").addEventListener("click", () => {
    const selections = {};
    $$("select[data-fixme-index]").forEach((select) => { if (select.value) selections[select.dataset.fixmeIndex] = select.value; });
    startAction("apply_fixmes", { selections });
  });

  $$('[data-browse-target]').forEach((button) => button.addEventListener("click", () => openPathPicker(button)));
}

function bindDialogs() {
  $("#manage-notes").addEventListener("click", () => { renderNotes(); $("#notes-dialog").showModal(); });
  $("#close-notes").addEventListener("click", () => $("#notes-dialog").close());
  $("#note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const response = await api("/api/notes/save", {
        method: "POST",
        body: { old_value: valueOf("note-old-value"), value: valueOf("note-value"), meaning: valueOf("note-meaning") },
      });
      state.notes = response.notes;
      clearNoteForm();
      renderNotes();
      refreshFixmeNoteOptions();
      showToast("Đã lưu ghi chú.", "success");
    } catch (error) { showToast(error.message, "error"); }
  });
  $("#delete-note").addEventListener("click", async () => {
    const value = valueOf("note-old-value") || valueOf("note-value");
    if (!value) return;
    if (!await confirmAction("Xóa ghi chú?", `Ghi chú “${value}” sẽ bị xóa khỏi danh sách lựa chọn.`)) return;
    try {
      const response = await api("/api/notes/delete", { method: "POST", body: { value } });
      state.notes = response.notes;
      clearNoteForm();
      renderNotes();
      refreshFixmeNoteOptions();
      showToast("Đã xóa ghi chú.", "success");
    } catch (error) { showToast(error.message, "error"); }
  });

  $("#path-up").addEventListener("click", () => { if (state.picker?.parent) loadPickerPath(state.picker.parent); });
  $("#path-go").addEventListener("click", () => loadPickerPath(valueOf("path-current")));
  $("#path-current").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); loadPickerPath(valueOf("path-current")); } });
  $("#path-root-select").addEventListener("change", (event) => loadPickerPath(event.target.value));
  $("#path-confirm").addEventListener("click", (event) => {
    event.preventDefault();
    confirmPathPicker();
  });
}

function hydrateDefaults() {
  const cwd = state.bootstrap.cwd;
  $("#server-address").textContent = `127.0.0.1:${state.bootstrap.port}`;
  $("#compare-root").value = cwd;
  $("#utility-root").value = cwd;
  $("#db-csv-path").value = cwd;
  $("#folder-output").value = joinPath(cwd, state.bootstrap.folder_compare_file);
  $("#workflow-count").textContent = String(state.bootstrap.compare_workflows.filter((item) => item.default_enabled).length);
}

function renderWorkflows() {
  const container = $("#compare-workflows");
  container.innerHTML = state.bootstrap.compare_workflows.map((workflow) => `
    <label class="choice-card">
      <input type="checkbox" name="compare-workflow" value="${escapeHtml(workflow.key)}" ${workflow.default_enabled ? "checked" : ""}>
      <b>${escapeHtml(workflow.label)}</b>
      <small>${escapeHtml(workflow.key.replaceAll("_", " · "))}</small>
    </label>`).join("");
}

function renderConnectionForms() {
  $$('[data-db-scope]').forEach((form) => {
    const scope = form.dataset.dbScope;
    const defaults = state.bootstrap.database_defaults["SQL Server"] || { port: "1433", schema: "dbo" };
    const drivers = state.bootstrap.sqlserver_drivers.length ? state.bootstrap.sqlserver_drivers : ["ODBC Driver 18 for SQL Server"];
    $(".connection-fields", form).innerHTML = `
      <label class="field"><span>Loại CSDL</span><select id="db-${scope}-type">${state.bootstrap.database_types.map((item) => `<option>${escapeHtml(item)}</option>`).join("")}</select></label>
      <label class="field"><span>Port</span><input id="db-${scope}-port" value="${escapeHtml(defaults.port)}"></label>
      <label class="field host-field"><span>Server / Host</span><input id="db-${scope}-host" placeholder="localhost hoặc server\\instance"></label>
      <label class="field"><span>Database / Service</span><input id="db-${scope}-database" list="db-${scope}-database-list"><datalist id="db-${scope}-database-list"></datalist></label>
      <label class="field"><span>Schema</span><input id="db-${scope}-schema" value="${escapeHtml(defaults.schema)}"></label>
      <label class="field auth-row" id="db-${scope}-driver-field"><span>Driver ODBC</span><select id="db-${scope}-driver">${drivers.map((item) => `<option>${escapeHtml(item)}</option>`).join("")}</select></label>
      <label class="field"><span>User</span><input id="db-${scope}-username" autocomplete="username"></label>
      <label class="field"><span>Password</span><input id="db-${scope}-password" type="password" autocomplete="current-password"></label>
      <div class="check-row auth-row" id="db-${scope}-trusted-row"><label><input type="checkbox" id="db-${scope}-trusted" ${scope === "main" || scope === "source" || scope === "target" ? "checked" : ""}> Xác thực Windows</label></div>`;

    form.addEventListener("submit", (event) => event.preventDefault());

    $$(`input, select`, form).forEach((input) => input.addEventListener("change", () => {
      if (input.id === `db-${scope}-type`) applyDatabaseType(scope, true);
      if (input.id === `db-${scope}-trusted`) syncAuthFields(scope);
      setVerified(scope, false);
    }));
    $(`#db-${scope}-trusted`).addEventListener("change", () => syncAuthFields(scope));
    applyDatabaseType(scope, false);
    syncAuthFields(scope);
  });

  $$('[data-db-test]').forEach((button) => button.addEventListener("click", () => {
    const scope = button.dataset.dbTest;
    startAction("db_test", { settings: getDbSettings(scope), role: scope, load_tables: scope === "source" });
  }));
  $$('[data-db-load]').forEach((button) => button.addEventListener("click", () => {
    const scope = button.dataset.dbLoad;
    startAction("db_list_databases", { settings: getDbSettings(scope), role: scope });
  }));
}

function applyDatabaseType(scope, resetDefaults) {
  const type = valueOf(`db-${scope}-type`);
  const defaults = state.bootstrap.database_defaults[type] || { port: "", schema: "" };
  if (resetDefaults || !valueOf(`db-${scope}-port`)) $(`#db-${scope}-port`).value = defaults.port || "";
  if (resetDefaults || !valueOf(`db-${scope}-schema`)) $(`#db-${scope}-schema`).value = defaults.schema || "";
  const sqlServer = type === "SQL Server";
  $(`#db-${scope}-driver-field`).classList.toggle("hidden", !sqlServer);
  $(`#db-${scope}-trusted-row`).classList.toggle("hidden", !sqlServer);
  syncAuthFields(scope);
}

function syncAuthFields(scope) {
  const trusted = valueOf(`db-${scope}-type`) === "SQL Server" && checked(`db-${scope}-trusted`);
  $(`#db-${scope}-username`).disabled = trusted;
  $(`#db-${scope}-password`).disabled = trusted;
}

function getDbSettings(scope) {
  return {
    database_type: valueOf(`db-${scope}-type`),
    host: valueOf(`db-${scope}-host`),
    port: valueOf(`db-${scope}-port`),
    database: valueOf(`db-${scope}-database`),
    schema: valueOf(`db-${scope}-schema`),
    driver: valueOf(`db-${scope}-driver`),
    username: valueOf(`db-${scope}-username`),
    password: valueOf(`db-${scope}-password`),
    trusted_connection: checked(`db-${scope}-trusted`),
    trust_server_certificate: true,
    encrypt: true,
  };
}

function setVerified(scope, verified) {
  state.dbVerified[scope] = verified;
  const indicator = $(`[data-verified-state="${scope}"]`);
  indicator.textContent = verified ? "Đã kết nối" : "Chưa kiểm tra";
  indicator.classList.toggle("verified", verified);
  if (scope === "source" && !verified) {
    state.sourceTables = [];
    state.selectedTables = [];
    renderTables();
  }
}

function requireVerified(scope) {
  if (state.dbVerified[scope]) return true;
  showToast(`Vui lòng test kết nối CSDL ${scope === "main" ? "" : scope === "source" ? "nguồn " : "đích "}thành công trước.`, "error");
  return false;
}

function selectedImportMode() {
  return $('input[name="db-import-mode"]:checked')?.value || "append";
}

function syncImportButtonLabel() {
  const labels = {
    append: "Import CSV",
    delete_matching_keys: "Xóa trùng key & Import",
    truncate_table: "Truncate & Import",
  };
  $("#db-import").textContent = labels[selectedImportMode()] || labels.append;
}

function selectedSyncMode() {
  return $('input[name="sync-mode"]:checked')?.value || "incremental";
}

function syncSyncModeControls() {
  const mode = selectedSyncMode();
  const incremental = mode === "incremental";
  const limitInput = $("#sync-record-limit");
  limitInput.disabled = incremental;
  if (incremental) limitInput.value = "";
  $("#sync-batch-size").disabled = !incremental;
  $("#sync-delete-target-only").disabled = !incremental;
  $("#sync-delete-target-only-row").classList.toggle("disabled", !incremental);
  const labels = {
    incremental: "Đồng bộ chênh lệch",
    append: "Insert toàn bộ dữ liệu",
    truncate_table: "Truncate & đồng bộ lại",
  };
  const hints = {
    incremental: "Chỉ ghi các record khác biệt; table nguồn và đích phải có primary key giống nhau.",
    append: "Insert toàn bộ record nguồn; có thể lỗi duplicate key nếu đích đã có dữ liệu.",
    truncate_table: "Xóa sạch table đích rồi insert lại toàn bộ dữ liệu nguồn.",
  };
  $("#run-db-sync").innerHTML = `${labels[mode] || labels.incremental} <b>→</b>`;
  $("#sync-mode-hint").textContent = hints[mode] || hints.incremental;
}

function renderFixmes() {
  $("#fixme-count").textContent = String(state.fixmes.length);
  $("#fixme-empty").classList.toggle("hidden", state.fixmes.length > 0);
  $("#fixme-table-wrap").classList.toggle("hidden", state.fixmes.length === 0);
  const options = [`<option value="">Chọn ghi chú</option>`, ...state.notes.map((note) => `<option value="${escapeHtml(note.value)}">${escapeHtml(note.value)}</option>`)].join("");
  $("#fixme-body").innerHTML = state.fixmes.map((entry) => `
    <tr>
      <td>${escapeHtml(entry.case_folder_name)}</td>
      <td><span class="cell-stack"><strong title="${escapeHtml(entry.workbook_path)}">${escapeHtml(entry.workbook_name)}</strong><small>${escapeHtml(entry.sheet_name)} · ${escapeHtml(entry.fixme_cell)}</small></span></td>
      <td>${escapeHtml(entry.column_name)}</td>
      <td><span class="diff-value">${escapeHtml(entry.left_value)}</span></td>
      <td><span class="diff-value">${escapeHtml(entry.right_value)}</span></td>
      <td>${escapeHtml(entry.record_number)}</td>
      <td><select data-fixme-index="${entry.index}">${options}</select></td>
    </tr>`).join("");
}

function refreshFixmeNoteOptions() {
  $$('select[data-fixme-index]').forEach((select) => {
    const currentValue = select.value;
    select.replaceChildren(new Option("Chọn ghi chú", ""));
    state.notes.forEach((note) => select.add(new Option(note.value, note.value)));
    if (state.notes.some((note) => note.value === currentValue)) select.value = currentValue;
  });
}

function renderNotes() {
  const list = $("#note-list");
  list.innerHTML = `<button class="note-item" data-note-new><strong>＋ Ghi chú mới</strong><small>Thêm lựa chọn cho bảng FIXME</small></button>` +
    state.notes.map((note) => `<button class="note-item" data-note-value="${escapeHtml(note.value)}"><strong>${escapeHtml(note.value)}</strong><small>${escapeHtml(note.meaning || "Chưa có mô tả")}</small></button>`).join("");
  $("[data-note-new]", list).addEventListener("click", clearNoteForm);
  $$('[data-note-value]', list).forEach((button) => button.addEventListener("click", () => {
    const note = state.notes.find((item) => item.value === button.dataset.noteValue);
    if (!note) return;
    $$(".note-item", list).forEach((item) => item.classList.toggle("active", item === button));
    $("#note-old-value").value = note.value;
    $("#note-value").value = note.value;
    $("#note-meaning").value = note.meaning;
    $("#delete-note").disabled = false;
  }));
  $("#delete-note").disabled = !valueOf("note-old-value");
}

function clearNoteForm() {
  $("#note-old-value").value = "";
  $("#note-value").value = "";
  $("#note-meaning").value = "";
  $("#delete-note").disabled = true;
  $$(".note-item").forEach((item) => item.classList.remove("active"));
  $("#note-value").focus();
}

function renderTables() {
  const filter = valueOf("sync-table-filter").toLocaleLowerCase("vi");
  const allMode = checked("sync-all-tables");
  const available = state.sourceTables.filter((name) => !state.selectedTables.includes(name) && name.toLocaleLowerCase("vi").includes(filter));
  const availableContainer = $("#available-tables");
  const selectedContainer = $("#selected-tables");
  $("#sync-table-filter").disabled = allMode || !state.sourceTables.length;
  if (allMode) {
    availableContainer.innerHTML = `<p>Đang chọn toàn bộ ${state.sourceTables.length} table nguồn.</p>`;
  } else if (!available.length) {
    availableContainer.innerHTML = `<p>${state.sourceTables.length ? "Không còn table phù hợp." : "Test kết nối nguồn để tải danh sách table."}</p>`;
  } else {
    availableContainer.innerHTML = available.map((name) => `<button class="table-option" type="button" data-add-table="${escapeHtml(name)}"><span>${escapeHtml(name)}</span><b>＋</b></button>`).join("");
    $$('[data-add-table]', availableContainer).forEach((button) => button.addEventListener("click", () => {
      state.selectedTables.push(button.dataset.addTable);
      renderTables();
    }));
  }
  if (!state.selectedTables.length) {
    selectedContainer.innerHTML = `<p>Chưa chọn table.</p>`;
  } else {
    selectedContainer.innerHTML = state.selectedTables.map((name) => `<div class="table-tag"><span>${escapeHtml(name)}</span><button type="button" data-remove-table="${escapeHtml(name)}">×</button></div>`).join("");
    $$('[data-remove-table]', selectedContainer).forEach((button) => button.addEventListener("click", () => {
      state.selectedTables = state.selectedTables.filter((name) => name !== button.dataset.removeTable);
      renderTables();
    }));
  }
  const count = allMode ? state.sourceTables.length : state.selectedTables.length;
  $("#selected-table-count").textContent = `${count} table`;
}

async function startAction(action, payload) {
  if (state.job && ["queued", "running"].includes(state.job.state)) {
    showToast("Một tác vụ khác đang chạy. Vui lòng chờ hoàn tất.", "error");
    return;
  }
  try {
    const response = await api("/api/actions", { method: "POST", body: { action, ...payload } });
    state.job = response.job;
    state.jobCursor = 0;
    setJobVisual("running", state.job.label);
    $("#activity-subtitle").textContent = state.job.label;
    $("#activity-log").textContent = "";
    setBusy(true);
    schedulePoll(100);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function schedulePoll(delay = 500) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(pollJob, delay);
}

async function pollJob() {
  try {
    const response = await api(`/api/jobs/current?cursor=${state.jobCursor}`);
    if (!response.job) return;
    state.job = response.job;
    state.jobCursor = response.job.next_cursor;
    if (response.job.logs.length) appendLogs(response.job.logs);
    updateJobState(response.job);
    if (["queued", "running"].includes(response.job.state)) schedulePoll();
  } catch (error) {
    showToast(error.message, "error");
    schedulePoll(1500);
  }
}

function updateJobState(job) {
  if (["queued", "running"].includes(job.state)) {
    setBusy(true);
    setJobVisual("running", job.status || job.label);
    return;
  }
  setBusy(false);
  if (state.handledJobs.has(job.id)) {
    setJobVisual(job.state === "succeeded" ? "success" : "error", job.state === "succeeded" ? "Hoàn tất" : "Thất bại");
    return;
  }
  state.handledJobs.add(job.id);
  if (job.state === "failed") {
    setJobVisual("error", "Tác vụ thất bại");
    $("#activity-panel").classList.remove("collapsed");
    showToast(job.error || "Tác vụ thất bại.", "error", 7000);
    return;
  }
  setJobVisual("success", "Hoàn tất");
  consumeJobResult(job);
  showToast(summaryMessage(job), "success", 5500);
}

function consumeJobResult(job) {
  const result = job.result || {};
  if (Array.isArray(result.fixmes)) {
    state.fixmes = result.fixmes;
    renderFixmes();
  }
  if (job.action === "db_test" && result.verified) {
    setVerified(result.role, true);
    if (result.role === "source" && Array.isArray(result.tables)) {
      state.sourceTables = result.tables;
      state.selectedTables = [];
      renderTables();
    }
  }
  if (job.action === "db_list_databases" && Array.isArray(result.databases)) {
    state.databaseNames[result.role] = result.databases;
    const list = $(`#db-${result.role}-database-list`);
    list.innerHTML = result.databases.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
    if (!valueOf(`db-${result.role}-database`) && result.databases.length) $(`#db-${result.role}-database`).value = result.databases[0];
  }
}

function summaryMessage(job) {
  const result = job.result || {};
  if (job.action === "compare") return `Đã xử lý ${result.processed_count || 0} case, tạo ${result.workbook_count || 0} workbook và tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "folder_compare") return `Đã tạo ${result.sheet_count || 0} sheet, tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "db_test") return "Kết nối cơ sở dữ liệu thành công.";
  if (job.action === "db_list_databases") return `Đã tải ${result.databases?.length || 0} cơ sở dữ liệu.`;
  if (job.action === "db_sync") {
    const retained = result.retained_target_only_count
      ? `, giữ lại ${result.retained_target_only_count} record chỉ có ở đích`
      : "";
    return `Đã đồng bộ ${result.table_count || 0} table: insert ${result.inserted_count || 0}, update ${result.updated_count || 0}, delete ${result.deleted_count || 0}, không đổi ${result.unchanged_count || 0}${retained}.`;
  }
  if (typeof result.changed_count === "number") return `${result.action_name || "Tác vụ"}: đã thay đổi ${result.changed_count}, bỏ qua ${result.skipped_count || 0}.`;
  if (typeof result.csv_count === "number") return `${result.action_name || "Tác vụ CSDL"}: ${result.csv_count} CSV / ${result.row_count || 0} dòng.`;
  if (job.action === "apply_fixmes") return `Đã cập nhật ${result.cell_count || 0} ô trong ${result.workbook_count || 0} workbook.`;
  return "Tác vụ đã hoàn tất.";
}

function setJobVisual(kind, text) {
  const pill = $("#job-status-button");
  const panel = $("#activity-panel");
  pill.className = `status-pill ${kind}`;
  panel.classList.remove("running", "success", "error");
  if (kind !== "idle") panel.classList.add(kind);
  $("#job-status-text").textContent = text;
  $("#activity-title").textContent = text;
  $("#activity-subtitle").textContent = kind === "idle" ? "Chưa có hoạt động" : text;
}

function setBusy(busy) {
  document.body.classList.toggle("is-busy", busy);
  $$('button[type="submit"], #db-normalize, #db-import, #db-export, #find-empty, #delete-empty, [data-db-test], [data-db-load], #apply-fixmes').forEach((button) => {
    button.disabled = busy;
  });
}

function appendLogs(lines) {
  const log = $("#activity-log");
  const prefix = log.textContent && !log.textContent.endsWith("\n") ? "\n" : "";
  log.textContent += prefix + lines.join("\n") + "\n";
  log.scrollTop = log.scrollHeight;
}

async function openPathPicker(button) {
  const target = button.dataset.browseTarget;
  const kind = button.dataset.browseKind || "directory";
  const extensions = (button.dataset.browseExt || "").split(",").filter(Boolean);
  const rawValue = valueOf(target);
  let initialPath = rawValue || state.bootstrap.cwd;
  let fileName = "";
  if (kind === "save" && rawValue) {
    fileName = baseName(rawValue);
    initialPath = parentPath(rawValue) || state.bootstrap.cwd;
  } else if (kind === "file" && rawValue) {
    initialPath = parentPath(rawValue) || state.bootstrap.cwd;
  }
  state.picker = { target, kind, extensions, selected: null, parent: null, current: initialPath };
  $("#path-dialog-title").textContent = kind === "directory" ? "Chọn folder" : kind === "file" ? "Chọn file" : "Chọn nơi lưu file";
  $("#save-name-field").classList.toggle("hidden", kind !== "save");
  $("#save-file-name").value = fileName || (kind === "save" ? state.bootstrap.folder_compare_file : "");
  $("#path-dialog").showModal();
  await loadPickerPath(initialPath);
}

async function loadPickerPath(path) {
  if (!state.picker) return;
  try {
    const kind = state.picker.kind === "directory" ? "directory" : "file";
    const params = new URLSearchParams({ path, kind });
    state.picker.extensions.forEach((ext) => params.append("ext", ext));
    const response = await api(`/api/fs?${params}`);
    state.picker.current = response.path;
    state.picker.parent = response.parent;
    state.picker.selected = null;
    $("#path-current").value = response.path;
    $("#path-up").disabled = !response.parent;
    $("#path-root-select").innerHTML = response.roots.map((root) => `<option value="${escapeHtml(root)}" ${response.path.toLocaleLowerCase().startsWith(root.toLocaleLowerCase()) ? "selected" : ""}>${escapeHtml(root)}</option>`).join("");
    renderPathEntries(response.entries);
    updatePickerHint();
  } catch (error) { showToast(error.message, "error"); }
}

function renderPathEntries(entries) {
  const list = $("#path-list");
  if (!entries.length) {
    list.innerHTML = `<div class="empty-state"><strong>Folder trống</strong><p>Không có mục phù hợp với bộ lọc.</p></div>`;
    return;
  }
  list.innerHTML = entries.map((entry, index) => `<button type="button" class="path-entry" data-path-index="${index}"><i>${entry.is_dir ? "▰" : "▤"}</i><span>${escapeHtml(entry.name)}</span><small>${entry.is_dir ? "Folder" : "File"}</small></button>`).join("");
  $$('[data-path-index]', list).forEach((button) => {
    const entry = entries[Number(button.dataset.pathIndex)];
    button.addEventListener("click", () => {
      state.picker.selected = entry;
      $$(".path-entry", list).forEach((item) => item.classList.toggle("selected", item === button));
      updatePickerHint();
    });
    button.addEventListener("dblclick", () => {
      if (entry.is_dir) loadPickerPath(entry.path);
      else { state.picker.selected = entry; confirmPathPicker(); }
    });
  });
}

function updatePickerHint() {
  if (!state.picker) return;
  const selected = state.picker.selected;
  $("#path-selection-hint").textContent = selected ? selected.path : state.picker.current;
}

function confirmPathPicker() {
  if (!state.picker) return;
  const { kind, target, selected, current } = state.picker;
  let chosen = "";
  if (kind === "directory") {
    chosen = selected?.is_dir ? selected.path : current;
  } else if (kind === "file") {
    if (!selected || selected.is_dir) { showToast("Vui lòng chọn một file.", "error"); return; }
    chosen = selected.path;
  } else {
    const fileName = valueOf("save-file-name");
    if (!fileName) { showToast("Vui lòng nhập tên file.", "error"); return; }
    if (/[\\/]/.test(fileName)) { showToast("Tên file không được chứa dấu \\ hoặc /.", "error"); return; }
    const folder = selected?.is_dir ? selected.path : current;
    chosen = joinPath(folder, ensureExtension(fileName, state.picker.extensions[0] || "xlsx"));
  }
  $(`#${target}`).value = chosen;
  $(`#${target}`).dispatchEvent(new Event("change", { bubbles: true }));
  $("#path-dialog").close();
  state.picker = null;
}

function confirmAction(title, message) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  let payload;
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function showToast(message, kind = "info", duration = 4000) {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  $("#toast-stack").appendChild(toast);
  window.setTimeout(() => toast.remove(), duration);
}

function valueOf(id) { return $(`#${id}`)?.value?.trim() || ""; }
function checked(id) { return Boolean($(`#${id}`)?.checked); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}
function joinPath(parent, child) {
  const separator = parent.includes("\\") ? "\\" : "/";
  return `${parent.replace(/[\\/]$/, "")}${separator}${child.replace(/^[\\/]/, "")}`;
}
function baseName(path) { return path.split(/[\\/]/).filter(Boolean).pop() || ""; }
function parentPath(path) {
  const trimmed = path.replace(/[\\/]$/, "");
  const index = Math.max(trimmed.lastIndexOf("\\"), trimmed.lastIndexOf("/"));
  if (index < 0) return "";
  if (index === 2 && /^[A-Za-z]:/.test(trimmed)) return trimmed.slice(0, 3);
  return trimmed.slice(0, index) || "/";
}
function ensureExtension(fileName, extension) {
  const normalized = extension.startsWith(".") ? extension : `.${extension}`;
  return fileName.toLocaleLowerCase().endsWith(normalized.toLocaleLowerCase()) ? fileName : `${fileName}${normalized}`;
}
