"use strict";

const state = {
  bootstrap: null,
  notes: [],
  excelFormatPresets: [],
  fixmes: [],
  fixmeFilters: {},
  fixmeSelections: {},
  fixmeCheckedRows: new Set(),
  fixmeSort: { field: "", direction: "asc" },
  job: null,
  jobCursor: 0,
  handledJobs: new Set(),
  pollTimer: null,
  dbVerified: { main: false, source: false, target: false },
  databaseNames: { main: [], source: [], target: [] },
  sourceTables: [],
  selectedTables: [],
  sqlWorkspace: {
    workspaceId: "",
    writeToken: "",
    writeExpiresAt: "",
    stale: false,
    exportable: false,
    dirty: {},
    rowTokens: {},
  },
  picker: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", init);

async function init() {
  prepareDatabaseWorkspaceLayout();
  bindNavigation();
  bindMobileMenu();
  bindTabs();
  bindActivityPanel();
  bindForms();
  bindDialogs();
  try {
    state.bootstrap = await api("/api/bootstrap");
    state.notes = state.bootstrap.notes || [];
    state.excelFormatPresets = state.bootstrap.excel_format_presets || [];
    state.fixmes = state.bootstrap.fixmes || [];
    hydrateDefaults();
    renderWorkflows();
    renderConnectionForms();
    renderNotes();
    refreshFixmeNoteOptions();
    renderExcelFormatPresets();
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

function prepareDatabaseWorkspaceLayout() {
  const sqlNav = $('.nav-item[data-page="sql-studio"]');
  if (sqlNav) sqlNav.remove();

  const databasePage = $("#page-database");
  const tabs = $(".database-tabs", databasePage);
  if (!databasePage || !tabs || $("#db-connection-hub")) return;

  const sqlTab = document.createElement("button");
  sqlTab.className = "tab";
  sqlTab.dataset.tabGroup = "database";
  sqlTab.dataset.tab = "sql-workspace";
  sqlTab.type = "button";
  sqlTab.textContent = "SQL Workspace";
  const syncTab = $('.tab[data-tab-group="database"][data-tab="sync"]', tabs);
  tabs.insertBefore(sqlTab, syncTab || null);

  const intro = $(".page-intro", databasePage);
  if (intro) {
    const hub = document.createElement("div");
    hub.className = "db-connection-hub";
    hub.id = "db-connection-hub";
    hub.innerHTML = `
      <div class="db-connection-chip" data-db-chip="main">
        <span class="source-target source">1</span>
        <span><strong>Database 1</strong><small data-verified-state="main">Chưa kiểm tra</small></span>
      </div>
      <div class="db-connection-chip" data-db-chip="target">
        <span class="source-target target">2</span>
        <span><strong>Database 2</strong><small data-verified-state="target">Chưa kiểm tra</small></span>
      </div>
      <button class="secondary-button small" id="db-open-connections" type="button">Kết nối CSDL</button>`;
    intro.appendChild(hub);
  }

  const dialog = document.createElement("dialog");
  dialog.className = "modal db-connection-modal";
  dialog.id = "db-connection-dialog";
  dialog.innerHTML = `
    <div class="modal-shell">
      <header>
        <div><span class="section-kicker">Database connection</span><h3>Kết nối dùng chung</h3><p>Database 1 dùng cho CSV, SQL Workspace và nguồn đồng bộ. Database 2 chỉ dùng làm đích khi đồng bộ.</p></div>
        <button class="icon-button" id="db-close-connections" type="button" aria-label="Đóng">×</button>
      </header>
      <div class="db-connection-dialog-body">
        <form class="card connection-card db-dialog-card" data-db-scope="main">
          <div class="card-heading"><div><span class="source-target source">1</span><h3>Database 1</h3></div><span class="connection-state" data-verified-state="main">Chưa kiểm tra</span></div>
          <div class="connection-fields"></div>
          <div class="two-buttons"><button class="ghost-button" data-db-load="main" type="button">Tải CSDL</button><button class="secondary-button" data-db-test="main" type="button">Test & tải table</button></div>
        </form>
        <form class="card connection-card db-dialog-card" data-db-scope="target">
          <div class="card-heading"><div><span class="source-target target">2</span><h3>Database 2</h3></div><span class="connection-state" data-verified-state="target">Chưa kiểm tra</span></div>
          <div class="connection-fields"></div>
          <div class="two-buttons"><button class="ghost-button" data-db-load="target" type="button">Tải CSDL</button><button class="secondary-button" data-db-test="target" type="button">Test kết nối</button></div>
        </form>
      </div>
    </div>`;
  databasePage.appendChild(dialog);

  $("#db-main-form")?.remove();
  $(".database-layout", databasePage)?.classList.add("database-layout-full");
  $(".sync-connections")?.remove();

  const sqlPage = $("#page-sql-studio");
  if (sqlPage) {
    const sqlPanel = document.createElement("div");
    sqlPanel.className = "tab-panel";
    sqlPanel.dataset.tabPanel = "database:sql-workspace";
    while (sqlPage.firstChild) sqlPanel.appendChild(sqlPage.firstChild);
    const syncPanel = $('[data-tab-panel="database:sync"]', databasePage);
    databasePage.insertBefore(sqlPanel, syncPanel || null);
    sqlPage.remove();
    enhanceSqlWorkspacePanel(sqlPanel);
  }
}

function enhanceSqlWorkspacePanel(panel) {
  const toolbarText = $(".sql-editor-toolbar small", panel);
  if (toolbarText) toolbarText.textContent = "Format/Analyze dùng parser; Run dùng Database 1 đã kết nối";
  const actions = $(".sql-editor-actions > div", panel);
  if (actions && !$("#sql-run-current")) {
    actions.insertAdjacentHTML("beforeend", `
      <button class="secondary-button" id="sql-run-current" type="button">Run current</button>
      <button class="secondary-button" id="sql-run-all" type="button">Run all</button>
      <button class="ghost-button" id="sql-write-mode" type="button">Write mode OFF</button>`);
  }
  panel.insertAdjacentHTML("beforeend", `
    <section class="card sql-workspace-export">
      <div class="card-heading"><div><span class="step-number">03</span><h3>Export source data</h3></div><button class="secondary-button small" id="sql-export-all" type="button" disabled>Export All</button></div>
      <label class="field field-wide"><span>Output folder</span><span class="path-control"><input id="sql-export-folder"><button class="browse-button" type="button" data-browse-target="sql-export-folder" data-browse-kind="directory">Chọn</button></span></label>
    </section>
    <section class="sql-workspace-output hidden" id="sql-workspace-output">
      <div class="sql-analysis-heading"><div><span class="section-kicker">Database workspace</span><h3>Query Results & Source Data</h3></div><span class="soft-badge" id="sql-workspace-state">STALE</span></div>
      <div class="sql-db-grid">
        <section class="card sql-db-panel"><div class="card-heading"><div><span class="sql-result-icon">R</span><h3>Query Results</h3></div></div><div id="sql-query-results" class="sql-db-stack"></div></section>
        <section class="card sql-db-panel"><div class="card-heading"><div><span class="sql-result-icon table-icon">S</span><h3>Sources</h3></div></div><div id="sql-source-list" class="sql-db-stack"></div></section>
      </div>
      <section class="card sql-db-panel sql-source-data-panel"><div class="card-heading"><div><span class="sql-result-icon condition-icon">D</span><h3>Source Data</h3></div></div><div id="sql-source-data" class="sql-db-stack"></div></section>
    </section>`);
}

function bindTabs() {
  $$(".tab").forEach((button) => button.addEventListener("click", () => {
    const group = button.dataset.tabGroup;
    const tab = button.dataset.tab;
    $$(`.tab[data-tab-group="${group}"]`).forEach((item) => item.classList.toggle("active", item === button));
    $$(`[data-tab-panel^="${group}:"]`).forEach((panel) => panel.classList.toggle("active", panel.dataset.tabPanel === `${group}:${tab}`));
    syncDatabaseCommonLayout(group, tab);
  }));
  syncDatabaseCommonLayout("database", "csv");
}

function syncDatabaseCommonLayout(group, tab) {
  if (group !== "database") return;
  $("#db-connection-hub")?.classList.toggle("sync-mode", tab === "sync");
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
  $("#excel-format-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const root = valueOf("excel-format-root");
    const overwriteOriginal = $('input[name="excel-output-mode"]:checked')?.value === "overwrite";
    const fontName = valueOf("excel-format-font-name");
    const fontSize = valueOf("excel-format-font-size");
    const exclusions = valueOf("excel-format-exclusions");
    const ruleCount = exclusions.split(/\r?\n/).filter((item) => item.trim()).length;
    const title = overwriteOriginal ? "Ghi đè các workbook gốc?" : "Format các workbook?";
    const message = overwriteOriginal
      ? `CẢNH BÁO: Mọi workbook bên dưới “${root}” sẽ được format và lưu trực tiếp. Thao tác này không thể hoàn tác tự động.`
      : `Workbook sẽ được copy vào “${joinPath(root, "Formatted")}” rồi format. File kết quả cùng tên đã tồn tại có thể bị ghi đè.`;
    const imageDetails = checked("excel-format-run-image")
      ? "Có căn ảnh theo vùng Input/Steps/Output."
      : "Không căn ảnh, chỉ format font/view workbook.";
    const formatDetails = `\n\nFont: ${fontName}, size ${fontSize}; ${ruleCount} quy tắc giữ nguyên cỡ chữ. ${imageDetails} Mọi sheet sẽ trở về A1 và scroll về đầu.`;
    if (await confirmAction(title, message + formatDetails)) {
      startAction("format_excel_images", {
        root,
        recursive: checked("excel-format-recursive"),
        run_image_format: checked("excel-format-run-image"),
        font_name: fontName,
        font_size: fontSize,
        font_size_exclusions: exclusions,
        overwrite_original: overwriteOriginal,
        confirmed: true,
      });
    }
  });
  $("#excel-format-preset").addEventListener("change", applySelectedExcelFormatPreset);
  $("#save-excel-format-preset").addEventListener("click", saveExcelFormatPreset);
  $("#delete-excel-format-preset").addEventListener("click", deleteExcelFormatPreset);
  $("#sql-studio-form").addEventListener("submit", (event) => {
    event.preventDefault();
    runSqlAction("sql_analyze");
  });
  $("#sql-format").addEventListener("click", () => runSqlAction("sql_format"));
  $("#sql-analyze").addEventListener("click", () => runSqlAction("sql_analyze"));
  $("#sql-load-excel").addEventListener("click", runSqlExcelLoad);
  $("#copy-formatted-sql").addEventListener("click", copyFormattedSql);
  $("#sql-run-current")?.addEventListener("click", () => runSqlExecute("current"));
  $("#sql-run-all")?.addEventListener("click", () => runSqlExecute("all"));
  $("#sql-write-mode")?.addEventListener("click", toggleSqlWriteMode);
  $("#sql-export-all")?.addEventListener("click", () => exportSqlSources());

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
    if (!requireVerified("main") || !requireVerified("target")) return;
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
        source_settings: getDbSettings("main"), target_settings: getDbSettings("target"), table_names: tableNames,
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
  $$("[data-fixme-filter]").forEach((control) => control.addEventListener("input", updateFixmeFilter));
  $$("[data-fixme-filter]").forEach((control) => control.addEventListener("change", updateFixmeFilter));
  $$("[data-fixme-sort]").forEach((button) => button.addEventListener("click", () => updateFixmeSort(button.dataset.fixmeSort)));
  $("#fixme-bulk-note").addEventListener("change", updateFixmeToolbarState);
  $("#fixme-bulk-scope").addEventListener("change", updateFixmeToolbarState);
  $("#fixme-select-filtered").addEventListener("click", selectFilteredFixmeRows);
  $("#fixme-clear-selection").addEventListener("click", clearFixmeRowSelection);
  $("#fixme-bulk-assign").addEventListener("click", assignBulkFixmeNote);
  $("#fixme-bulk-clear").addEventListener("click", clearBulkFixmeNotes);
  $("#fixme-clear-filters").addEventListener("click", clearFixmeFilters);
  $("#fixme-check-visible").addEventListener("change", toggleVisibleFixmeRows);
  $("#apply-fixmes").addEventListener("click", () => {
    const selections = Object.fromEntries(Object.entries(state.fixmeSelections).filter(([, value]) => value));
    if (!Object.keys(selections).length) {
      showToast("Vui lòng gán ít nhất một note cho dòng FIXME.", "error");
      return;
    }
    startAction("apply_fixmes", { selections });
  });

  $$('[data-browse-target]').forEach((button) => button.addEventListener("click", () => openPathPicker(button)));
}

function bindDialogs() {
  const dbDialog = $("#db-connection-dialog");
  $("#db-open-connections")?.addEventListener("click", () => dbDialog?.showModal());
  $("#db-close-connections")?.addEventListener("click", () => dbDialog?.close());
  dbDialog?.addEventListener("click", (event) => {
    if (event.target === dbDialog) dbDialog.close();
  });

  $("#manage-notes").addEventListener("click", () => { renderNotes(); $("#notes-dialog").showModal(); });
  $("#close-notes").addEventListener("click", () => $("#notes-dialog").close());
  $("#note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const response = await api("/api/notes/save", {
        method: "POST",
        body: { old_value: valueOf("note-old-value"), value: valueOf("note-value"), meaning: valueOf("note-meaning") },
      });
      const oldValue = valueOf("note-old-value");
      const newValue = valueOf("note-value");
      state.notes = response.notes;
      renameFixmeSelectionNote(oldValue, newValue);
      pruneFixmeSelectionsToNotes();
      clearNoteForm();
      renderNotes();
      refreshFixmeNoteOptions();
      renderFixmes();
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
      pruneFixmeSelectionsToNotes();
      clearNoteForm();
      renderNotes();
      refreshFixmeNoteOptions();
      renderFixmes();
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
  $("#excel-format-root").value = cwd;
  $("#db-csv-path").value = cwd;
  $("#sql-export-folder").value = cwd;
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

    $$(`input, select`, form).forEach((input) => input.addEventListener("input", () => invalidateDbConnection(scope)));
    $$(`input, select`, form).forEach((input) => input.addEventListener("change", () => {
      if (input.id === `db-${scope}-type`) applyDatabaseType(scope, true);
      if (input.id === `db-${scope}-trusted`) syncAuthFields(scope);
      invalidateDbConnection(scope);
    }));
    $(`#db-${scope}-trusted`).addEventListener("change", () => syncAuthFields(scope));
    applyDatabaseType(scope, false);
    syncAuthFields(scope);
  });

  $$('[data-db-test]').forEach((button) => button.addEventListener("click", () => {
    const scope = button.dataset.dbTest;
    startAction("db_test", { settings: getDbSettings(scope), role: scope, load_tables: scope === "main" });
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
  $$(`[data-verified-state="${scope}"]`).forEach((indicator) => {
    indicator.textContent = verified ? "Đã kết nối" : "Chưa kiểm tra";
    indicator.classList.toggle("verified", verified);
  });
  $$(`[data-db-chip="${scope}"]`).forEach((chip) => chip.classList.toggle("verified", verified));
  if (scope === "main" && !verified) {
    state.sourceTables = [];
    state.selectedTables = [];
    renderTables();
  }
}

function invalidateDbConnection(scope) {
  setVerified(scope, false);
  if (scope === "main" || scope === "target") {
    if (state.sqlWorkspace.writeToken) {
      api("/api/sql-workspace/write-mode/disable", {
        method: "POST",
        body: { write_token: state.sqlWorkspace.writeToken },
      }).catch(() => {});
    }
    disableSqlWriteModeLocal();
    markSqlWorkspaceStale();
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
  $("#fixme-tools").classList.toggle("hidden", state.fixmes.length === 0);
  const filteredEntries = sortedFixmes(filteredFixmes());
  updateFixmeSortHeaders();
  $("#fixme-body").innerHTML = filteredEntries.length ? filteredEntries.map((entry) => `
    <tr>
      <td class="select-column"><input class="fixme-row-check" type="checkbox" data-fixme-check-index="${entry.index}" ${state.fixmeCheckedRows.has(String(entry.index)) ? "checked" : ""}></td>
      <td>${escapeHtml(entry.case_folder_name)}</td>
      <td>${fixmeWorkbookHtml(entry)}</td>
      <td>${escapeHtml(fixmeCsvSheetName(entry))}</td>
      <td>${escapeHtml(entry.column_name)}</td>
      <td><span class="diff-value">${escapeHtml(entry.left_value)}</span></td>
      <td><span class="diff-value">${escapeHtml(entry.right_value)}</span></td>
      <td>${escapeHtml(entry.record_number)}</td>
      <td><select data-fixme-index="${entry.index}">${fixmeNoteOptionsHtml("Chọn ghi chú", state.fixmeSelections[entry.index])}</select></td>
    </tr>`).join("") : `<tr class="fixme-empty-row"><td colspan="9">Không có dòng phù hợp với filter hiện tại.</td></tr>`;

  $$('select[data-fixme-index]').forEach((select) => {
    select.addEventListener("change", () => {
      if (select.value) state.fixmeSelections[select.dataset.fixmeIndex] = select.value;
      else delete state.fixmeSelections[select.dataset.fixmeIndex];
      if (state.fixmeSort.field === "note" || state.fixmeFilters.note) renderFixmes();
      else updateFixmeToolbarState(filteredEntries);
    });
  });
  $$("[data-fixme-check-index]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const index = checkbox.dataset.fixmeCheckIndex;
      if (checkbox.checked) state.fixmeCheckedRows.add(index);
      else state.fixmeCheckedRows.delete(index);
      updateFixmeToolbarState(filteredEntries);
    });
  });
  updateFixmeToolbarState(filteredEntries);
}

function refreshFixmeNoteOptions() {
  const bulkSelect = $("#fixme-bulk-note");
  const noteFilter = $("#fixme-filter-note");
  const previousBulkNote = bulkSelect.value;
  const previousNoteFilter = noteFilter.value;
  bulkSelect.innerHTML = fixmeNoteOptionsHtml("Chọn note");
  noteFilter.innerHTML = fixmeNoteOptionsHtml("Tất cả");
  if (state.notes.some((note) => note.value === previousBulkNote)) bulkSelect.value = previousBulkNote;
  if (state.notes.some((note) => note.value === previousNoteFilter)) noteFilter.value = previousNoteFilter;

  $$('select[data-fixme-index]').forEach((select) => {
    const currentValue = select.value;
    select.replaceChildren(new Option("Chọn ghi chú", ""));
    state.notes.forEach((note) => select.add(new Option(note.value, note.value)));
    if (state.notes.some((note) => note.value === currentValue)) select.value = currentValue;
  });
  updateFixmeToolbarState();
  updateSqlDirtyButtons();
  if ($("#sql-export-all") && !state.sqlWorkspace.exportable) $("#sql-export-all").disabled = true;
}

function fixmeNoteOptionsHtml(placeholder, selectedValue = "") {
  return [`<option value="">${escapeHtml(placeholder)}</option>`, ...state.notes.map((note) =>
    `<option value="${escapeHtml(note.value)}" ${note.value === selectedValue ? "selected" : ""}>${escapeHtml(note.value)}</option>`
  )].join("");
}

function fixmeWorkbookHtml(entry) {
  return `<span class="cell-stack"><strong>${escapeHtml(entry.workbook_name)}</strong></span>`;
}

function fixmeCsvSheetName(entry) {
  return String(entry.csv_file_name || "").replace(/\.csv$/i, "");
}

function filteredFixmes() {
  return state.fixmes.filter((entry) => Object.entries(state.fixmeFilters).every(([field, filterValue]) => {
    if (!filterValue) return true;
    return normalizedFixmeText(fixmeFieldValue(entry, field)).includes(normalizedFixmeText(filterValue));
  }));
}

function sortedFixmes(entries) {
  const field = state.fixmeSort.field;
  if (!field) return entries;
  const direction = state.fixmeSort.direction === "desc" ? -1 : 1;
  return entries
    .map((entry, order) => ({ entry, order }))
    .sort((left, right) => {
      const compared = compareFixmeSortValues(fixmeFieldValue(left.entry, field), fixmeFieldValue(right.entry, field), field);
      return compared ? compared * direction : left.order - right.order;
    })
    .map((item) => item.entry);
}

function compareFixmeSortValues(leftValue, rightValue, field) {
  const leftText = String(leftValue ?? "").trim();
  const rightText = String(rightValue ?? "").trim();
  if (field === "record_number") {
    const leftNumber = Number(leftText);
    const rightNumber = Number(rightText);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  }
  const leftNumber = parseSortableNumber(leftText);
  const rightNumber = parseSortableNumber(rightText);
  if (leftNumber !== null && rightNumber !== null) return leftNumber - rightNumber;
  return leftText.localeCompare(rightText, "vi", { numeric: true, sensitivity: "base" });
}

function parseSortableNumber(value) {
  const normalized = String(value ?? "").trim().replace(/,/g, "");
  if (!/^-?\d+(\.\d+)?$/.test(normalized)) return null;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

function fixmeFieldValue(entry, field) {
  if (field === "note") return state.fixmeSelections[entry.index] || "";
  if (field === "csv_sheet_name") return fixmeCsvSheetName(entry);
  return entry[field] ?? "";
}

function normalizedFixmeText(value) {
  return String(value ?? "").trim().toLocaleLowerCase("vi");
}

function updateFixmeFilter(event) {
  const field = event.target.dataset.fixmeFilter;
  if (!field) return;
  const value = event.target.value.trim();
  if (value) state.fixmeFilters[field] = value;
  else delete state.fixmeFilters[field];
  renderFixmes();
}

function updateFixmeSort(field) {
  if (!field) return;
  if (state.fixmeSort.field === field) {
    state.fixmeSort.direction = state.fixmeSort.direction === "asc" ? "desc" : "asc";
  } else {
    state.fixmeSort = { field, direction: "asc" };
  }
  renderFixmes();
}

function updateFixmeSortHeaders() {
  $$("[data-fixme-sort]").forEach((button) => {
    const active = button.dataset.fixmeSort === state.fixmeSort.field;
    const direction = active ? state.fixmeSort.direction : "";
    button.classList.toggle("active", active);
    button.classList.toggle("asc", direction === "asc");
    button.classList.toggle("desc", direction === "desc");
    button.setAttribute("aria-sort", active ? (direction === "desc" ? "descending" : "ascending") : "none");
    button.title = active ? `Đang sort ${direction === "desc" ? "giảm dần" : "tăng dần"}` : "Bấm để sort tăng dần";
  });
}

function clearFixmeFilters() {
  state.fixmeFilters = {};
  $$("[data-fixme-filter]").forEach((control) => { control.value = ""; });
  renderFixmes();
}

function selectFilteredFixmeRows() {
  filteredFixmes().forEach((entry) => state.fixmeCheckedRows.add(String(entry.index)));
  renderFixmes();
}

function clearFixmeRowSelection() {
  state.fixmeCheckedRows.clear();
  renderFixmes();
}

function toggleVisibleFixmeRows(event) {
  const visibleRows = filteredFixmes();
  visibleRows.forEach((entry) => {
    const index = String(entry.index);
    if (event.target.checked) state.fixmeCheckedRows.add(index);
    else state.fixmeCheckedRows.delete(index);
  });
  renderFixmes();
}

function assignBulkFixmeNote() {
  const note = valueOf("fixme-bulk-note");
  if (!note) {
    showToast("Vui lòng chọn note cần gán.", "error");
    $("#fixme-bulk-note").focus();
    return;
  }
  const targets = fixmeBulkTargets();
  if (!targets.length) {
    showToast("Không có dòng nào để gán note.", "error");
    return;
  }
  targets.forEach((entry) => { state.fixmeSelections[entry.index] = note; });
  renderFixmes();
  showToast(`Đã gán note cho ${targets.length} dòng FIXME.`, "success");
}

function clearBulkFixmeNotes() {
  const targets = fixmeBulkTargets();
  if (!targets.length) {
    showToast("Không có dòng nào để xóa note.", "error");
    return;
  }
  targets.forEach((entry) => { delete state.fixmeSelections[entry.index]; });
  renderFixmes();
  showToast(`Đã xóa note khỏi ${targets.length} dòng FIXME.`, "success");
}

function fixmeBulkTargets() {
  const filteredEntries = filteredFixmes();
  if (valueOf("fixme-bulk-scope") === "checked") {
    return filteredEntries.filter((entry) => state.fixmeCheckedRows.has(String(entry.index)));
  }
  return filteredEntries;
}

function updateFixmeToolbarState(filteredEntries = filteredFixmes()) {
  const checkVisible = $("#fixme-check-visible");
  if (!checkVisible) return;
  const visibleCount = filteredEntries.length;
  const noteCount = Object.values(state.fixmeSelections).filter(Boolean).length;
  const checkedVisibleCount = filteredEntries.filter((entry) => state.fixmeCheckedRows.has(String(entry.index))).length;
  $("#fixme-visible-count").textContent = `${visibleCount} / ${state.fixmes.length} dòng`;
  $("#fixme-note-count").textContent = `${noteCount} dòng đã gán note · ${state.fixmeCheckedRows.size} dòng đã tick`;
  checkVisible.checked = visibleCount > 0 && checkedVisibleCount === visibleCount;
  checkVisible.indeterminate = checkedVisibleCount > 0 && checkedVisibleCount < visibleCount;

  const busy = document.body.classList.contains("is-busy");
  const scopedTargets = valueOf("fixme-bulk-scope") === "checked" ? checkedVisibleCount : visibleCount;
  $("#fixme-select-filtered").disabled = busy || visibleCount === 0;
  $("#fixme-clear-selection").disabled = busy || state.fixmeCheckedRows.size === 0;
  $("#fixme-bulk-assign").disabled = busy || scopedTargets === 0 || !valueOf("fixme-bulk-note");
  $("#fixme-bulk-clear").disabled = busy || scopedTargets === 0;
  $("#apply-fixmes").disabled = busy || noteCount === 0;
}

function resetFixmeReviewState() {
  state.fixmeFilters = {};
  state.fixmeSelections = {};
  state.fixmeCheckedRows = new Set();
  $$("[data-fixme-filter]").forEach((control) => { control.value = ""; });
}

function renameFixmeSelectionNote(oldValue, newValue) {
  if (!oldValue || !newValue || oldValue === newValue) return;
  Object.keys(state.fixmeSelections).forEach((index) => {
    if (state.fixmeSelections[index] === oldValue) state.fixmeSelections[index] = newValue;
  });
}

function pruneFixmeSelectionsToNotes() {
  const knownNotes = new Set(state.notes.map((note) => note.value));
  Object.keys(state.fixmeSelections).forEach((index) => {
    if (!knownNotes.has(state.fixmeSelections[index])) delete state.fixmeSelections[index];
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

function renderExcelFormatPresets(selectedName = "") {
  const select = $("#excel-format-preset");
  select.innerHTML = `<option value="">— Chọn preset —</option>` + state.excelFormatPresets.map((preset) =>
    `<option value="${escapeHtml(preset.name)}">${escapeHtml(preset.name)}</option>`
  ).join("");
  if (selectedName && state.excelFormatPresets.some((item) => item.name === selectedName)) {
    select.value = selectedName;
  }
  $("#delete-excel-format-preset").disabled = !select.value;
}

function applySelectedExcelFormatPreset() {
  const name = valueOf("excel-format-preset");
  const preset = state.excelFormatPresets.find((item) => item.name === name);
  $("#delete-excel-format-preset").disabled = !preset;
  if (!preset) return;
  $("#excel-format-preset-name").value = preset.name;
  $("#excel-format-font-name").value = preset.font_name;
  $("#excel-format-font-size").value = String(preset.font_size);
  $("#excel-format-exclusions").value = Array.isArray(preset.exclusions) ? preset.exclusions.join("\n") : "";
}

async function saveExcelFormatPreset() {
  const name = valueOf("excel-format-preset-name");
  if (!name) {
    showToast("Vui lòng nhập tên preset.", "error");
    $("#excel-format-preset-name").focus();
    return;
  }
  try {
    const response = await api("/api/excel-format-presets/save", {
      method: "POST",
      body: {
        name,
        font_name: valueOf("excel-format-font-name"),
        font_size: valueOf("excel-format-font-size"),
        exclusions: valueOf("excel-format-exclusions"),
      },
    });
    state.excelFormatPresets = response.presets || [];
    renderExcelFormatPresets(name);
    applySelectedExcelFormatPreset();
    showToast("Đã lưu preset format Excel.", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteExcelFormatPreset() {
  const name = valueOf("excel-format-preset");
  if (!name) return;
  if (!await confirmAction("Xóa preset format Excel?", `Preset “${name}” sẽ bị xóa khỏi bộ nhớ.`)) return;
  try {
    const response = await api("/api/excel-format-presets/delete", {
      method: "POST",
      body: { name },
    });
    state.excelFormatPresets = response.presets || [];
    renderExcelFormatPresets();
    $("#excel-format-preset-name").value = "";
    showToast("Đã xóa preset.", "success");
  } catch (error) {
    showToast(error.message, "error");
  }
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
    resetFixmeReviewState();
    renderFixmes();
  }
  if (job.action === "db_test" && result.verified) {
    setVerified(result.role, true);
    if (result.role === "main" && Array.isArray(result.tables)) {
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
  if (job.action === "sql_format" || job.action === "sql_analyze" || job.action === "sql_load_excel") {
    if (job.action === "sql_load_excel" && result.source_sql) {
      $("#sql-input").value = result.source_sql;
      markSqlWorkspaceStale();
    }
    $("#sql-formatted-output").value = result.formatted_sql || "";
    $("#sql-statement-count").textContent = `${result.statement_count || 0} statement`;
    $("#sql-output-card").classList.remove("hidden");
    if (job.action === "sql_analyze") renderSqlAnalysis(result);
    else $("#sql-analysis").classList.add("hidden");
  }
  if (job.action === "db_sql_execute") {
    renderSqlWorkspace(result);
    if (result.analysis) renderSqlAnalysis(result.analysis);
  }
  if (job.action === "db_sql_update") {
    state.sqlWorkspace.dirty = {};
    markSqlWorkspaceStale();
  }
}

function runSqlAction(action) {
  const sql = valueOf("sql-input");
  if (!sql) {
    showToast("Vui lòng nhập câu SQL cần xử lý.", "error");
    $("#sql-input").focus();
    return;
  }
  startAction(action, { sql, dialect: valueOf("sql-dialect") });
}

function runSqlExcelLoad() {
  const excelPath = valueOf("sql-excel-path");
  const sheetName = valueOf("sql-excel-sheet");
  if (!excelPath) {
    showToast("Vui lòng chọn file Excel chứa SQL.", "error");
    $("#sql-excel-path").focus();
    return;
  }
  if (!sheetName) {
    showToast("Vui lòng nhập tên sheet cần đọc.", "error");
    $("#sql-excel-sheet").focus();
    return;
  }
  startAction("sql_load_excel", {
    excel_path: excelPath,
    sheet_name: sheetName,
    dialect: valueOf("sql-dialect"),
  });
}

function runSqlExecute(mode) {
  if (!requireVerified("main")) return;
  const editor = $("#sql-input");
  const sql = mode === "current" ? currentSqlSelection(editor) : valueOf("sql-input");
  if (!sql.trim()) {
    showToast("Vui lòng nhập hoặc chọn statement SQL cần chạy.", "error");
    editor.focus();
    return;
  }
  startAction("db_sql_execute", {
    sql,
    settings: getDbSettings("main"),
    run_mode: mode,
    write_token: state.sqlWorkspace.writeToken || "",
  });
}

async function toggleSqlWriteMode() {
  if (state.sqlWorkspace.writeToken) {
    try {
      await api("/api/sql-workspace/write-mode/disable", {
        method: "POST",
        body: { write_token: state.sqlWorkspace.writeToken },
      });
    } catch (_error) {
      // Local token is temporary; clearing it is enough when the server already dropped it.
    }
    disableSqlWriteModeLocal();
    showToast("Đã tắt Write mode.", "success");
    return;
  }
  if (!requireVerified("main")) return;
  const confirmed = await confirmAction(
    "Bật Write mode cho SQL editor?",
    "DDL/DML sẽ được phép chạy trong 30 phút cho Database 1 hiện tại. Batch Run all sẽ rollback nếu có lỗi khi database hỗ trợ transaction; một số DDL/MySQL/Oracle có thể implicit commit."
  );
  if (!confirmed) return;
  try {
    const result = await api("/api/sql-workspace/write-mode/enable", {
      method: "POST",
      body: { settings: getDbSettings("main") },
    });
    state.sqlWorkspace.writeToken = result.write_token || "";
    state.sqlWorkspace.writeExpiresAt = result.expires_at || "";
    updateSqlWriteModeButton();
    showToast("Write mode đã bật.", "success");
  } catch (error) {
    showToast(error.message, "error", 7000);
  }
}

function disableSqlWriteModeLocal() {
  state.sqlWorkspace.writeToken = "";
  state.sqlWorkspace.writeExpiresAt = "";
  updateSqlWriteModeButton();
}

function updateSqlWriteModeButton() {
  const button = $("#sql-write-mode");
  if (!button) return;
  const enabled = Boolean(state.sqlWorkspace.writeToken);
  button.classList.toggle("danger-button", enabled);
  button.classList.toggle("ghost-button", !enabled);
  button.textContent = enabled ? "Write mode ON" : "Write mode OFF";
}

function markSqlWorkspaceStale() {
  if (!state.sqlWorkspace.workspaceId) return;
  state.sqlWorkspace.stale = true;
  state.sqlWorkspace.exportable = false;
  const badge = $("#sql-workspace-state");
  if (badge) {
    badge.classList.add("stale");
    badge.textContent = "STALE";
  }
}

function currentSqlSelection(editor) {
  const start = editor.selectionStart || 0;
  const end = editor.selectionEnd || 0;
  if (end > start) return editor.value.slice(start, end);
  const ranges = splitSqlStatements(editor.value);
  const found = ranges.find((item) => start >= item.start && start <= item.end);
  return found ? editor.value.slice(found.start, found.end) : editor.value;
}

function splitSqlStatements(sql) {
  const ranges = [];
  let start = 0;
  let quote = "";
  let lineComment = false;
  let blockComment = false;
  for (let index = 0; index < sql.length; index += 1) {
    const char = sql[index];
    const next = sql[index + 1] || "";
    if (lineComment) {
      if (char === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (char === "*" && next === "/") { blockComment = false; index += 1; }
      continue;
    }
    if (quote) {
      if (char === quote) {
        if (next === quote) index += 1;
        else quote = "";
      }
      continue;
    }
    if (char === "-" && next === "-") { lineComment = true; index += 1; continue; }
    if (char === "/" && next === "*") { blockComment = true; index += 1; continue; }
    if (char === "'" || char === '"' || char === "`") { quote = char; continue; }
    if (char === ";") {
      if (sql.slice(start, index).trim()) ranges.push({ start, end: index });
      start = index + 1;
    }
  }
  if (sql.slice(start).trim()) ranges.push({ start, end: sql.length });
  return ranges;
}

async function copyFormattedSql() {
  const sql = $("#sql-formatted-output").value;
  if (!sql) return;
  try {
    await navigator.clipboard.writeText(sql);
  } catch (_error) {
    const output = $("#sql-formatted-output");
    output.focus();
    output.select();
    document.execCommand("copy");
  }
  showToast("Đã sao chép SQL đã format.", "success");
}

function renderSqlAnalysis(result) {
  const tables = Array.isArray(result.tables) ? result.tables : [];
  const conditions = Array.isArray(result.conditions) ? result.conditions : [];
  const ctes = Array.isArray(result.ctes) ? result.ctes : [];
  const subqueries = Array.isArray(result.subqueries) ? result.subqueries : [];
  const projections = Array.isArray(result.projections) ? result.projections : [];
  const clauses = Array.isArray(result.clauses) ? result.clauses : [];

  $("#sql-analysis").classList.remove("hidden");
  $("#sql-analysis-dialect").textContent = String(result.dialect || "auto").toUpperCase();
  $("#sql-count-statements").textContent = String(result.statement_count || 0);
  $("#sql-count-tables").textContent = String(tables.length);
  $("#sql-count-conditions").textContent = String(conditions.length);
  $("#sql-count-ctes").textContent = String(ctes.length);
  $("#sql-count-subqueries").textContent = String(subqueries.length);
  $("#sql-table-count").textContent = String(tables.length);
  $("#sql-condition-count").textContent = String(conditions.length);
  $("#sql-cte-count").textContent = String(ctes.length);
  $("#sql-subquery-count").textContent = String(subqueries.length);
  $("#sql-projection-count").textContent = String(projections.length);
  $("#sql-clause-count").textContent = String(clauses.length);

  $("#sql-table-body").innerHTML = tables.length ? tables.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><code class="sql-code">${escapeHtml(item.qualified_name)}</code></td>
      <td>${item.alias ? `<b>${escapeHtml(item.alias)}</b>` : "—"}</td>
      <td><span class="soft-badge">${escapeHtml(item.role)}</span></td>
      <td>${escapeHtml(sqlSourceTypeLabel(item.source_type))}</td>
      <td>${sqlScopeHtml(item)}</td>
    </tr>`).join("") : emptySqlTableRow(6, "Không tìm thấy table/reference trong SQL.");

  $("#sql-condition-body").innerHTML = conditions.length ? conditions.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><span class="soft-badge">${escapeHtml(item.clause)}</span></td>
      <td><code class="sql-code">${escapeHtml(item.expression)}</code></td>
      <td>${sqlPills(item.referenced_aliases)}</td>
      <td>${sqlPills(item.referenced_columns)}</td>
      <td>${sqlScopeHtml(item)}</td>
    </tr>`).join("") : emptySqlTableRow(6, "Không có điều kiện WHERE/JOIN/HAVING trong SQL.");

  $("#sql-cte-list").innerHTML = ctes.length ? ctes.map((item) => `
    <article class="sql-stack-item">
      <header><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.scope_id)}${item.recursive ? " · recursive" : ""}</span></header>
      <small>${item.columns?.length ? `Columns: ${escapeHtml(item.columns.join(", "))}` : "Không khai báo danh sách column riêng"}</small>
      <code class="sql-code">${escapeHtml(item.sql)}</code>
    </article>`).join("") : sqlEmpty("Không có CTE.");

  $("#sql-subquery-list").innerHTML = subqueries.length ? subqueries.map((item) => `
    <article class="sql-stack-item">
      <header><strong>${escapeHtml(item.alias || item.subquery_type)}</strong><span>${escapeHtml(item.subquery_type)} · depth ${item.depth}</span></header>
      <small>${escapeHtml(item.context)} · ${escapeHtml(item.scope_name)}</small>
      <code class="sql-code">${escapeHtml(item.sql)}</code>
    </article>`).join("") : sqlEmpty("Không có subquery.");

  $("#sql-projection-body").innerHTML = projections.length ? projections.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><code class="sql-code">${escapeHtml(item.expression)}</code></td>
      <td>${item.alias ? `<b>${escapeHtml(item.alias)}</b>` : "—"}</td>
      <td>${sqlPills(item.referenced_columns)}</td>
      <td>${sqlScopeHtml(item)}</td>
    </tr>`).join("") : emptySqlTableRow(5, "Không có SELECT expression.");

  $("#sql-clause-list").innerHTML = clauses.length ? clauses.map((item) => `
    <article class="sql-stack-item">
      <header><strong>${escapeHtml(item.clause)}</strong><span>${escapeHtml(item.scope_id)}</span></header>
      <small>${escapeHtml(item.scope_name)}</small>
      <code class="sql-code">${escapeHtml(item.expression)}</code>
    </article>`).join("") : sqlEmpty("Không có GROUP BY, ORDER BY hoặc LIMIT.");
}

function sqlScopeHtml(item) {
  return `<span class="sql-scope">${escapeHtml(item.scope_name || "Main query")}<small>${escapeHtml(item.scope_id || "")} · depth ${Number(item.depth || 0)}</small></span>`;
}

function sqlPills(values) {
  if (!Array.isArray(values) || !values.length) return "—";
  return `<span class="sql-pill-list">${values.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</span>`;
}

function sqlSourceTypeLabel(value) {
  const labels = { TABLE: "Table vật lý", CTE_REFERENCE: "CTE reference", QUERY_REFERENCE: "Query reference" };
  return labels[value] || value || "Table vật lý";
}

function emptySqlTableRow(columnCount, message) {
  return `<tr><td colspan="${columnCount}">${sqlEmpty(message)}</td></tr>`;
}

function sqlEmpty(message) {
  return `<div class="sql-empty">${escapeHtml(message)}</div>`;
}

function renderSqlWorkspace(result) {
  state.sqlWorkspace.workspaceId = result.workspace_id || "";
  state.sqlWorkspace.stale = false;
  state.sqlWorkspace.dirty = {};
  state.sqlWorkspace.rowTokens = {};
  $("#sql-workspace-output").classList.remove("hidden");
  state.sqlWorkspace.exportable = (result.sources || []).some((item) => item.lineage_status === "exact");
  $("#sql-export-all").disabled = !state.sqlWorkspace.exportable;
  const badge = $("#sql-workspace-state");
  badge.textContent = result.transaction_status || "READY";
  badge.classList.remove("stale");

  renderSqlQueryResults(result.results || []);
  renderSqlSourceList(result.sources || []);
  renderSqlSourceData(result.sources || []);
}

function renderSqlQueryResults(results) {
  const container = $("#sql-query-results");
  if (!results.length) {
    container.innerHTML = sqlEmpty("Không có result set.");
    return;
  }
  container.innerHTML = results.map((item) => `
    <article class="sql-db-card">
      <header><strong>${escapeHtml(item.label || item.item_id)}</strong><span>${Number(item.row_count || 0)} rows</span></header>
      ${renderSqlDataGrid(item.first_page || { columns: item.columns || [], rows: [] }, { editable: false })}
    </article>`).join("");
  bindSqlPageControls(container);
}

function renderSqlSourceList(sources) {
  const container = $("#sql-source-list");
  if (!sources.length) {
    container.innerHTML = sqlEmpty("Analyze không tìm thấy source.");
    return;
  }
  container.innerHTML = sources.map((source) => `
    <article class="sql-source-card ${source.lineage_status !== "exact" ? "unsupported" : ""}">
      <header><strong>${escapeHtml(source.label || source.relation_id)}</strong><span>${escapeHtml(source.relation_kind || "")}</span></header>
      <small>${escapeHtml(source.scope_id || "")} · ${escapeHtml(source.lineage_status || "unsupported")}</small>
      ${source.unsupported_reason ? `<p>${escapeHtml(source.unsupported_reason)}</p>` : ""}
    </article>`).join("");
}

function renderSqlSourceData(sources) {
  const container = $("#sql-source-data");
  const exactSources = sources.filter((item) => item.lineage_status === "exact" && item.first_page);
  if (!sources.length) {
    container.innerHTML = sqlEmpty("Chưa có source data.");
    return;
  }
  container.innerHTML = sources.map((source) => {
    if (source.lineage_status !== "exact" || !source.first_page) {
      return `<article class="sql-db-card unsupported"><header><div><strong>${escapeHtml(source.label || source.relation_id)}</strong><small>${escapeHtml(source.scope_id || "")} · ${escapeHtml(source.lineage_status || "unsupported")}</small></div><span>read-only</span></header>${sqlEmpty(source.unsupported_reason || "Không thể truy vết chính xác.")}</article>`;
    }
    rememberSqlRowTokens(source.relation_id, source.first_page.rows || []);
    return `
      <article class="sql-db-card" data-source-card="${escapeHtml(source.relation_id)}">
        <header>
          <div><strong>${escapeHtml(source.label || source.relation_id)}</strong><small>${escapeHtml(source.scope_id || "")} · ${escapeHtml(source.lineage_status || "exact")}</small></div>
          <div class="sql-card-actions">
            <span>${Number(source.row_count || 0)} rows</span>
            <button class="secondary-button small" type="button" data-sql-export="${escapeHtml(source.relation_id)}">Export CSV</button>
            <button class="primary-button small" type="button" data-sql-update="${escapeHtml(source.relation_id)}" disabled>Update Data</button>
          </div>
        </header>
        ${renderSqlDataGrid(source.first_page, { editable: source.updateable, relationId: source.relation_id })}
      </article>`;
  }).join("");
  $$("[data-sql-export]", container).forEach((button) => {
    button.addEventListener("click", () => exportSqlSources([button.dataset.sqlExport]));
  });
  $$("[data-sql-update]", container).forEach((button) => {
    button.addEventListener("click", () => updateSqlSource(button.dataset.sqlUpdate));
  });
  bindSqlGridEditing(container);
  bindSqlPageControls(container);
  if (!exactSources.length) {
    state.sqlWorkspace.exportable = false;
    $("#sql-export-all").disabled = true;
  }
}

function renderSqlDataGrid(page, options = {}) {
  const columns = Array.isArray(page.columns) ? page.columns : [];
  const rows = Array.isArray(page.rows) ? page.rows : [];
  if (!columns.length) return sqlEmpty("Không có metadata column.");
  const headerIndexes = columns.map((column) => `<th style="${column.color ? `--usage-color:${escapeHtml(column.color)}` : ""}" class="${column.color ? "usage-column" : ""}">#${Number(column.index || 0)}</th>`).join("");
  const headerNames = columns.map((column) => {
    const title = column.join_tooltip ? ` title="${escapeHtml(column.join_tooltip)}"` : "";
    return `<th${title} style="${column.color ? `--usage-color:${escapeHtml(column.color)}` : ""}" class="${column.color ? "usage-column" : ""}">
      <span class="sql-col-name">${column.is_primary_key ? "🔑 " : ""}${escapeHtml(column.name || "")}</span>
      <small>${escapeHtml(column.data_type || "")}${column.usage ? ` · ${escapeHtml(column.usage)}` : ""}</small>
    </th>`;
  }).join("");
  const body = rows.length ? rows.map((row) => `
    <tr>
      ${columns.map((column, index) => renderSqlCell(row, column, index, options)).join("")}
    </tr>`).join("") : `<tr><td colspan="${columns.length}">${sqlEmpty("Không có record trong page này.")}</td></tr>`;
  const pageNumber = Number(page.page || 1);
  const pageSize = Number(page.page_size || rows.length || 100);
  const rowCount = Number(page.row_count || rows.length || 0);
  const maxPage = Math.max(1, Math.ceil(rowCount / Math.max(1, pageSize)));
  const pager = page.item_id && rowCount > pageSize ? `
    <div class="sql-grid-pager">
      <button class="ghost-button small" type="button" data-sql-page="${escapeHtml(page.item_id)}" data-page="${pageNumber - 1}" data-relation-id="${escapeHtml(options.relationId || "")}" data-editable="${options.editable ? "1" : "0"}" ${pageNumber <= 1 ? "disabled" : ""}>Prev</button>
      <span>Page ${pageNumber} / ${maxPage}</span>
      <button class="ghost-button small" type="button" data-sql-page="${escapeHtml(page.item_id)}" data-page="${pageNumber + 1}" data-relation-id="${escapeHtml(options.relationId || "")}" data-editable="${options.editable ? "1" : "0"}" ${pageNumber >= maxPage ? "disabled" : ""}>Next</button>
    </div>` : "";
  return `<div class="sql-grid-host"><div class="table-wrap sql-source-table-wrap"><table class="sql-source-table"><thead><tr>${headerIndexes}</tr><tr>${headerNames}</tr></thead><tbody>${body}</tbody></table></div>${pager}</div>`;
}

function renderSqlCell(row, column, index, options) {
  const value = Array.isArray(row.values) ? row.values[index] ?? "" : "";
  const style = column.color ? ` style="--usage-color:${escapeHtml(column.color)}"` : "";
  const className = column.color ? "usage-column" : "";
  if (options.editable && column.editable) {
    return `<td${style} class="${className}"><input class="sql-cell-input" data-sql-edit="1" data-relation-id="${escapeHtml(options.relationId)}" data-row-number="${Number(row.row_number)}" data-column-name="${escapeHtml(column.name)}" value="${escapeHtml(value)}"></td>`;
  }
  return `<td${style} class="${className}"><span class="diff-value">${escapeHtml(value)}</span></td>`;
}

function rememberSqlRowTokens(relationId, rows) {
  state.sqlWorkspace.rowTokens[relationId] = state.sqlWorkspace.rowTokens[relationId] || {};
  rows.forEach((row) => {
    state.sqlWorkspace.rowTokens[relationId][row.row_number] = row.row_token;
  });
}

function bindSqlGridEditing(root) {
  $$("[data-sql-edit]", root).forEach((input) => input.addEventListener("input", () => {
    const relationId = input.dataset.relationId;
    const rowNumber = input.dataset.rowNumber;
    const columnName = input.dataset.columnName;
    state.sqlWorkspace.dirty[relationId] = state.sqlWorkspace.dirty[relationId] || {};
    state.sqlWorkspace.dirty[relationId][rowNumber] = state.sqlWorkspace.dirty[relationId][rowNumber] || {};
    state.sqlWorkspace.dirty[relationId][rowNumber][columnName] = { value: input.value };
    input.classList.add("dirty");
    updateSqlDirtyButtons();
  }));
}

function bindSqlPageControls(root) {
  $$("[data-sql-page]", root).forEach((button) => button.addEventListener("click", async () => {
    const page = Number(button.dataset.page || 1);
    if (!state.sqlWorkspace.workspaceId || page < 1) return;
    try {
      const params = new URLSearchParams({
        workspace_id: state.sqlWorkspace.workspaceId,
        item_id: button.dataset.sqlPage,
        page: String(page),
      });
      const result = await api(`/api/sql-workspace/page?${params}`);
      const relationId = button.dataset.relationId || "";
      if (relationId) rememberSqlRowTokens(relationId, result.rows || []);
      const host = button.closest(".sql-grid-host");
      const cardBeforeReplace = button.closest(".sql-db-card");
      host.outerHTML = renderSqlDataGrid(result, {
        editable: button.dataset.editable === "1",
        relationId,
      });
      const card = relationId ? $(`[data-source-card="${cssEscape(relationId)}"]`) : cardBeforeReplace;
      if (card) {
        bindSqlGridEditing(card);
        bindSqlPageControls(card);
      }
    } catch (error) {
      showToast(error.message, "error", 7000);
    }
  }));
}

function updateSqlDirtyButtons() {
  $$("[data-sql-update]").forEach((button) => {
    const dirty = state.sqlWorkspace.dirty[button.dataset.sqlUpdate] || {};
    button.disabled = document.body.classList.contains("is-busy") || !Object.keys(dirty).length;
  });
}

async function exportSqlSources(relationIds = null) {
  if (!state.sqlWorkspace.workspaceId) return;
  const outputFolder = valueOf("sql-export-folder");
  if (!outputFolder) {
    showToast("Vui lòng chọn output folder để export CSV.", "error");
    return;
  }
  if (!await confirmAction("Export source data SQL?", "CSV sẽ được ghi vào folder đã chọn. Nếu xác định được, mỗi source sẽ có thêm đúng một negative record ở dòng cuối file.")) return;
  startAction("db_sql_export", {
    workspace_id: state.sqlWorkspace.workspaceId,
    settings: getDbSettings("main"),
    output_folder: outputFolder,
    relation_ids: relationIds,
    confirmed: true,
  });
}

async function updateSqlSource(relationId) {
  const dirtyRows = state.sqlWorkspace.dirty[relationId] || {};
  const rows = Object.entries(dirtyRows).map(([rowNumber, values]) => ({
    row_number: Number(rowNumber),
    row_token: state.sqlWorkspace.rowTokens[relationId]?.[rowNumber] || "",
    values,
  }));
  if (!rows.length) return;
  if (!await confirmAction("Update data vào database?", "Các row dirty của cùng table sẽ update trong một transaction. Nếu có conflict hoặc lỗi, toàn bộ nhóm sẽ rollback.")) return;
  startAction("db_sql_update", {
    workspace_id: state.sqlWorkspace.workspaceId,
    settings: getDbSettings("main"),
    relation_id: relationId,
    rows,
    confirmed: true,
  });
}

function summaryMessage(job) {
  const result = job.result || {};
  if (job.action === "compare") return `Đã xử lý ${result.processed_count || 0} case, tạo ${result.workbook_count || 0} workbook và tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "folder_compare") return `Đã tạo ${result.sheet_count || 0} sheet, tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "format_excel_images") return `Đã format ${result.processed_count || 0}/${result.file_count || 0} workbook, chuẩn hóa ${result.workbook_format_sheet_count || 0} sheet, giữ size cũ tại ${result.font_size_skipped_row_count || 0} row; lỗi ${result.error_count || 0}.`;
  if (job.action === "sql_format") return `Đã format ${result.statement_count || 0} câu lệnh SQL.`;
  if (job.action === "sql_load_excel") return `Đã đọc ${result.entry_count || 0} SQL từ Excel và format ${result.statement_count || 0} statement.`;
  if (job.action === "sql_analyze") return `Đã phân tích ${result.statement_count || 0} statement: ${result.tables?.length || 0} table/reference, ${result.conditions?.length || 0} điều kiện, ${result.subqueries?.length || 0} subquery.`;
  if (job.action === "db_test") return "Kết nối cơ sở dữ liệu thành công.";
  if (job.action === "db_list_databases") return `Đã tải ${result.databases?.length || 0} cơ sở dữ liệu.`;
  if (job.action === "db_sql_execute") return `SQL Workspace đã chạy ${result.statements?.length || 0} statement, ${result.results?.length || 0} result set, ${result.sources?.length || 0} source.`;
  if (job.action === "db_sql_export") return `Đã export ${result.files?.length || 0} file CSV; lỗi ${result.error_count || 0}.`;
  if (job.action === "db_sql_update") return `Đã update ${result.updated_count || 0} row; ${result.conflicts?.length || 0} conflict.`;
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
  $$('button[type="submit"], #db-normalize, #db-import, #db-export, #find-empty, #delete-empty, #sql-format, #sql-analyze, #sql-load-excel, #sql-run-current, #sql-run-all, #sql-export-all, [data-sql-export], [data-sql-update], #save-excel-format-preset, #delete-excel-format-preset, #fixme-select-filtered, #fixme-clear-selection, #fixme-bulk-assign, #fixme-bulk-clear, [data-db-test], [data-db-load], #apply-fixmes').forEach((button) => {
    button.disabled = busy || (button.id === "delete-excel-format-preset" && !valueOf("excel-format-preset"));
  });
  updateFixmeToolbarState();
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
function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
  return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
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
