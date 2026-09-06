"use strict";

const state = {
  bootstrap: null,
  notes: [],
  excelFormatPresets: [],
  fixmes: [],
  fixmeFilters: {},
  fixmeSelections: {},
  fixmeCheckedRows: new Set(),
  fixmeScanLocations: [],
  fixmeSortTouched: false,
  fixmeSorts: defaultFixmeSorts(),
  folderComparePairs: [],
  folderPairDrag: null,
  compareView: { cases: [], activeCaseId: "", activeWorkbookId: "", activeSheetName: "", sheet: null, loadingKey: "" },
  job: null,
  jobCursor: 0,
  handledJobs: new Set(),
  loggedJobStarts: new Set(),
  pollTimer: null,
  dbVerified: { main: false, source: false, target: false },
  databaseNames: { main: [], source: [], target: [] },
  databaseHistory: [],
  sourceTables: [],
  selectedTables: [],
  syncProgress: null,
  sqlAnalysisTables: [],
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

const UI_CACHE_KEY = "autocompare:last-inputs:v1";
const DB_HISTORY_CACHE_KEY = "autocompare:database-history:v1";
const UI_CACHE_DEBOUNCE_MS = 250;
const DB_HISTORY_LIMIT = 50;
const COMPARE_PREVIEW_COLORS = {
  a1Background: "#FFC7CE",
  headerBackground: "#C6EFCE",
  headerText: "#006100",
  nameBackground: "#E2EFDA",
  diffBackground: "#E5CCFF",
  a1Text: "#9C0006",
  diffText: "#FF0000",
  text: "#000000",
};
const ACTIVITY_LOG_READY_TEXT = "AutoCompare đã sẵn sàng.";
const ACTIVITY_LOG_SEPARATOR = "-----------------------------------------";
const CANCELLABLE_ACTIONS = new Set([
  "compare_keys_extract",
  "db_test",
  "db_list_databases",
  "db_list_tables",
  "db_normalize",
  "db_import",
  "db_export",
  "db_sync",
  "db_sql_execute",
  "db_sql_export",
  "db_sql_update",
]);

function defaultFixmeSorts() {
  return [
    { field: "case_folder_name", direction: "asc" },
    { field: "workbook_name", direction: "asc" },
    { field: "csv_sheet_name", direction: "asc" },
    { field: "record_number", direction: "asc" },
  ];
}

let uiCacheTimer = null;
let uiCacheRestoring = false;
let uiCacheBound = false;
let sqlJoinTooltipGlobalBound = false;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", init);

async function init() {
  prepareDatabaseWorkspaceLayout();
  prepareCompareReviewLayout();
  prepareAdminatorLayout();
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
    state.compareView = normalizeCompareView(state.bootstrap.compare_view);
    state.databaseHistory = loadDatabaseHistoryCache(state.bootstrap.database_connection_history || []);
    saveDatabaseHistoryCache();
    hydrateDefaults();
    renderWorkflows();
    renderConnectionForms();
    renderNotes();
    refreshFixmeNoteOptions();
    renderExcelFormatPresets();
    renderFixmes();
    renderComparePreview();
    renderTables();
    restoreUiCache();
    updateFolderCompareMode();
    restoreDatabaseSessionConnections();
    renderCompareKeys();
    bindUiCache();
    if (state.bootstrap.job) {
      state.job = state.bootstrap.job;
      state.jobCursor = 0;
      appendJobStartLog(state.job);
      await pollJob();
    } else {
      setJobVisual("idle", "Sẵn sàng");
    }
  } catch (error) {
    showToast(error.message, "error", 7000);
    setJobVisual("error", "Không thể khởi tạo");
  }
}

function prepareCompareReviewLayout() {
  const comparePage = $("#page-compare");
  const previewCard = $("#compare-preview-card", comparePage);
  const fixmeCard = $(".fixme-card", comparePage);
  if (previewCard && fixmeCard && previewCard.compareDocumentPosition(fixmeCard) & Node.DOCUMENT_POSITION_PRECEDING) {
    comparePage.insertBefore(previewCard, fixmeCard);
  }
  const previewStep = $(".step-number", previewCard);
  const fixmeStep = $(".step-number", fixmeCard);
  const previewTitle = $("h3", previewCard);
  const fixmeTitle = $("h3", fixmeCard);
  if (previewStep) previewStep.textContent = "03";
  if (fixmeStep) fixmeStep.textContent = "04";
  if (previewTitle) previewTitle.textContent = "Review FIXME";
  if (fixmeTitle) fixmeTitle.textContent = "Review FIXME Expand";
  fixmeCard?.classList.add("collapsed");
  if (previewCard && !$("#compare-bulk-tools")) {
    $(".card-heading", previewCard)?.insertAdjacentHTML("afterend", `
      <div class="compare-bulk-toolbar hidden" id="compare-bulk-tools">
        <span id="compare-checked-count">0 dòng đã tick</span>
        <select id="compare-bulk-note"></select>
        <button class="secondary-button small" id="compare-bulk-assign" type="button">Gán note cho dòng đã tick</button>
        <button class="ghost-button small" id="compare-bulk-clear" type="button">Bỏ tick</button>
      </div>`);
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

function renderCompareKeys() {
  const keys = state.bootstrap?.update_compare_keys || {};
  const entries = Object.entries(keys).sort(([a], [b]) => a.localeCompare(b));
  $("#compare-key-count").textContent = `Key đã lưu: ${entries.length} table`;
  $("#compare-key-body").innerHTML = entries.length
    ? entries.map(([table, columns]) => `<tr><td>${escapeHtml(table)}</td><td>${escapeHtml(columns.join(", "))}</td></tr>`).join("")
    : '<tr><td colspan="2">Chưa có key đã lưu.</td></tr>';
  const connections = state.bootstrap?.database_connections || {};
  for (const option of $("#compare-key-role").options) {
    const connection = connections[option.value];
    const name = option.value === "main" ? "Database 1" : "Database 2";
    option.textContent = connection ? `${name}: ${connection.database} / ${connection.schema || "default"}` : `${name}: chưa kết nối`;
  }
  const busy = state.job && ["queued", "running"].includes(state.job.state);
  $("#extract-compare-keys").disabled = Boolean(busy);
  $("#remove-compare-keys").disabled = Boolean(busy) || !entries.length;
}

function showPage(pageKey, updateHash) {
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === pageKey));
    $$(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${pageKey}`));
    const page = $(`#page-${pageKey}`);
    $("#page-title").textContent = page.dataset.title;
    $("#page-eyebrow").textContent = page.dataset.eyebrow;
    setMobileMenuOpen(false);
    $$(".nav-item").forEach((item) => {
      if (item.dataset.page === pageKey) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });
    if (updateHash) history.replaceState(null, "", `#${pageKey}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindMobileMenu() {
  const mobile = window.matchMedia("(max-width: 900px)");
  $("#menu-toggle").addEventListener("click", () => {
    if (mobile.matches) setMobileMenuOpen(!$("#sidebar").classList.contains("open"));
    else {
      document.body.classList.toggle("nav-collapsed");
      updateMenuToggle();
    }
  });
  $("#menu-backdrop").addEventListener("click", () => setMobileMenuOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && $("#sidebar").classList.contains("open")) {
      setMobileMenuOpen(false);
      $("#menu-toggle").focus();
    }
  });
  mobile.addEventListener("change", () => {
    document.body.classList.remove("nav-collapsed");
    setMobileMenuOpen(false);
  });
  setMobileMenuOpen(false);
}

function setMobileMenuOpen(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#menu-backdrop")?.classList.toggle("visible", open);
  $("#sidebar").inert = window.matchMedia("(max-width: 900px)").matches && !open;
  updateMenuToggle();
}

function updateMenuToggle() {
  const mobile = window.matchMedia("(max-width: 900px)").matches;
  const expanded = mobile ? $("#sidebar").classList.contains("open") : !document.body.classList.contains("nav-collapsed");
  const button = $("#menu-toggle");
  button.setAttribute("aria-expanded", String(expanded));
  button.title = expanded ? "Thu gọn menu" : "Mở menu";
  button.setAttribute("aria-label", button.title);
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
  const dialogHeader = $("header", dialog);
  const closeButton = $("#db-close-connections", dialog);
  if (dialogHeader && closeButton && !$("#db-switch-connections", dialog)) {
    const actions = document.createElement("div");
    actions.className = "db-dialog-header-actions";
    actions.innerHTML = `<button class="secondary-button small" id="db-switch-connections" type="button">Switch DB 1 ⇄ DB 2</button>`;
    actions.appendChild(closeButton);
    dialogHeader.appendChild(actions);
  }

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
  if (toolbarText) toolbarText.textContent = "Format/Phân tích dùng parser; chạy SQL dùng Database 1 đã kết nối";
  const actions = $("#sql-db-actions", panel) || $(".sql-toolbar-actions", panel);
  if (actions && !$("#sql-run-current")) {
    actions.insertAdjacentHTML("beforeend", `
      <button class="secondary-button small" id="sql-run-current" type="button">Chạy hiện tại</button>
      <button class="secondary-button small" id="sql-run-all" type="button">Chạy toàn bộ</button>
      <button class="ghost-button small" id="sql-write-mode" type="button">Ghi DB OFF</button>`);
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
  $("#activity-toggle").addEventListener("click", () => {
    panel.classList.toggle("collapsed");
    updateActivityToggleTitle();
  });
  $("#job-status-button").addEventListener("click", () => {
    panel.classList.remove("collapsed");
    updateActivityToggleTitle();
  });
  $("#clear-log").addEventListener("click", () => { $("#activity-log").textContent = ""; });
  $("#cancel-job").addEventListener("click", cancelCurrentJob);
  updateActivityToggleTitle();
}

function updateActivityToggleTitle() {
  const collapsed = $("#activity-panel")?.classList.contains("collapsed");
  $("#activity-toggle")?.setAttribute("title", collapsed ? "Mở nhật ký tác vụ" : "Thu gọn nhật ký tác vụ");
}

function bindUiCache() {
  if (uiCacheBound) return;
  uiCacheBound = true;
  document.addEventListener("input", (event) => {
    if (isCacheableEventTarget(event.target)) saveUiCacheDebounced();
  });
  document.addEventListener("change", (event) => {
    if (isCacheableEventTarget(event.target)) saveUiCacheDebounced();
  });
  window.addEventListener("beforeunload", saveUiCacheNow);
}

function isCacheableEventTarget(target) {
  if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement || target instanceof HTMLTextAreaElement)) return false;
  if (target.matches('input[type="radio"][name], input[type="checkbox"][name]')) return true;
  return shouldCacheControl(target);
}

function shouldCacheControl(control) {
  if (!control?.id) return false;
  const tag = control.tagName.toLowerCase();
  if (!["input", "select", "textarea"].includes(tag)) return false;
  const type = (control.getAttribute("type") || "").toLowerCase();
  if (["password", "button", "submit", "reset", "file", "hidden"].includes(type)) return false;
  const id = control.id.toLowerCase();
  if (id.includes("password")) return false;
  if (control.matches("[data-db-history-select]")) return false;
  if (id === "activity-log" || id === "path-current" || id === "path-root-select" || id === "save-file-name") return false;
  if (id.startsWith("note-") || id.startsWith("confirm-")) return false;
  return true;
}

function restoreUiCache() {
  let cache = null;
  try {
    cache = JSON.parse(window.localStorage.getItem(UI_CACHE_KEY) || "null");
  } catch {
    return;
  }
  if (!cache || typeof cache !== "object") return;
  uiCacheRestoring = true;
  try {
    Object.entries(cache.fields || {}).forEach(([id, value]) => {
      const control = document.getElementById(id);
      if (!control || !shouldCacheControl(control)) return;
      if (control instanceof HTMLInputElement && control.type === "checkbox") control.checked = Boolean(value);
      else control.value = value ?? "";
    });
    Object.entries(cache.radioGroups || {}).forEach(([name, value]) => {
      const radio = $(`input[type="radio"][name="${cssEscape(name)}"][value="${cssEscape(value)}"]`);
      if (radio) radio.checked = true;
    });
    Object.entries(cache.checkboxGroups || {}).forEach(([name, values]) => {
      const selected = new Set(Array.isArray(values) ? values.map(String) : []);
      $$(`input[type="checkbox"][name="${cssEscape(name)}"]`).forEach((input) => {
        if (!input.id) input.checked = selected.has(input.value);
      });
    });
    if (Array.isArray(cache.selectedTables)) {
      state.selectedTables = uniqueStrings(cache.selectedTables);
    }
  } finally {
    uiCacheRestoring = false;
  }
  finalizeRestoredUiCache();
}

function finalizeRestoredUiCache() {
  ["main", "target", "source"].forEach((scope) => {
    if (!$(`#db-${scope}-type`)) return;
    applyDatabaseType(scope, false);
    syncAuthFields(scope);
    ensureDefaultSqlServerDriver(scope);
  });
  ensureDefaultMainDatabaseHost();
  syncImportButtonLabel();
  syncSyncModeControls();
  state.fixmeFilters = {};
  $$("[data-fixme-filter]").forEach((control) => {
    const field = control.dataset.fixmeFilter;
    const value = control.value.trim();
    if (field && value) state.fixmeFilters[field] = value;
  });
  renderFixmes();
  renderTables();
  renderDatabaseHistorySelects();
  if (valueOf("sql-input")) markSqlWorkspaceStale();
}

function restoreDatabaseSessionConnections() {
  const remembered = state.bootstrap?.database_connections || {};
  const tableCache = state.bootstrap?.database_tables || {};
  ["main", "target", "source"].forEach((scope) => {
    const settings = remembered[scope];
    if (!settings || !$(`#db-${scope}-type`)) return;
    if (dbSettingsMostlyEmpty(scope)) setDbSettings(scope, settings);
    if (!dbPublicSettingsMatch(getDbSettings(scope), settings)) return;
    setVerified(scope, true);
    if (scope === "main" && Array.isArray(tableCache[scope])) {
      state.sourceTables = tableCache[scope];
      const tableLookup = new Map(state.sourceTables.map((name) => [name.toLocaleLowerCase("vi"), name]));
      state.selectedTables = uniqueStrings(state.selectedTables.map((name) => tableLookup.get(String(name).toLocaleLowerCase("vi")) || "").filter(Boolean));
    }
  });
  renderTables();
  renderDatabaseHistorySelects();
}

function dbSettingsMostlyEmpty(scope) {
  const settings = getDbSettings(scope);
  const host = String(settings.host || "").trim().toLocaleLowerCase("vi");
  return !String(settings.database || "").trim()
    && !String(settings.username || "").trim()
    && (!host || host === "localhost");
}

function dbPublicSettingsMatch(current, remembered) {
  const sameText = (left, right) => String(left || "").trim().toLocaleLowerCase("vi") === String(right || "").trim().toLocaleLowerCase("vi");
  return sameText(current.database_type, remembered.database_type)
    && sameText(current.host, remembered.host)
    && sameText(current.database, remembered.database)
    && sameText(current.schema, remembered.schema)
    && String(current.port || "").trim() === String(remembered.port || "").trim()
    && sameText(current.username, remembered.username)
    && Boolean(current.trusted_connection) === Boolean(remembered.trusted_connection)
    && sameText(current.driver, remembered.driver)
    && Boolean(current.trust_server_certificate) === Boolean(remembered.trust_server_certificate)
    && Boolean(current.encrypt) === Boolean(remembered.encrypt);
}

function loadDatabaseHistoryCache(sessionHistory = []) {
  let localConnections = [];
  try {
    const cache = JSON.parse(window.localStorage.getItem(DB_HISTORY_CACHE_KEY) || "null");
    localConnections = Array.isArray(cache) ? cache : Array.isArray(cache?.connections) ? cache.connections : [];
  } catch {
    localConnections = [];
  }
  return mergeDatabaseHistories(sessionHistory, localConnections);
}

function saveDatabaseHistoryCache() {
  try {
    window.localStorage.setItem(DB_HISTORY_CACHE_KEY, JSON.stringify({
      savedAt: new Date().toISOString(),
      connections: state.databaseHistory,
    }));
  } catch {
    // Ignore storage failures; connection history is a convenience only.
  }
}

function mergeDatabaseHistories(...groups) {
  const merged = [];
  const seen = new Set();
  groups.flat().forEach((item) => {
    const settings = sanitizeDatabaseHistorySettings(item);
    if (!settings) return;
    const key = databaseHistoryKey(settings);
    if (seen.has(key)) return;
    seen.add(key);
    merged.push(settings);
  });
  return merged.slice(0, DB_HISTORY_LIMIT);
}

function sanitizeDatabaseHistorySettings(settings) {
  if (!settings || typeof settings !== "object") return null;
  const item = {
    database_type: String(settings.database_type || "SQL Server"),
    host: String(settings.host || ""),
    port: String(settings.port || ""),
    database: String(settings.database || ""),
    schema: String(settings.schema || ""),
    driver: String(settings.driver || ""),
    username: String(settings.username || ""),
    password: "",
    trusted_connection: settings.trusted_connection === true,
    trust_server_certificate: settings.trust_server_certificate !== false,
    encrypt: settings.encrypt !== false,
    updated_at: String(settings.updated_at || settings.saved_at || new Date().toISOString()),
  };
  if (!item.host.trim() && !item.database.trim()) return null;
  return item;
}

function rememberDatabaseHistory(settings) {
  const item = sanitizeDatabaseHistorySettings(settings);
  if (!item) return;
  const key = databaseHistoryKey(item);
  state.databaseHistory = [item, ...state.databaseHistory.filter((entry) => databaseHistoryKey(entry) !== key)].slice(0, DB_HISTORY_LIMIT);
  saveDatabaseHistoryCache();
  renderDatabaseHistorySelects();
}

function renderDatabaseHistorySelects() {
  $$("[data-db-history-select]").forEach((select) => {
    const scope = select.dataset.dbHistorySelect;
    const currentKey = $(`#db-${scope}-type`) ? databaseHistoryKey(getDbSettings(scope)) : "";
    select.innerHTML = `<option value="">-- Chọn kết nối đã dùng --</option>` + state.databaseHistory.map((settings) => {
      const key = databaseHistoryKey(settings);
      return `<option value="${escapeHtml(key)}">${escapeHtml(databaseHistoryLabel(settings))}</option>`;
    }).join("");
    select.value = state.databaseHistory.some((settings) => databaseHistoryKey(settings) === currentKey) ? currentKey : "";
  });
}

function applyDatabaseHistorySelection(scope) {
  const select = $(`#db-${scope}-history`);
  if (!select?.value) return;
  const settings = state.databaseHistory.find((item) => databaseHistoryKey(item) === select.value);
  if (!settings) return;
  setDbSettings(scope, settings);
  state.databaseNames[scope] = [];
  renderDatabaseNameList(scope);
  invalidateDbConnection(scope);
  saveUiCacheDebounced();
  showToast("Đang tự động kết nối CSDL đã chọn.", "success", 3500);
  startAction("db_test", { settings: getDbSettings(scope), role: scope, load_tables: scope === "main" });
}

function databaseHistoryKey(settings) {
  return [
    settings.database_type,
    settings.host,
    settings.database,
    settings.schema,
    settings.port,
    settings.username,
    settings.trusted_connection ? "1" : "0",
    settings.driver,
    settings.trust_server_certificate ? "1" : "0",
    settings.encrypt ? "1" : "0",
  ].map((value) => String(value || "").trim().toLocaleLowerCase("vi")).join("\u001f");
}

function databaseHistoryLabel(settings) {
  const type = settings.database_type || "CSDL";
  const server = [settings.host, settings.port].filter(Boolean).join(":") || "(chưa có máy chủ)";
  const database = settings.database || "(chưa chọn CSDL)";
  const schema = settings.schema ? ` / ${settings.schema}` : "";
  const user = settings.trusted_connection ? "Xác thực Windows" : (settings.username || "chưa nhập user");
  return `${type} | ${server} | ${database}${schema} | ${user}`;
}

function saveUiCacheDebounced() {
  if (uiCacheRestoring) return;
  window.clearTimeout(uiCacheTimer);
  uiCacheTimer = window.setTimeout(saveUiCacheNow, UI_CACHE_DEBOUNCE_MS);
}

function saveUiCacheNow() {
  if (uiCacheRestoring) return;
  window.clearTimeout(uiCacheTimer);
  const fields = {};
  $$("input[id], select[id], textarea[id]").forEach((control) => {
    if (!shouldCacheControl(control)) return;
    fields[control.id] = control instanceof HTMLInputElement && control.type === "checkbox" ? control.checked : control.value;
  });
  const radioGroups = {};
  $$('input[type="radio"][name]').forEach((input) => {
    if (input.checked) radioGroups[input.name] = input.value;
  });
  const checkboxGroups = {};
  $$('input[type="checkbox"][name]').forEach((input) => {
    if (input.id) return;
    if (!checkboxGroups[input.name]) checkboxGroups[input.name] = [];
    if (input.checked) checkboxGroups[input.name].push(input.value);
  });
  const cache = {
    savedAt: new Date().toISOString(),
    page: window.location.hash.slice(1),
    fields,
    radioGroups,
    checkboxGroups,
    selectedTables: state.selectedTables,
  };
  try {
    window.localStorage.setItem(UI_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Local cache is a convenience; quota/private-mode failures should not block workflows.
  }
}

function uniqueStrings(values) {
  const seen = new Set();
  const result = [];
  values.forEach((value) => {
    const text = String(value ?? "").trim();
    if (!text) return;
    const key = text.toLocaleLowerCase("vi");
    if (seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result;
}

function ensureDefaultMainDatabaseHost() {
  const hostInput = $("#db-main-host");
  if (hostInput && !hostInput.value.trim()) hostInput.value = "localhost";
}

function preferredSqlServerDriver(drivers) {
  const choices = (Array.isArray(drivers) && drivers.length ? drivers : ["SQL Server Native Client RDA 11.0", "ODBC Driver 18 for SQL Server"]).filter(Boolean);
  const keywords = ["SQL Server Native Client RDA", "SQL Server Native Client", "SQL Server Native"];
  for (const keyword of keywords) {
    const match = choices.find((driver) => driver.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()));
    if (match) return match;
  }
  return choices[0] || "SQL Server Native Client RDA 11.0";
}

function ensureDefaultSqlServerDriver(scope) {
  if (valueOf(`db-${scope}-type`) !== "SQL Server") return;
  const driverInput = $(`#db-${scope}-driver`);
  if (!driverInput) return;
  const preferred = preferredSqlServerDriver(state.bootstrap?.sqlserver_drivers || []);
  if (!driverInput.value || driverInput.value === "ODBC Driver 18 for SQL Server") driverInput.value = preferred;
}

function bindForms() {
  $("#compare-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const workflows = $$("input[name='compare-workflow']:checked").map((item) => item.value);
    startAction("compare", { root: valueOf("compare-root"), workflows });
  });
  $("#extract-compare-keys").addEventListener("click", () => {
    if (!$("#compare-root").reportValidity()) return;
    startAction("compare_keys_extract", { root: valueOf("compare-root"), role: valueOf("compare-key-role") });
  });
  $("#remove-compare-keys").addEventListener("click", async () => {
    const count = Object.keys(state.bootstrap.update_compare_keys || {}).length;
    if (await confirmAction("Xóa key compare?", `Xóa toàn bộ key đã lưu của ${count} table, bao gồm key nhập thủ công. Các lần compare tiếp theo sẽ bỏ qua bước lọc record ngoài đối tượng cho đến khi có key mới.`)) {
      startAction("compare_keys_remove", { confirmed: true });
    }
  });
  $("#toggle-workflows").addEventListener("click", () => {
    const boxes = $$("input[name='compare-workflow']");
    const selectAll = boxes.some((box) => !box.checked);
    boxes.forEach((box) => { box.checked = selectAll; });
    saveUiCacheDebounced();
  });
  $("#folder-compare-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const exportMode = $('input[name="folder-export-mode"]:checked')?.value || "single";
    if (exportMode === "separate" && !state.folderComparePairs.length) {
      loadFolderComparePairs();
      return;
    }
    startAction("folder_compare", {
      left: valueOf("folder-left"),
      right: valueOf("folder-right"),
      output: valueOf("folder-output"),
      export_mode: exportMode,
      pairs: exportMode === "separate" ? collectFolderComparePairs() : [],
    });
  });
  $$('input[name="folder-export-mode"]').forEach((control) => control.addEventListener("change", updateFolderCompareMode));
  $("#load-folder-pairs")?.addEventListener("click", loadFolderComparePairs);
  ["folder-left", "folder-right"].forEach((id) => $(`#${id}`)?.addEventListener("change", resetFolderComparePairs));
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
      ? "Có căn ảnh theo 6 vùng hệ thống cũ/mới và Input/Steps/Output."
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
  $("#sql-input").addEventListener("input", () => {
    clearSqlAnalysisTables();
    $("#sql-statement-count").textContent = "0 statement";
    markSqlWorkspaceStale();
  });
  $("#copy-current-sql").addEventListener("click", copyCurrentSql);
  $("#copy-sql-tables")?.addEventListener("click", copyAnalyzedSqlTables);
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
    const whereClause = valueOf("sync-where-clause");
    const duplicateMode = syncMode === "condition" && checked("sync-handle-duplicates") ? valueOf("sync-duplicate-mode") : "error";
    if (syncMode === "condition" && !whereClause.trim()) {
      showToast("Vui lòng nhập điều kiện WHERE khi đồng bộ theo điều kiện.", "error");
      return;
    }
    const modeDetails = {
      incremental: deleteTargetOnly
        ? "Chỉ INSERT/UPDATE record khác biệt và DELETE record chỉ có ở đích. Table phải có primary key."
        : "Chỉ INSERT/UPDATE record khác biệt; record chỉ có ở đích sẽ được giữ lại.",
      append: "Toàn bộ record nguồn sẽ được INSERT thêm; dữ liệu hiện có ở đích được giữ nguyên.",
      condition: syncDuplicateModeText(duplicateMode),
      truncate_table: "CẢNH BÁO: table đích sẽ bị TRUNCATE rồi INSERT lại toàn bộ dữ liệu nguồn.",
    };
    const detail = [
      `Đồng bộ ${allTables ? "toàn bộ table nguồn" : `${tableNames.length} table đã chọn`} từ nguồn sang đích.`,
      modeDetails[syncMode],
      syncMode === "condition" ? `Điều kiện áp dụng cho từng table:\nWHERE ${whereClause.replace(/^where\s+/i, "")}` : "",
      syncMode === "condition" && duplicateMode !== "error"
        ? "Trước khi xóa hoặc ghi đè record trùng key, hệ thống sẽ backup record hiện có ở DB đích vào folder db_sync_backups trong project."
        : "",
      syncMode === "incremental" || syncMode === "condition"
        ? `Dữ liệu được đọc và ghi theo batch ${batchSize || "5000"} record; không nạp toàn bộ table vào RAM.`
        : (limit ? `Mỗi table chỉ đồng bộ tối đa ${limit} record.` : "Đồng bộ toàn bộ record trong mỗi table."),
    ].filter(Boolean).join("\n\n");
    if (await confirmAction("Xác nhận đồng bộ cơ sở dữ liệu", detail)) {
      resetSyncProgress(tableNames);
      startAction("db_sync", {
        source_settings: getDbSettings("main"), target_settings: getDbSettings("target"), table_names: tableNames,
        record_limit: limit, keep_identity: checked("sync-keep-identity"), sync_mode: syncMode,
        batch_size: batchSize, delete_target_only: deleteTargetOnly,
        where_clause: syncMode === "condition" ? whereClause : "",
        duplicate_mode: duplicateMode,
        truncate_before_sync: syncMode === "truncate_table", confirmed: true,
      });
    }
  });

  $$('input[name="sync-mode"]').forEach((input) => input.addEventListener("change", syncSyncModeControls));
  $("#sync-handle-duplicates").addEventListener("change", syncSyncModeControls);
  $("#sync-duplicate-mode").addEventListener("change", syncSyncModeControls);
  syncSyncModeControls();
  $("#sync-all-tables").addEventListener("change", renderTables);
  const syncTableFilter = $("#sync-table-filter");
  syncTableFilter.placeholder = "Nhập table1, table2 rồi Enter; hoặc gõ để lọc";
  syncTableFilter.addEventListener("input", renderTables);
  syncTableFilter.addEventListener("keydown", handleSyncTableFilterKeydown);
  $("#clear-selected-tables").addEventListener("click", () => {
    state.selectedTables = [];
    renderTables();
    saveUiCacheDebounced();
  });
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
  $("#apply-fixmes").addEventListener("click", applySelectedFixmeNotes);
  $("#apply-fixmes-preview").addEventListener("click", applySelectedFixmeNotes);
  $("#refresh-compare-preview").addEventListener("click", refreshComparePreview);
  $("#check-fixmes")?.addEventListener("click", checkRemainingFixmes);
  $("#toggle-fixme-expand")?.addEventListener("click", toggleFixmeExpand);
  $("#compare-bulk-note")?.addEventListener("change", updateCompareBulkToolbarState);
  $("#compare-bulk-assign")?.addEventListener("click", assignCompareBulkNote);
  $("#compare-bulk-clear")?.addEventListener("click", clearCompareRowSelection);

  $$('[data-browse-target]').forEach((button) => button.addEventListener("click", () => openPathPicker(button)));
}

function applySelectedFixmeNotes() {
    const selections = Object.fromEntries(Object.entries(state.fixmeSelections).filter(([, value]) => value));
    if (!Object.keys(selections).length) {
      showToast("Vui lòng gán ít nhất một note cho dòng FIXME.", "error");
      return;
    }
    startAction("apply_fixmes", { selections });
}

function toggleFixmeExpand() {
  const card = $("#fixme-expand-card");
  if (!card) return;
  const collapsed = card.classList.toggle("collapsed");
  $("#toggle-fixme-expand").textContent = collapsed ? "Mở rộng" : "Thu gọn";
}

function checkRemainingFixmes() {
  startAction("check_fixmes", {});
}

function updateFolderCompareMode() {
  const exportMode = $('input[name="folder-export-mode"]:checked')?.value || "single";
  $("#folder-pair-panel")?.classList.toggle("hidden", exportMode !== "separate");
}

function resetFolderComparePairs() {
  state.folderComparePairs = [];
  renderFolderComparePairs();
}

async function loadFolderComparePairs() {
  try {
    const response = await api("/api/folder-compare/pairs", {
      method: "POST",
      body: { left: valueOf("folder-left"), right: valueOf("folder-right") },
    });
    state.folderComparePairs = Array.isArray(response.pairs) ? response.pairs : [];
    renderFolderComparePairs();
    showToast(`Đã quét ${state.folderComparePairs.length} pair CSV.`, "success", 3500);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function collectFolderComparePairs() {
  return $$("#folder-pair-body tr[data-index]").map((row) => ({
    left_name: row.querySelector("[data-pair-left]")?.dataset.pairLeft || "",
    right_name: row.querySelector("[data-pair-right]")?.dataset.pairRight || "",
    output_name: row.querySelector("[data-pair-output]")?.value?.trim() || "",
  }));
}

function renderFolderComparePairs() {
  const body = $("#folder-pair-body");
  if (!body) return;
  if (!state.folderComparePairs.length) {
    body.innerHTML = `<tr><td colspan="3">Không tìm thấy file CSV trong hai folder.</td></tr>`;
    return;
  }
  body.innerHTML = state.folderComparePairs.map((pair, index) => `
    <tr data-index="${index}">
      <td draggable="true" data-pair-side="left" data-pair-left="${escapeHtml(pair.left_name || "")}" title="${escapeHtml(pair.left_name || "")}">${escapeHtml(pair.left_name || "(trống)")}</td>
      <td draggable="true" data-pair-side="right" data-pair-right="${escapeHtml(pair.right_name || "")}" title="${escapeHtml(pair.right_name || "")}">${escapeHtml(pair.right_name || "(trống)")}</td>
      <td><input data-pair-output value="${escapeHtml(pair.output_name || "")}" placeholder="compare_${index + 1}.xlsx"></td>
    </tr>
  `).join("");
  $$("#folder-pair-body [data-pair-side]").forEach((cell) => {
    cell.addEventListener("dragstart", handleFolderPairDragStart);
    cell.addEventListener("dragover", handleFolderPairDragOver);
    cell.addEventListener("drop", handleFolderPairDrop);
    cell.addEventListener("dragend", handleFolderPairDragEnd);
  });
}

function handleFolderPairDragStart(event) {
  const cell = event.currentTarget;
  state.folderPairDrag = { side: cell.dataset.pairSide, index: Number(cell.closest("tr")?.dataset.index) };
  cell.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
}

function handleFolderPairDragOver(event) {
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
}

function handleFolderPairDrop(event) {
  event.preventDefault();
  const target = event.currentTarget;
  const targetIndex = Number(target.closest("tr")?.dataset.index);
  const drag = state.folderPairDrag;
  if (!drag || drag.side !== target.dataset.pairSide || !Number.isInteger(drag.index) || drag.index === targetIndex) return;
  state.folderComparePairs = collectFolderComparePairs();
  const field = drag.side === "left" ? "left_name" : "right_name";
  const values = state.folderComparePairs.map((pair) => pair[field] || "");
  const [moved] = values.splice(drag.index, 1);
  values.splice(targetIndex, 0, moved);
  state.folderComparePairs = state.folderComparePairs.map((pair, index) => ({ ...pair, [field]: values[index] || "" }));
  renderFolderComparePairs();
}

function handleFolderPairDragEnd() {
  $$("#folder-pair-body .dragging").forEach((cell) => cell.classList.remove("dragging"));
  state.folderPairDrag = null;
}

function bindDialogs() {
  const dbDialog = $("#db-connection-dialog");
  $("#db-open-connections")?.addEventListener("click", () => dbDialog?.showModal());
  $("#db-close-connections")?.addEventListener("click", () => dbDialog?.close());
  $("#db-switch-connections")?.addEventListener("click", switchMainAndTargetDatabases);
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
    const drivers = state.bootstrap.sqlserver_drivers.length ? state.bootstrap.sqlserver_drivers : ["SQL Server Native Client RDA 11.0", "ODBC Driver 18 for SQL Server"];
    const defaultDriver = preferredSqlServerDriver(drivers);
    $(".connection-fields", form).innerHTML = `
      <label class="field connection-history-field"><span>K&#x1EBF;t n&#x1ED1;i &#x111;&#xE3; d&#xF9;ng</span><select id="db-${scope}-history" data-db-history-select="${scope}"></select><small>Ch&#x1ECD;n l&#x1EA1;i m&#xE1;y ch&#x1EE7;/CSDL &#x111;&#xE3; k&#x1EBF;t n&#x1ED1;i tr&#x1B0;&#x1EDB;c &#x111;&#xF3;. H&#x1EC7; th&#x1ED1;ng s&#x1EBD; t&#x1EF1; &#x111;&#x1ED9;ng k&#x1EBF;t n&#x1ED1;i l&#x1EA1;i b&#x1EB1;ng th&#xF4;ng tin &#x111;&#xE3; l&#x1B0;u tr&#xEA;n server local.</small></label>
      <label class="field"><span>Loại CSDL</span><select id="db-${scope}-type">${state.bootstrap.database_types.map((item) => `<option>${escapeHtml(item)}</option>`).join("")}</select></label>
      <label class="field"><span>Port</span><input id="db-${scope}-port" value="${escapeHtml(defaults.port)}"></label>
      <label class="field host-field"><span>Server / Host</span><input id="db-${scope}-host" value="${scope === "main" ? "localhost" : ""}" placeholder="localhost hoặc server\\instance"></label>
      <label class="field"><span>Database / Service</span><input id="db-${scope}-database" list="db-${scope}-database-list"><datalist id="db-${scope}-database-list"></datalist></label>
      <label class="field"><span>Schema</span><input id="db-${scope}-schema" value="${escapeHtml(defaults.schema)}"></label>
      <label class="field auth-row" id="db-${scope}-driver-field"><span>Driver ODBC</span><select id="db-${scope}-driver">${drivers.map((item) => `<option ${item === defaultDriver ? "selected" : ""}>${escapeHtml(item)}</option>`).join("")}</select></label>
      <label class="field"><span>User</span><input id="db-${scope}-username" autocomplete="username"></label>
      <label class="field"><span>Password</span><input id="db-${scope}-password" type="password" autocomplete="current-password"></label>
      <div class="check-row auth-row" id="db-${scope}-trusted-row"><label><input type="checkbox" id="db-${scope}-trusted" ${scope === "main" || scope === "source" || scope === "target" ? "checked" : ""}> Xác thực Windows</label></div>`;

    form.addEventListener("submit", (event) => event.preventDefault());

    const settingsControls = $$(`input, select`, form).filter((input) => !input.matches("[data-db-history-select]"));
    settingsControls.forEach((input) => input.addEventListener("input", () => invalidateDbConnection(scope)));
    settingsControls.forEach((input) => input.addEventListener("change", () => {
      if (input.id === `db-${scope}-type`) applyDatabaseType(scope, true);
      if (input.id === `db-${scope}-trusted`) syncAuthFields(scope);
      invalidateDbConnection(scope);
    }));
    $(`#db-${scope}-history`).addEventListener("change", () => applyDatabaseHistorySelection(scope));
    $(`#db-${scope}-trusted`).addEventListener("change", () => syncAuthFields(scope));
    applyDatabaseType(scope, false);
    syncAuthFields(scope);
  });
  renderDatabaseHistorySelects();

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

function setDbSettings(scope, settings) {
  $(`#db-${scope}-type`).value = settings.database_type || "";
  applyDatabaseType(scope, false);
  $(`#db-${scope}-host`).value = settings.host || "";
  $(`#db-${scope}-port`).value = settings.port || "";
  $(`#db-${scope}-database`).value = settings.database || "";
  $(`#db-${scope}-schema`).value = settings.schema || "";
  $(`#db-${scope}-driver`).value = settings.driver || "";
  $(`#db-${scope}-username`).value = settings.username || "";
  $(`#db-${scope}-password`).value = settings.password || "";
  $(`#db-${scope}-trusted`).checked = !!settings.trusted_connection;
  syncAuthFields(scope);
  ensureDefaultSqlServerDriver(scope);
}

function switchMainAndTargetDatabases() {
  const mainSettings = getDbSettings("main");
  const targetSettings = getDbSettings("target");
  const mainVerified = state.dbVerified.main;
  const targetVerified = state.dbVerified.target;
  const mainDatabases = state.databaseNames.main || [];
  const targetDatabases = state.databaseNames.target || [];

  setDbSettings("main", targetSettings);
  setDbSettings("target", mainSettings);
  state.databaseNames.main = targetDatabases;
  state.databaseNames.target = mainDatabases;
  renderDatabaseNameList("main");
  renderDatabaseNameList("target");
  state.sourceTables = [];
  state.selectedTables = [];
  renderTables();
  saveUiCacheDebounced();
  api("/api/database/session/switch", { method: "POST", body: {} }).then((response) => {
    state.bootstrap.database_connections = response.database_connections || {};
    state.bootstrap.database_connection_history = response.database_connection_history || state.bootstrap.database_connection_history || [];
    renderCompareKeys();
    state.databaseHistory = mergeDatabaseHistories(state.bootstrap.database_connection_history, state.databaseHistory);
    saveDatabaseHistoryCache();
    renderDatabaseHistorySelects();
    state.bootstrap.database_tables = response.database_tables || {};
  }).catch(() => {});
  setVerified("main", targetVerified);
  setVerified("target", mainVerified);
  disableSqlWriteModeLocal();
  markSqlWorkspaceStale();
  showToast("Đã switch Database 1 và Database 2.", "success");
  if (targetVerified) {
    startAction("db_test", { settings: getDbSettings("main"), role: "main", load_tables: true });
  }
}

function renderDatabaseNameList(scope) {
  const list = $(`#db-${scope}-database-list`);
  if (!list) return;
  list.innerHTML = (state.databaseNames[scope] || []).map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
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
  const condition = mode === "condition";
  const limitInput = $("#sync-record-limit");
  limitInput.disabled = incremental || condition;
  if (incremental || condition) limitInput.value = "";
  $("#sync-batch-size").disabled = !(incremental || condition);
  $("#sync-delete-target-only").disabled = !incremental;
  $("#sync-delete-target-only-row").classList.toggle("disabled", !incremental);
  $("#sync-condition-panel").classList.toggle("hidden", !condition);
  $("#sync-where-clause").disabled = !condition;
  $("#sync-handle-duplicates").disabled = !condition;
  $("#sync-duplicate-mode").disabled = !condition || !checked("sync-handle-duplicates");
  const labels = {
    incremental: "Đồng bộ theo key",
    append: "Insert toàn bộ dữ liệu",
    condition: "Đồng bộ theo điều kiện",
    truncate_table: "Truncate & đồng bộ lại",
  };
  const hints = {
    incremental: "Đồng bộ theo primary key; chỉ ghi các record khác biệt và table nguồn/đích phải có key giống nhau.",
    append: "Insert toàn bộ record nguồn; có thể lỗi duplicate key nếu đích đã có dữ liệu.",
    condition: checked("sync-handle-duplicates")
      ? "Chỉ lấy record nguồn theo WHERE; record đích trùng key sẽ được backup trước khi xóa hoặc ghi đè."
      : "Chỉ lấy record nguồn theo WHERE; nếu đích đã có key trùng thì database có thể báo lỗi duplicate key.",
    truncate_table: "Xóa sạch table đích rồi insert lại toàn bộ dữ liệu nguồn.",
  };
  $("#run-db-sync").innerHTML = `${labels[mode] || labels.incremental} <b>→</b>`;
  $("#sync-mode-hint").textContent = hints[mode] || hints.incremental;
}

function syncDuplicateModeText(mode) {
  if (mode === "delete_insert") {
    return "Lấy record nguồn theo WHERE. Record đích trùng primary key sẽ được backup, xóa trước, rồi insert lại từ nguồn.";
  }
  if (mode === "upsert") {
    return "Lấy record nguồn theo WHERE. Record đích trùng primary key sẽ được backup rồi ghi đè bằng dữ liệu nguồn; key chưa có sẽ được insert.";
  }
  return "Lấy record nguồn theo WHERE rồi insert sang đích. Nếu đích đã có primary key trùng, database có thể báo lỗi.";
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
      <td><select data-fixme-index="${entry.index}">${fixmeNoteOptionsHtml("Chọn ý nghĩa", state.fixmeSelections[entry.index])}</select></td>
    </tr>`).join("") : `<tr class="fixme-empty-row"><td colspan="9">Không có dòng phù hợp với filter hiện tại.</td></tr>`;

  $$('select[data-fixme-index]').forEach((select) => {
    select.addEventListener("change", () => {
      if (select.value) state.fixmeSelections[select.dataset.fixmeIndex] = select.value;
      else delete state.fixmeSelections[select.dataset.fixmeIndex];
      if ((state.fixmeSorts || []).some((sort) => sort.field === "note") || state.fixmeFilters.note) renderFixmes();
      else {
        updateFixmeToolbarState(filteredEntries);
        syncComparePreviewNoteControls();
      }
    });
  });
  $$("[data-fixme-check-index]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const index = checkbox.dataset.fixmeCheckIndex;
      if (checkbox.checked) state.fixmeCheckedRows.add(index);
      else state.fixmeCheckedRows.delete(index);
      updateFixmeToolbarState(filteredEntries);
      syncComparePreviewNoteControls();
      updateCompareBulkToolbarState();
    });
  });
  updateFixmeToolbarState(filteredEntries);
  syncComparePreviewNoteControls();
}

function refreshFixmeNoteOptions() {
  const bulkSelect = $("#fixme-bulk-note");
  const noteFilter = $("#fixme-filter-note");
  const compareBulkSelect = $("#compare-bulk-note");
  const previousBulkNote = bulkSelect.value;
  const previousNoteFilter = noteFilter.value;
  const previousCompareBulkNote = compareBulkSelect?.value || "";
  bulkSelect.innerHTML = fixmeNoteOptionsHtml("Chọn ý nghĩa");
  noteFilter.innerHTML = fixmeNoteOptionsHtml("Tất cả");
  if (compareBulkSelect) compareBulkSelect.innerHTML = fixmeNoteOptionsHtml("Chọn ý nghĩa");
  if (state.notes.some((note) => note.value === previousBulkNote)) bulkSelect.value = previousBulkNote;
  if (state.notes.some((note) => note.value === previousNoteFilter)) noteFilter.value = previousNoteFilter;
  if (compareBulkSelect && state.notes.some((note) => note.value === previousCompareBulkNote)) compareBulkSelect.value = previousCompareBulkNote;

  $$('select[data-fixme-index]').forEach((select) => {
    const currentValue = select.value;
    select.replaceChildren(new Option("Chọn ý nghĩa", ""));
    state.notes.forEach((note) => select.add(new Option(noteOptionLabel(note), note.value)));
    if (state.notes.some((note) => note.value === currentValue)) select.value = currentValue;
  });
  syncComparePreviewNoteControls();
  updateCompareBulkToolbarState();
  updateFixmeToolbarState();
  updateSqlDirtyButtons();
  if ($("#sql-export-all") && !state.sqlWorkspace.exportable) $("#sql-export-all").disabled = true;
}

function fixmeNoteOptionsHtml(placeholder, selectedValue = "") {
  return [`<option value="">${escapeHtml(placeholder)}</option>`, ...state.notes.map((note) =>
    `<option value="${escapeHtml(note.value)}" ${note.value === selectedValue ? "selected" : ""} title="Ghi chú: ${escapeHtml(note.value)}">${escapeHtml(noteOptionLabel(note))}</option>`
  )].join("");
}

function noteOptionLabel(note) {
  return String(note?.meaning || note?.value || "");
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
  const sorts = Array.isArray(state.fixmeSorts) ? state.fixmeSorts.filter((sort) => sort.field) : defaultFixmeSorts();
  if (!sorts.length) return entries;
  return entries
    .map((entry, order) => ({ entry, order }))
    .sort((left, right) => {
      for (const sort of sorts) {
        const direction = sort.direction === "desc" ? -1 : 1;
        const compared = compareFixmeSortValues(fixmeFieldValue(left.entry, sort.field), fixmeFieldValue(right.entry, sort.field), sort.field);
        if (compared) return compared * direction;
      }
      return left.order - right.order;
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
  const currentSorts = state.fixmeSortTouched && Array.isArray(state.fixmeSorts) ? [...state.fixmeSorts] : [];
  const existingIndex = currentSorts.findIndex((sort) => sort.field === field);
  if (existingIndex >= 0) {
    const existing = currentSorts[existingIndex];
    currentSorts[existingIndex] = { field, direction: existing.direction === "asc" ? "desc" : "asc" };
  } else {
    currentSorts.push({ field, direction: "asc" });
  }
  state.fixmeSortTouched = true;
  state.fixmeSorts = currentSorts;
  renderFixmes();
}

function fixmeSortForField(field) {
  const sorts = Array.isArray(state.fixmeSorts) ? state.fixmeSorts : [];
  const index = sorts.findIndex((sort) => sort.field === field);
  if (index < 0) return null;
  return { ...sorts[index], order: index + 1 };
}

function updateFixmeSortHeaders() {
  $$("[data-fixme-sort]").forEach((button) => {
    const sort = fixmeSortForField(button.dataset.fixmeSort);
    const direction = sort?.direction || "";
    button.classList.toggle("active", Boolean(sort));
    button.classList.toggle("asc", direction === "asc");
    button.classList.toggle("desc", direction === "desc");
    button.dataset.sortOrder = sort ? String(sort.order) : "";
    button.setAttribute("aria-sort", sort ? (direction === "desc" ? "descending" : "ascending") : "none");
    button.title = sort
      ? `Uu tien sort ${sort.order}: ${direction === "desc" ? "giam dan" : "tang dan"}`
      : "Bam de them vao thu tu sort";
  });
}

function clearFixmeSorts() {
  state.fixmeSortTouched = false;
  state.fixmeSorts = defaultFixmeSorts();
}
function clearFixmeFilters() {
  state.fixmeFilters = {};
  $$("[data-fixme-filter]").forEach((control) => { control.value = ""; });
  renderFixmes();
  saveUiCacheDebounced();
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
  $("#apply-fixmes-preview").disabled = busy || noteCount === 0;
  $("#refresh-compare-preview").disabled = busy || !state.compareView.cases?.length;
  $("#check-fixmes").disabled = busy || !state.compareView.cases?.length;
}

function resetFixmeReviewState() {
  state.fixmeFilters = {};
  state.fixmeSelections = {};
  state.fixmeCheckedRows = new Set();
  clearFixmeSorts();
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

function normalizeCompareView(view) {
  const current = state.compareView || {};
  const cases = Array.isArray(view?.cases) ? view.cases.map((caseItem, caseIndex) => ({
    id: String(caseItem.id || `case-${caseIndex}`),
    name: String(caseItem.name || `Case ${caseIndex + 1}`),
    workbooks: Array.isArray(caseItem.workbooks) ? caseItem.workbooks.map((workbook, workbookIndex) => ({
      id: String(workbook.id ?? workbookIndex),
      name: String(workbook.name || `Workbook ${workbookIndex + 1}`),
      path: String(workbook.path || ""),
      error: String(workbook.error || ""),
      sheets: Array.isArray(workbook.sheets) ? workbook.sheets.map((sheet, sheetIndex) => ({
        name: String(sheet.name || `Sheet${sheetIndex + 1}`),
      })) : [],
    })) : [],
  })) : [];
  return {
    cases,
    activeCaseId: current.activeCaseId || "",
    activeWorkbookId: current.activeWorkbookId || "",
    activeSheetName: current.activeSheetName || "",
    sheet: null,
    loadingKey: "",
  };
}

function renderComparePreview() {
  const card = $("#compare-preview-card");
  if (!card) return;
  const cases = state.compareView.cases || [];
  card.classList.toggle("hidden", cases.length === 0);
  if (!cases.length) {
    state.compareView.sheet = null;
    updateFixmeToolbarState();
    return;
  }

  const active = ensureActiveCompareSelection();
  const workbookCount = cases.reduce((total, caseItem) => total + (caseItem.workbooks?.length || 0), 0);
  $("#compare-preview-meta").textContent = `${workbookCount} workbook`;
  renderCompareCaseTabs(cases, active.caseItem);
  renderCompareWorkbookTabs(active.caseItem, active.workbook);
  renderCompareSheetTabs(active.workbook, active.sheet);
  updateFixmeToolbarState();

  if (!active.workbook) {
    showComparePreviewStatus("Case đang chọn chưa có file compare.");
    return;
  }
  if (active.workbook.error) {
    showComparePreviewStatus(`Không đọc được workbook: ${active.workbook.error}`);
    return;
  }
  if (!active.sheet) {
    showComparePreviewStatus("Workbook đang chọn chưa có sheet để hiển thị.");
    return;
  }
  loadActiveCompareSheet();
}

function ensureActiveCompareSelection() {
  const cases = state.compareView.cases || [];
  const caseItem = cases.find((item) => item.id === state.compareView.activeCaseId) || cases[0] || null;
  state.compareView.activeCaseId = caseItem?.id || "";

  const workbooks = caseItem?.workbooks || [];
  const workbook = workbooks.find((item) => item.id === state.compareView.activeWorkbookId) || workbooks[0] || null;
  state.compareView.activeWorkbookId = workbook?.id || "";

  const sheets = workbook?.sheets || [];
  const sheet = sheets.find((item) => item.name === state.compareView.activeSheetName) || sheets[0] || null;
  state.compareView.activeSheetName = sheet?.name || "";
  return { caseItem, workbook, sheet };
}

function renderCompareCaseTabs(cases, activeCase) {
  const container = $("#compare-case-tabs");
  container.innerHTML = cases.map((caseItem) =>
    `<button class="compare-tab ${caseItem.id === activeCase?.id ? "active" : ""}" data-compare-case="${escapeHtml(caseItem.id)}" type="button" title="${escapeHtml(caseItem.name)}">${escapeHtml(caseItem.name)}</button>`
  ).join("");
  $$("[data-compare-case]", container).forEach((button) => button.addEventListener("click", () => {
    state.compareView.activeCaseId = button.dataset.compareCase;
    state.compareView.activeWorkbookId = "";
    state.compareView.activeSheetName = "";
    state.compareView.sheet = null;
    renderComparePreview();
  }));
}

function renderCompareWorkbookTabs(caseItem, activeWorkbook) {
  const container = $("#compare-workbook-tabs");
  const workbooks = caseItem?.workbooks || [];
  container.innerHTML = workbooks.map((workbook) =>
    `<button class="compare-tab ${workbook.id === activeWorkbook?.id ? "active" : ""} ${workbook.error ? "error" : ""}" data-compare-workbook="${escapeHtml(workbook.id)}" type="button" title="${escapeHtml(workbook.path || workbook.name)}">${escapeHtml(workbook.name)}</button>`
  ).join("");
  $$("[data-compare-workbook]", container).forEach((button) => button.addEventListener("click", () => {
    state.compareView.activeWorkbookId = button.dataset.compareWorkbook;
    state.compareView.activeSheetName = "";
    state.compareView.sheet = null;
    renderComparePreview();
  }));
}

function renderCompareSheetTabs(workbook, activeSheet) {
  const container = $("#compare-sheet-tabs");
  const sheets = workbook?.sheets || [];
  container.innerHTML = sheets.map((sheet) =>
    `<button class="compare-tab ${sheet.name === activeSheet?.name ? "active" : ""}" data-compare-sheet="${escapeHtml(sheet.name)}" type="button" title="${escapeHtml(sheet.name)}">${escapeHtml(sheet.name)}</button>`
  ).join("");
  $$("[data-compare-sheet]", container).forEach((button) => button.addEventListener("click", () => {
    state.compareView.activeSheetName = button.dataset.compareSheet;
    state.compareView.sheet = null;
    renderComparePreview();
  }));
}

async function refreshComparePreview() {
  try {
    const response = await api("/api/compare-view");
    state.compareView = normalizeCompareView(response.compare_view);
    renderComparePreview();
    showToast("Đã tải lại view file compare.", "success");
  } catch (error) {
    showToast(error.message, "error", 7000);
  }
}

function reloadActiveCompareSheet() {
  if (!state.compareView.cases?.length) return;
  state.compareView.sheet = null;
  state.compareView.loadingKey = "";
  renderComparePreview();
}

async function loadActiveCompareSheet() {
  const active = ensureActiveCompareSelection();
  if (!active.workbook || !active.sheet || active.workbook.error) return;
  const key = `${active.workbook.id}\u001f${active.sheet.name}`;
  if (state.compareView.sheet?.key === key) {
    renderCompareSheet();
    return;
  }
  if (state.compareView.loadingKey === key) return;
  state.compareView.loadingKey = key;
  showComparePreviewStatus(`Đang tải sheet ${active.sheet.name}...`);
  try {
    const sheet = await api(`/api/compare-view/sheet?workbook_id=${encodeURIComponent(active.workbook.id)}&sheet=${encodeURIComponent(active.sheet.name)}`);
    if (state.compareView.loadingKey !== key) return;
    state.compareView.sheet = { ...sheet, key };
    state.compareView.loadingKey = "";
    renderCompareSheet();
  } catch (error) {
    if (state.compareView.loadingKey !== key) return;
    state.compareView.loadingKey = "";
    showComparePreviewStatus(error.message);
  }
}

function showComparePreviewStatus(message) {
  $("#compare-preview-status").textContent = message;
  $("#compare-preview-status").classList.remove("hidden");
  $("#compare-preview-table").classList.add("hidden");
}

function renderCompareSheet() {
  const sheet = state.compareView.sheet;
  const active = ensureActiveCompareSelection();
  if (!sheet || sheet.key !== `${active.workbook?.id}\u001f${active.sheet?.name}`) return;
  const table = $("#compare-preview-table");
  const widths = Array.isArray(sheet.column_widths) ? sheet.column_widths : [];
  const letters = Array.isArray(sheet.column_letters) ? sheet.column_letters : [];
  const rows = Array.isArray(sheet.rows) ? sheet.rows : [];
  table.innerHTML = `
    <colgroup>
      <col class="compare-row-number-col">
      ${widths.map(() => `<col class="compare-value-col">`).join("")}
      <col class="compare-check-col">
    </colgroup>
    <thead><tr><th class="compare-corner"></th>${letters.map((letter) => `<th>${escapeHtml(letter)}</th>`).join("")}<th class="compare-check-header"></th></tr></thead>
    <tbody>${rows.map((row) => `
      <tr>
        <th class="compare-row-number">${escapeHtml(row.number)}</th>
        ${(row.cells || []).map((cell) => compareCellHtml(cell, row)).join("")}
        ${compareCheckCellHtml(row)}
      </tr>`).join("")}</tbody>`;
  $("#compare-preview-status").classList.add("hidden");
  table.classList.remove("hidden");
  bindCompareCellCopyControls(table);
  bindCompareFixmeControls();
  updateCompareBulkToolbarState();
}

function compareCellHtml(cell, row) {
  const fixmeIndices = Array.isArray(cell.fixme_indices) ? cell.fixme_indices : [];
  const classes = ["compare-cell", ...compareCellColorClasses(cell, row)];
  if (Number(cell?.row || row?.number || 0) === 2) classes.push("compare-header-cell");
  if (compareCellBelongsToDiffPair(cell, row)) classes.push("compare-diff-cell");
  if (cell.style?.wrap) classes.push("wrap");
  if (fixmeIndices.length) classes.push("compare-fixme-cell");
  return `<td class="${classes.join(" ")}">${compareCellContent(cell, fixmeIndices)}</td>`;
}

function compareCheckCellHtml(row) {
  const rowNumber = Number(row?.number || 0);
  if (rowNumber === 2) {
    return `<td class="compare-check-cell compare-check-all-cell"><input id="compare-check-visible" type="checkbox" title="Chon/bo chon tat ca dong sai khac dang hien thi"></td>`;
  }
  const indices = compareRowFixmeIndices(row);
  if (!indices.length) return `<td class="compare-check-cell"></td>`;
  const checked = indices.every((index) => state.fixmeCheckedRows.has(String(index))) ? "checked" : "";
  return `<td class="compare-check-cell"><input type="checkbox" data-compare-fixme-check="${escapeHtml(indices.join(","))}" ${checked}></td>`;
}

function compareRowFixmeIndices(row) {
  const indices = [];
  (row?.cells || []).forEach((cell) => {
    if (Array.isArray(cell.fixme_indices)) indices.push(...cell.fixme_indices);
  });
  return uniqueStrings(indices.map(String));
}

function compareCellColorClasses(cell, row) {
  const colorStyle = compareCellColorStyle(cell, row);
  const classes = [];
  const background = safeCssColor(colorStyle.background);
  const color = safeCssColor(colorStyle.color);
  const backgroundClass = compareColorClass("bg", background);
  const colorClass = compareColorClass("text", color);
  if (backgroundClass) classes.push(backgroundClass);
  if (colorClass) classes.push(colorClass);
  return classes;
}

function compareColorClass(kind, color) {
  const normalized = String(color || "").toUpperCase();
  if (kind === "bg" && normalized === COMPARE_PREVIEW_COLORS.a1Background) return "compare-bg-a1";
  if (kind === "bg" && normalized === COMPARE_PREVIEW_COLORS.headerBackground) return "compare-bg-header";
  if (kind === "bg" && normalized === COMPARE_PREVIEW_COLORS.nameBackground) return "compare-bg-name";
  if (kind === "bg" && normalized === COMPARE_PREVIEW_COLORS.diffBackground) return "compare-bg-diff";
  if (kind === "text" && normalized === COMPARE_PREVIEW_COLORS.a1Text) return "compare-text-a1";
  if (kind === "text" && normalized === COMPARE_PREVIEW_COLORS.headerText) return "compare-text-header";
  if (kind === "text" && normalized === COMPARE_PREVIEW_COLORS.diffText) return "compare-text-diff";
  if (kind === "text" && normalized === COMPARE_PREVIEW_COLORS.text) return "compare-text-normal";
  return "";
}

function compareCellColorStyle(cell, row) {
  const style = cell?.style || {};
  const fallback = compareCellFallbackColors(cell, row);
  return {
    background: style.background || fallback.background || "",
    color: style.color || fallback.color || "",
  };
}

function compareCellFallbackColors(cell, row) {
  const rowNumber = Number(cell?.row || row?.number || 0);
  const column = Number(cell?.column || 0);
  const value = String(cell?.value || "").trim();
  if (rowNumber === 1 && column === 1) {
    return { background: COMPARE_PREVIEW_COLORS.a1Background, color: COMPARE_PREVIEW_COLORS.a1Text };
  }
  if (rowNumber === 2 && value) {
    return { background: COMPARE_PREVIEW_COLORS.headerBackground, color: COMPARE_PREVIEW_COLORS.headerText };
  }
  if (rowNumber >= 3 && (column === 1 || column === 2)) {
    return { background: COMPARE_PREVIEW_COLORS.nameBackground, color: COMPARE_PREVIEW_COLORS.text };
  }
  if (rowNumber >= 3 && compareCellBelongsToDiffPair(cell, row)) {
    return { background: COMPARE_PREVIEW_COLORS.diffBackground, color: COMPARE_PREVIEW_COLORS.diffText };
  }
  if (Array.isArray(cell?.fixme_indices) && cell.fixme_indices.length) {
    return { color: COMPARE_PREVIEW_COLORS.text };
  }
  return {};
}

function compareCellBelongsToDiffPair(cell, row) {
  const column = Number(cell?.column || 0);
  if (column < 3) return false;
  const pairStart = column - ((column - 3) % 2);
  if (!compareHeaderCellValue(pairStart) || !compareHeaderCellValue(pairStart + 1)) return false;
  const cells = Array.isArray(row?.cells) ? row.cells : [];
  const left = cells.find((item) => Number(item.column) === pairStart);
  const right = cells.find((item) => Number(item.column) === pairStart + 1);
  if (!left || !right) return false;
  return String(left.value ?? "") !== String(right.value ?? "");
}

function compareHeaderCellValue(column) {
  const headerRow = (state.compareView.sheet?.rows || []).find((row) => Number(row.number) === 2);
  const headerCell = headerRow?.cells?.find((cell) => Number(cell.column) === column);
  return String(headerCell?.value || "").trim();
}

function safeCssColor(value) {
  const text = String(value || "").trim();
  return /^#[0-9a-f]{6}$/i.test(text) ? text : "";
}

function compareCellContent(cell, fixmeIndices) {
  if (fixmeIndices.length) {
    const workbookValue = String(cell.value || "");
    const existingNote = workbookValue && workbookValue !== "FIXME" && !fixmeIndices.some((index) => state.fixmeSelections[index])
      ? `<div class="compare-existing-note">${escapeHtml(workbookValue)}</div>`
      : "";
    return `<select data-compare-fixme-indices="${escapeHtml(fixmeIndices.join(","))}" data-compare-fixme-value="${escapeHtml(workbookValue)}" ${state.notes.length ? "" : "disabled"}>${compareFixmeOptionsHtml(fixmeIndices, workbookValue)}</select>${existingNote}`;
  }
  return `<textarea class="compare-cell-value" readonly title="Click để chọn/copy value">${escapeHtml(cell.value)}</textarea>`;
}

function bindCompareCellCopyControls(root) {
  $$(".compare-cell-value", root).forEach((textarea) => {
    textarea.addEventListener("focus", () => textarea.select());
    textarea.addEventListener("click", () => textarea.select());
  });
}

function compareFixmeOptionsHtml(indices, workbookValue = "") {
  let selectedValues = uniqueStrings(indices.map((index) => state.fixmeSelections[index]).filter(Boolean));
  if (!selectedValues.length && workbookValue && workbookValue !== "FIXME") {
    const noteValues = new Set(state.notes.map((note) => note.value));
    selectedValues = uniqueStrings(workbookValue.split(/\r?\n/).map((value) => value.trim()).filter((value) => noteValues.has(value)));
  }
  const mixed = selectedValues.length > 1;
  return [
    mixed ? `<option value="__mixed" selected>Nhiều note</option>` : "",
    `<option value="">Chọn ý nghĩa</option>`,
    ...state.notes.map((note) =>
      `<option value="${escapeHtml(note.value)}" ${selectedValues.length === 1 && note.value === selectedValues[0] ? "selected" : ""} title="Ghi chú: ${escapeHtml(note.value)}">${escapeHtml(noteOptionLabel(note))}</option>`
    ),
  ].join("");
}

function bindCompareFixmeControls() {
  $("#compare-check-visible")?.addEventListener("change", toggleVisibleCompareFixmeRows);
  $$("[data-compare-fixme-check]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      compareFixmeIndicesFromSelect(checkbox).forEach((index) => {
        if (checkbox.checked) state.fixmeCheckedRows.add(String(index));
        else state.fixmeCheckedRows.delete(String(index));
      });
      syncFixmeRowChecks();
      updateFixmeToolbarState();
      updateCompareBulkToolbarState();
    });
  });
  $$("[data-compare-fixme-indices]").forEach((select) => {
    select.addEventListener("change", () => {
      if (select.value === "__mixed") return;
      const indices = compareFixmeIndicesFromSelect(select);
      indices.forEach((index) => {
        if (select.value) state.fixmeSelections[index] = select.value;
        else delete state.fixmeSelections[index];
      });
      renderFixmes();
      syncComparePreviewNoteControls();
    });
  });
  syncComparePreviewNoteControls();
}

function visibleCompareFixmeIndices() {
  const indices = [];
  $$("[data-compare-fixme-check]").forEach((checkbox) => {
    indices.push(...compareFixmeIndicesFromSelect(checkbox));
  });
  return uniqueStrings(indices.map(String));
}

function toggleVisibleCompareFixmeRows(event) {
  visibleCompareFixmeIndices().forEach((index) => {
    if (event.target.checked) state.fixmeCheckedRows.add(index);
    else state.fixmeCheckedRows.delete(index);
  });
  syncFixmeRowChecks();
  syncComparePreviewNoteControls();
  updateFixmeToolbarState();
  updateCompareBulkToolbarState();
}

function assignCompareBulkNote() {
  const note = valueOf("compare-bulk-note");
  const targets = visibleCompareFixmeIndices().filter((index) => state.fixmeCheckedRows.has(index));
  if (!note) {
    showToast("Vui lòng chọn note cần gán.", "error");
    $("#compare-bulk-note")?.focus();
    return;
  }
  if (!targets.length) {
    showToast("Vui lòng tick ít nhất một dòng sai khác trong preview.", "error");
    return;
  }
  targets.forEach((index) => { state.fixmeSelections[index] = note; });
  renderFixmes();
  syncComparePreviewNoteControls();
  updateCompareBulkToolbarState();
  showToast(`Đã gán note cho ${targets.length} dòng đã tick.`, "success");
}

function clearCompareRowSelection() {
  visibleCompareFixmeIndices().forEach((index) => state.fixmeCheckedRows.delete(index));
  syncFixmeRowChecks();
  syncComparePreviewNoteControls();
  updateFixmeToolbarState();
  updateCompareBulkToolbarState();
}

function updateCompareBulkToolbarState() {
  const toolbar = $("#compare-bulk-tools");
  if (!toolbar) return;
  const visible = visibleCompareFixmeIndices();
  const checkedCount = visible.filter((index) => state.fixmeCheckedRows.has(index)).length;
  toolbar.classList.toggle("hidden", visible.length === 0);
  $("#compare-checked-count").textContent = `${checkedCount} / ${visible.length} dòng đã tick`;
  const checkAll = $("#compare-check-visible");
  if (checkAll) {
    checkAll.checked = visible.length > 0 && checkedCount === visible.length;
    checkAll.indeterminate = checkedCount > 0 && checkedCount < visible.length;
  }
  const busy = document.body.classList.contains("is-busy");
  $("#compare-bulk-assign").disabled = busy || checkedCount === 0 || !valueOf("compare-bulk-note");
  $("#compare-bulk-clear").disabled = busy || checkedCount === 0;
}

function syncFixmeRowChecks() {
  $$("[data-fixme-check-index]").forEach((checkbox) => {
    checkbox.checked = state.fixmeCheckedRows.has(String(checkbox.dataset.fixmeCheckIndex));
  });
}

function compareFixmeIndicesFromSelect(select) {
  return String(select.dataset.compareFixmeIndices || select.dataset.compareFixmeCheck || "")
    .split(",")
    .map((value) => Number(value))
    .filter((value) => Number.isInteger(value) && value >= 0);
}

function syncComparePreviewNoteControls() {
  $$("[data-compare-fixme-check]").forEach((checkbox) => {
    const indices = compareFixmeIndicesFromSelect(checkbox);
    const checkedCount = indices.filter((index) => state.fixmeCheckedRows.has(String(index))).length;
    checkbox.checked = indices.length > 0 && checkedCount === indices.length;
    checkbox.indeterminate = checkedCount > 0 && checkedCount < indices.length;
  });
  $$("[data-compare-fixme-indices]").forEach((select) => {
    const indices = compareFixmeIndicesFromSelect(select);
    select.innerHTML = compareFixmeOptionsHtml(indices, select.dataset.compareFixmeValue || "");
    select.disabled = state.notes.length === 0;
    const existingNote = select.nextElementSibling;
    if (existingNote?.classList.contains("compare-existing-note")) {
      existingNote.classList.toggle("hidden", indices.some((index) => state.fixmeSelections[index]));
    }
  });
  updateCompareBulkToolbarState();
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
  saveUiCacheDebounced();
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

function handleSyncTableFilterKeydown(event) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  if (checked("sync-all-tables")) return;
  const rawInput = valueOf("sync-table-filter");
  if (!rawInput) return;
  const result = addSelectedSyncTables(rawInput.split(","));
  if (!result.added.length && !result.missing.length && !rawInput.includes(",")) {
    const filter = rawInput.toLocaleLowerCase("vi");
    const filtered = state.sourceTables.filter((name) => !state.selectedTables.includes(name) && name.toLocaleLowerCase("vi").includes(filter));
    if (filtered.length === 1) result.added.push(...addSelectedSyncTables(filtered).added);
  }
  if (result.added.length) {
    $("#sync-table-filter").value = "";
    renderTables();
    saveUiCacheDebounced();
  }
  if (result.missing.length) {
    showToast(`Không tìm thấy table: ${result.missing.join(", ")}`, "error", 5500);
  } else if (result.added.length) {
    showToast(`Đã chọn thêm ${result.added.length} table.`, "success", 2600);
  }
}

function addSelectedSyncTables(names) {
  const knownTables = new Map(state.sourceTables.map((name) => [name.toLocaleLowerCase("vi"), name]));
  const selectedKeys = new Set(state.selectedTables.map((name) => name.toLocaleLowerCase("vi")));
  const added = [];
  const missing = [];
  names.map((name) => String(name ?? "").trim()).filter(Boolean).forEach((name) => {
    const canonical = knownTables.get(name.toLocaleLowerCase("vi")) || (!state.sourceTables.length ? name : "");
    if (!canonical) {
      missing.push(name);
      return;
    }
    const key = canonical.toLocaleLowerCase("vi");
    if (selectedKeys.has(key)) return;
    selectedKeys.add(key);
    state.selectedTables.push(canonical);
    added.push(canonical);
  });
  return { added, missing };
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
      addSelectedSyncTables([button.dataset.addTable]);
      renderTables();
      saveUiCacheDebounced();
    }));
  }
  if (!state.selectedTables.length) {
    selectedContainer.innerHTML = `<p>Chưa chọn table.</p>`;
  } else {
    selectedContainer.innerHTML = state.selectedTables.map((name) => `<div class="table-tag"><span>${escapeHtml(name)}</span><button type="button" data-remove-table="${escapeHtml(name)}">×</button></div>`).join("");
    $$('[data-remove-table]', selectedContainer).forEach((button) => button.addEventListener("click", () => {
      state.selectedTables = state.selectedTables.filter((name) => name !== button.dataset.removeTable);
      renderTables();
      saveUiCacheDebounced();
    }));
  }
  const count = allMode ? state.sourceTables.length : state.selectedTables.length;
  $("#selected-table-count").textContent = `${count} table`;
}

function resetSyncProgress(tableNames = []) {
  state.syncProgress = {
    tableNames,
    current: 0,
    total: null,
    speedRowsPerSecond: null,
    etaSeconds: null,
    inserted: 0,
    updated: 0,
    deleted: 0,
    table: "",
    tableIndex: 0,
    totalTables: tableNames.length || 0,
  };
  renderSyncProgress();
}

function consumeSyncProgressLog(line) {
  const prefix = "__SYNC_PROGRESS__";
  if (!line.startsWith(prefix)) return false;
  try {
    const payload = JSON.parse(line.slice(prefix.length));
    state.syncProgress = {
      ...(state.syncProgress || {}),
      table: payload.table || "",
      current: Number(payload.current || 0),
      total: typeof payload.total === "number" ? payload.total : null,
      tableIndex: Number(payload.table_index || 0),
      totalTables: Number(payload.total_tables || 0),
      speedRowsPerSecond: typeof payload.speed_rows_per_second === "number" ? payload.speed_rows_per_second : null,
      etaSeconds: typeof payload.eta_seconds === "number" ? payload.eta_seconds : null,
      inserted: Number(payload.inserted || 0),
      updated: Number(payload.updated || 0),
      deleted: Number(payload.deleted || 0),
      unchanged: Number(payload.unchanged || 0),
      done: !!payload.done,
    };
    renderSyncProgress();
  } catch (_error) {
    return false;
  }
  return true;
}

function renderSyncProgress() {
  const panel = $("#sync-progress-panel");
  if (!panel || !state.syncProgress) return;
  const progress = state.syncProgress;
  panel.classList.remove("hidden");
  const total = progress.total;
  const current = progress.current || 0;
  const percent = total ? Math.min(100, Math.round((current / total) * 100)) : 0;
  $("#sync-progress-title").textContent = progress.table
    ? `Table ${progress.tableIndex || "?"}/${progress.totalTables || "?"}: ${progress.table}`
    : "Sync progress";
  $("#sync-progress-percent").textContent = total ? `${percent}%` : "Đang tính...";
  $("#sync-progress-bar").style.width = total ? `${percent}%` : "6%";
  $("#sync-progress-records").textContent = `${formatNumber(current)} / ${total == null ? "?" : formatNumber(total)}`;
  $("#sync-progress-speed").textContent = progress.speedRowsPerSecond
    ? `${formatNumber(progress.speedRowsPerSecond)} rows/s`
    : "Sau 100 rows";
  $("#sync-progress-eta").textContent = progress.etaSeconds == null ? "--" : formatDuration(progress.etaSeconds);
  $("#sync-progress-change").textContent = `${formatNumber(progress.inserted || 0)} / ${formatNumber(progress.updated || 0)} / ${formatNumber(progress.deleted || 0)}`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("vi-VN", { maximumFractionDigits: 2 });
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(Number(totalSeconds || 0)));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remain = seconds % 60;
  if (hours) return `${hours}h ${minutes}m ${remain}s`;
  if (minutes) return `${minutes}m ${remain}s`;
  return `${remain}s`;
}

function formatDateTime(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return String(value || "");
  const pad = (number) => String(number).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + ` ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function jobDuration(job) {
  const startedAt = job?.started_at || job?.created_at;
  const finishedAt = job?.finished_at || new Date().toISOString();
  const start = startedAt ? new Date(startedAt) : null;
  const finish = finishedAt ? new Date(finishedAt) : null;
  if (!start || !finish || Number.isNaN(start.getTime()) || Number.isNaN(finish.getTime())) return "Không xác định";
  const elapsedMs = Math.max(0, finish.getTime() - start.getTime());
  if (elapsedMs > 0 && elapsedMs < 1000) return "dưới 1s";
  return formatDuration(elapsedMs / 1000);
}

function appendJobStartLog(job) {
  if (!job?.id || state.loggedJobStarts.has(job.id)) return;
  state.loggedJobStarts.add(job.id);
  appendActivityLogLines([
    `[${formatDateTime(job.started_at || job.created_at)}] Bắt đầu tác vụ: ${job.label || job.action || ""}`,
  ]);
}

function appendJobFinishLog(job, statusText, detail = "") {
  appendActivityLogLines([
    `[${formatDateTime(job?.finished_at)}] Kết thúc tác vụ: ${statusText}`,
    `Thời gian xử lý: ${jobDuration(job)}`,
    ...(detail ? [`Kết quả: ${detail}`] : []),
    ACTIVITY_LOG_SEPARATOR,
  ]);
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
    appendJobStartLog(state.job);
    setBusy(true);
    schedulePoll(100);
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function cancelCurrentJob() {
  if (!state.job || !["queued", "running"].includes(state.job.state)) return;
  const button = $("#cancel-job");
  button.disabled = true;
  button.textContent = "Đang hủy...";
  try {
    const response = await api("/api/jobs/cancel", {
      method: "POST",
      body: { job_id: state.job.id },
    });
    if (response.job) {
      state.job = response.job;
      updateJobState(response.job);
    }
    showToast(response.cancel_requested ? "Đã gửi yêu cầu hủy tác vụ." : "Không có tác vụ đang chạy.", "success");
  } catch (error) {
    button.disabled = false;
    button.textContent = "Hủy tác vụ";
    showToast(error.message, "error", 7000);
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
    appendJobStartLog(job);
    return;
  }
  setBusy(false);
  if (state.handledJobs.has(job.id)) {
    const finishedKind = job.state === "succeeded" ? "success" : (job.state === "cancelled" ? "idle" : "error");
    const finishedText = job.state === "succeeded" ? "Hoàn tất" : (job.state === "cancelled" ? "Đã hủy" : "Thất bại");
    setJobVisual(finishedKind, finishedText);
    return;
  }
  state.handledJobs.add(job.id);
  if (job.state === "cancelled") {
    setJobVisual("idle", "Đã hủy");
    $("#activity-panel").classList.remove("collapsed");
    updateActivityToggleTitle();
    appendJobFinishLog(job, "Đã hủy", job.error || "Tác vụ đã được hủy.");
    showToast(job.error || "Tác vụ đã được hủy.", "success", 5500);
    return;
  }
  if (job.state === "failed") {
    setJobVisual("error", "Tác vụ thất bại");
    $("#activity-panel").classList.remove("collapsed");
    updateActivityToggleTitle();
    appendJobFinishLog(job, "Thất bại", job.error || "Tác vụ thất bại.");
    showToast(job.error || "Tác vụ thất bại.", "error", 7000);
    return;
  }
  setJobVisual("success", "Hoàn tất");
  consumeJobResult(job);
  const message = summaryMessage(job);
  appendJobFinishLog(job, "Hoàn tất", message);
  showToast(message, "success", 5500);
}

function consumeJobResult(job) {
  const result = job.result || {};
  if (result.update_compare_keys) {
    state.bootstrap.update_compare_keys = result.update_compare_keys;
    renderCompareKeys();
    $("#compare-key-details").open = true;
  }
  if (result.connection) rememberDatabaseHistory(result.connection);
  if (Array.isArray(result.fixmes)) {
    state.fixmes = result.fixmes;
    state.fixmeScanLocations = [];
    $("#fixme-scan-result")?.removeAttribute("data-checked");
    resetFixmeReviewState();
    renderFixmes();
    renderFixmeScanResult();
  }
  if (result.compare_view) {
    state.compareView = normalizeCompareView(result.compare_view);
    renderComparePreview();
    if (state.compareView.cases.length && $("#page-compare.active, #page-folder-compare.active")) {
      showPage("compare", true);
      $("#tab-compare-preview-card")?.click();
    }
  }
  if (Array.isArray(result.fixme_scan_locations)) {
    state.fixmeScanLocations = result.fixme_scan_locations;
    $("#fixme-scan-result")?.setAttribute("data-checked", "1");
    renderFixmeScanResult();
  }
  if (job.action === "db_test" && result.verified) {
    state.bootstrap.database_connections = { ...state.bootstrap.database_connections, [result.role]: result.connection };
    renderCompareKeys();
    setVerified(result.role, true);
    if (result.role === "main" && Array.isArray(result.tables)) {
      state.sourceTables = result.tables;
      const tableLookup = new Map(state.sourceTables.map((name) => [name.toLocaleLowerCase("vi"), name]));
      state.selectedTables = uniqueStrings(state.selectedTables.map((name) => tableLookup.get(String(name).toLocaleLowerCase("vi")) || "").filter(Boolean));
      renderTables();
      saveUiCacheDebounced();
    }
  }
  if (job.action === "db_list_databases" && Array.isArray(result.databases)) {
    state.databaseNames[result.role] = result.databases;
    renderDatabaseNameList(result.role);
    if (!valueOf(`db-${result.role}-database`) && result.databases.length) {
      $(`#db-${result.role}-database`).value = result.databases[0];
      saveUiCacheDebounced();
    }
  }
  if (job.action === "sql_format" || job.action === "sql_analyze" || job.action === "sql_load_excel") {
    if (job.action === "sql_load_excel" && result.source_sql) {
      $("#sql-input").value = result.source_sql;
      markSqlWorkspaceStale();
      saveUiCacheDebounced();
    }
    if (result.formatted_sql) {
      $("#sql-input").value = result.formatted_sql;
      markSqlWorkspaceStale();
      saveUiCacheDebounced();
    }
    $("#sql-statement-count").textContent = `${result.statement_count || 0} statement`;
    if (job.action === "sql_analyze") renderSqlAnalysis(result);
    else {
      const analysisPanel = $("#sql-analysis");
      analysisPanel.classList.add("hidden");
      analysisPanel.open = false;
      clearSqlAnalysisTables();
    }
  }
  if (job.action === "db_sql_execute") {
    renderSqlWorkspace(result);
    if (result.analysis) renderSqlAnalysis(result.analysis);
    else {
      const analysisPanel = $("#sql-analysis");
      analysisPanel.classList.add("hidden");
      analysisPanel.open = false;
      clearSqlAnalysisTables();
    }
  }
  if (job.action === "db_sql_update") {
    state.sqlWorkspace.dirty = {};
    markSqlWorkspaceStale();
  }
  if (job.action === "apply_fixmes") {
    reloadActiveCompareSheet();
  }
}

function renderFixmeScanResult() {
  const container = $("#fixme-scan-result");
  if (!container) return;
  const locations = Array.isArray(state.fixmeScanLocations) ? state.fixmeScanLocations : [];
  if (!locations.length) {
    if (container.dataset.checked === "1") {
      container.classList.remove("hidden", "has-fixmes");
      container.innerHTML = `<strong>Không còn FIXME.</strong><span>Tất cả file compare hiện tại đã được xử lý.</span>`;
    } else {
      container.classList.add("hidden");
      container.innerHTML = "";
    }
    return;
  }
  container.dataset.checked = "1";
  container.classList.remove("hidden");
  container.classList.add("has-fixmes");
  container.innerHTML = `
    <strong>Còn ${locations.length} cell FIXME</strong>
    <div class="table-wrap fixme-scan-table-wrap">
      <table class="fixme-scan-table">
        <thead><tr><th>Case</th><th>Workbook</th><th>Sheet</th><th>Cell</th><th>Value</th></tr></thead>
        <tbody>${locations.map((item) => `
          <tr>
            <td>${escapeHtml(item.case_folder_name)}</td>
            <td title="${escapeHtml(item.workbook_path)}">${escapeHtml(item.workbook_name)}</td>
            <td>${escapeHtml(item.sheet_name)}</td>
            <td>${escapeHtml(item.cell)}</td>
            <td>${escapeHtml(item.value)}</td>
          </tr>`).join("")}</tbody>
      </table>
    </div>`;
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
    showToast("Đã tắt chế độ ghi DB.", "success");
    return;
  }
  if (!requireVerified("main")) return;
  const confirmed = await confirmAction(
    "Bật chế độ ghi DB cho SQL editor?",
    "DDL/DML sẽ được phép chạy trong 30 phút cho Database 1 hiện tại. Chạy toàn bộ sẽ rollback nếu có lỗi khi database hỗ trợ transaction; một số DDL/MySQL/Oracle có thể implicit commit."
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
    showToast("Chế độ ghi DB đã bật.", "success");
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
  button.textContent = enabled ? "Ghi DB ON" : "Ghi DB OFF";
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

async function copyCurrentSql() {
  const sql = $("#sql-input").value;
  if (!sql.trim()) return;
  await writeClipboardText(sql, $("#sql-input"));
  showToast("Đã sao chép SQL trong editor.", "success");
}

async function copyAnalyzedSqlTables() {
  if (!state.sqlAnalysisTables.length) return;
  await writeClipboardText(state.sqlAnalysisTables.join(", "));
  showToast(`Đã sao chép ${state.sqlAnalysisTables.length} table database.`, "success");
}

async function writeClipboardText(text, fallbackElement = null) {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(text);
  } catch (_error) {
    const temporaryElement = !fallbackElement;
    const output = fallbackElement || document.createElement("textarea");
    if (temporaryElement) {
      output.value = text;
      output.style.position = "fixed";
      output.style.left = "-9999px";
      output.style.top = "0";
      document.body.appendChild(output);
    }
    output.focus();
    output.select();
    document.execCommand("copy");
    if (temporaryElement) output.remove();
  }
}

function renderSqlAnalysis(result) {
  const tables = Array.isArray(result.tables) ? result.tables : [];
  const conditions = Array.isArray(result.conditions) ? result.conditions : [];
  const ctes = Array.isArray(result.ctes) ? result.ctes : [];
  const subqueries = Array.isArray(result.subqueries) ? result.subqueries : [];
  const projections = Array.isArray(result.projections) ? result.projections : [];
  const clauses = Array.isArray(result.clauses) ? result.clauses : [];

  const analysisPanel = $("#sql-analysis");
  analysisPanel.classList.remove("hidden");
  analysisPanel.open = false;
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
  state.sqlAnalysisTables = sqlDatabaseTableNames(tables);
  updateCopySqlTablesButton();

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

function sqlDatabaseTableNames(tables) {
  const seen = new Set();
  const result = [];
  (Array.isArray(tables) ? tables : []).forEach((item) => {
    if (item?.source_type !== "TABLE") return;
    const tableName = String(item.qualified_name || item.name || "").trim();
    if (!tableName) return;
    const key = tableName.toLocaleLowerCase("vi");
    if (seen.has(key)) return;
    seen.add(key);
    result.push(tableName);
  });
  return result;
}

function updateCopySqlTablesButton() {
  const button = $("#copy-sql-tables");
  if (!button) return;
  button.disabled = state.sqlAnalysisTables.length === 0;
  button.textContent = state.sqlAnalysisTables.length
    ? `Sao chép ${state.sqlAnalysisTables.length} table`
    : "Sao chép table";
}

function clearSqlAnalysisTables() {
  state.sqlAnalysisTables = [];
  updateCopySqlTablesButton();
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
  bindSqlJoinTooltips(container);
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
  const legend = `
    <div class="sql-usage-legend">
      <span class="usage-join-sample">JOIN group</span>
      <span class="usage-where-sample">WHERE</span>
      <span class="usage-select-sample">SELECT</span>
      <small>Ưu tiên màu: JOIN &gt; WHERE &gt; SELECT</small>
    </div>`;
  container.innerHTML = legend + sources.map((source) => {
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
        ${renderSqlDataGrid(mergeSqlSourcePageUsage(source.first_page, source.columns || []), { editable: source.updateable, relationId: source.relation_id })}
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
  bindSqlJoinTooltips(container);
  if (!exactSources.length) {
    state.sqlWorkspace.exportable = false;
    $("#sql-export-all").disabled = true;
  }
}

function renderSqlDataGrid(page, options = {}) {
  const columns = Array.isArray(page.columns) ? page.columns : [];
  const rows = Array.isArray(page.rows) ? page.rows : [];
  if (!columns.length) return sqlEmpty("Không có metadata column.");
  const headerIndexes = columns.map((column) => `<th class="sql-index-header">#${Number(column.index || 0)}</th>`).join("");
  const headerNames = columns.map((column) => {
    return `<th${sqlJoinTooltipAttrs(column)}${sqlUsageStyle(column)} class="${sqlUsageClass(column)}">
      <span class="sql-col-name">${column.is_primary_key ? "🔑 " : ""}${escapeHtml(column.name || "")}</span>
      <small>${escapeHtml(column.data_type || "")}${sqlUsageLabel(column) ? ` · ${escapeHtml(sqlUsageLabel(column))}` : ""}</small>
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

function sqlUsageStyle(column) {
  const color = column.color || fallbackSqlUsageColor(column);
  if (!color) return "";
  const headerBg = usageBackgroundFor(column, color, 0.34);
  const bodyBg = usageBackgroundFor(column, color, 0.16);
  const bodyAltBg = usageBackgroundFor(column, color, 0.22);
  const bodyHoverBg = usageBackgroundFor(column, color, 0.30);
  const accent = normalizeHexColor(color) || color;
  return ` style="--usage-color:${escapeHtml(accent)};--usage-header-bg:${escapeHtml(headerBg)};--usage-body-bg:${escapeHtml(bodyBg)};--usage-body-alt-bg:${escapeHtml(bodyAltBg)};--usage-body-hover-bg:${escapeHtml(bodyHoverBg)};--usage-accent:${escapeHtml(accent)}"`;
}

function fallbackSqlUsageColor(column) {
  const usage = String(column.usage || "").toUpperCase();
  if (usage === "SELECT") return "#facc15";
  if (usage === "WHERE") return "#92d050";
  if (usage === "JOIN") return "#60a5fa";
  return "";
}

function usageBackgroundFor(column, color, ratio) {
  const usage = String(column.usage || "").toUpperCase();
  if (usage === "SELECT") {
    if (ratio >= 0.30) return "#fff3a6";
    if (ratio >= 0.20) return "#fff8c9";
    return "#fffde5";
  }
  if (usage === "WHERE") {
    if (ratio >= 0.30) return "#d7efc9";
    if (ratio >= 0.20) return "#e5f6dc";
    return "#f1faeb";
  }
  return mixHexColor(color, "#ffffff", ratio) || color;
}

function normalizeHexColor(color) {
  const text = String(color || "").trim();
  const short = text.match(/^#([0-9a-f]{3})$/i);
  if (short) return `#${short[1].split("").map((item) => item + item).join("")}`.toLowerCase();
  const long = text.match(/^#([0-9a-f]{6})$/i);
  return long ? `#${long[1]}`.toLowerCase() : "";
}

function mixHexColor(color, base, ratio) {
  const source = normalizeHexColor(color);
  const target = normalizeHexColor(base);
  if (!source || !target) return "";
  const amount = Math.min(1, Math.max(0, Number(ratio) || 0));
  const parse = (hex) => [1, 3, 5].map((start) => Number.parseInt(hex.slice(start, start + 2), 16));
  const sourceRgb = parse(source);
  const targetRgb = parse(target);
  const mixed = sourceRgb.map((value, index) => Math.round(value * amount + targetRgb[index] * (1 - amount)));
  return `#${mixed.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function mergeSqlSourcePageUsage(page, sourceColumns) {
  const pageColumns = Array.isArray(page?.columns) ? page.columns : [];
  const sourceList = Array.isArray(sourceColumns) ? sourceColumns : [];
  const usageByName = new Map(sourceList.map((column) => [String(column.name || "").toLocaleLowerCase("vi"), column]));
  const usageByIndex = new Map(sourceList.map((column) => [Number(column.index || 0), column]));
  return {
    ...(page || {}),
    columns: pageColumns.map((column) => {
      const sourceColumn = usageByName.get(String(column.name || "").toLocaleLowerCase("vi")) || usageByIndex.get(Number(column.index || 0)) || {};
      return {
        ...column,
        usages: Array.isArray(column.usages) && column.usages.length ? column.usages : (sourceColumn.usages || []),
        usage: column.usage || sourceColumn.usage || "",
        color: column.color || sourceColumn.color || "",
        join_group: column.join_group || sourceColumn.join_group || "",
        join_tooltip: column.join_tooltip || sourceColumn.join_tooltip || "",
      };
    }),
  };
}

function sqlUsageClass(column) {
  if (!column.color && !column.usage) return "";
  const usage = String(column.usage || "").toLowerCase().replace(/[^a-z0-9_-]/g, "");
  return `usage-column${usage ? ` usage-${usage}` : ""}`;
}

function sqlUsageLabel(column) {
  const values = Array.isArray(column.usages) && column.usages.length ? column.usages : (column.usage ? [column.usage] : []);
  const order = { JOIN: 1, WHERE: 2, SELECT: 3 };
  return values
    .map((value) => String(value || "").toUpperCase())
    .filter(Boolean)
    .sort((left, right) => (order[left] || 99) - (order[right] || 99) || left.localeCompare(right))
    .join(" · ");
}

function sqlJoinTooltipAttrs(column) {
  if (!column.join_tooltip) return "";
  const tooltip = escapeHtml(column.join_tooltip);
  return ` data-sql-join-tooltip="${tooltip}" aria-label="${tooltip}" tabindex="0"`;
}

function renderSqlCell(row, column, index, options) {
  const value = Array.isArray(row.values) ? row.values[index] ?? "" : "";
  const style = sqlUsageStyle(column);
  const className = sqlUsageClass(column);
  const joinTooltipAttrs = sqlJoinTooltipAttrs(column);
  const valueTitle = joinTooltipAttrs ? "" : ` title="${escapeHtml(value)}"`;
  if (options.editable && column.editable) {
    return `<td${joinTooltipAttrs}${style} class="${className}"><input class="sql-cell-input" data-sql-edit="1" data-relation-id="${escapeHtml(options.relationId)}" data-row-number="${Number(row.row_number)}" data-column-name="${escapeHtml(column.name)}" value="${escapeHtml(value)}"${valueTitle}></td>`;
  }
  return `<td${joinTooltipAttrs}${style} class="${className}"><span class="diff-value"${valueTitle}>${escapeHtml(value)}</span></td>`;
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
        bindSqlJoinTooltips(card);
      }
    } catch (error) {
      showToast(error.message, "error", 7000);
    }
  }));
}

function bindSqlJoinTooltips(root) {
  if (!sqlJoinTooltipGlobalBound) {
    sqlJoinTooltipGlobalBound = true;
    window.addEventListener("scroll", hideSqlJoinTooltip, { passive: true });
    window.addEventListener("resize", hideSqlJoinTooltip);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideSqlJoinTooltip();
    });
  }
  $$("[data-sql-join-tooltip]", root).forEach((element) => {
    if (element.dataset.sqlTooltipBound === "1") return;
    element.dataset.sqlTooltipBound = "1";
    element.addEventListener("mouseenter", (event) => showSqlJoinTooltip(element, event));
    element.addEventListener("mousemove", (event) => positionSqlJoinTooltip(event));
    element.addEventListener("mouseleave", hideSqlJoinTooltip);
    element.addEventListener("focus", (event) => showSqlJoinTooltip(element, event));
    element.addEventListener("blur", hideSqlJoinTooltip);
  });
}

function sqlJoinTooltipElement() {
  let tooltip = $("#sql-join-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "sql-join-tooltip";
    tooltip.className = "sql-join-tooltip";
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function showSqlJoinTooltip(element, event) {
  const text = element.dataset.sqlJoinTooltip;
  if (!text) return;
  const tooltip = sqlJoinTooltipElement();
  tooltip.textContent = text;
  tooltip.classList.add("visible");
  positionSqlJoinTooltip(event, element);
}

function positionSqlJoinTooltip(event, element = null) {
  const tooltip = $("#sql-join-tooltip");
  if (!tooltip || !tooltip.classList.contains("visible")) return;
  const rect = element?.getBoundingClientRect?.();
  const clientX = typeof event?.clientX === "number" ? event.clientX : (rect ? rect.left + 12 : 20);
  const clientY = typeof event?.clientY === "number" ? event.clientY : (rect ? rect.bottom + 6 : 20);
  const margin = 12;
  const width = tooltip.offsetWidth || 340;
  const height = tooltip.offsetHeight || 120;
  const left = Math.min(Math.max(margin, clientX + 14), window.innerWidth - width - margin);
  const top = Math.min(Math.max(margin, clientY + 14), window.innerHeight - height - margin);
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function hideSqlJoinTooltip() {
  $("#sql-join-tooltip")?.classList.remove("visible");
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
  if (job.action === "compare_keys_extract") return `Đã lưu key cho ${job.result.saved_count} table; giữ ${job.result.existing_count} key hiện có; bỏ qua ${job.result.skipped.length} table. Chi tiết trong log.`;
  if (job.action === "compare_keys_remove") return `Đã xóa key của ${job.result.removed_count} table khỏi config.`;
  const result = job.result || {};
  if (job.action === "compare") return `Đã xử lý ${result.processed_count || 0} case, tạo ${result.workbook_count || 0} workbook và tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "folder_compare") return `Đã tạo ${result.workbook_count || 1} workbook / ${result.sheet_count || 0} sheet, tìm thấy ${result.fixme_count || 0} FIXME.`;
  if (job.action === "check_fixmes") {
    const count = result.fixme_location_count || 0;
    return count ? `Vẫn còn ${count} cell FIXME trong file compare.` : "Không còn cell FIXME trong các file compare.";
  }
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
    const backup = result.backup_path
      ? ` Backup ${result.backup_row_count || 0} record tại ${result.backup_path}.`
      : "";
    return `Đã đồng bộ ${result.table_count || 0} table: insert ${result.inserted_count || 0}, update ${result.updated_count || 0}, delete ${result.deleted_count || 0}, không đổi ${result.unchanged_count || 0}${retained}.${backup}`;
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
  const cancelButton = $("#cancel-job");
  if (cancelButton) {
    const canCancel = busy && CANCELLABLE_ACTIONS.has(String(state.job?.action || ""));
    cancelButton.classList.toggle("hidden", !canCancel);
    cancelButton.disabled = !canCancel || Boolean(state.job?.cancel_requested);
    cancelButton.textContent = state.job?.cancel_requested ? "Đang hủy..." : "Hủy tác vụ";
  }
  $$('button[type="submit"], #db-normalize, #db-import, #db-export, #db-switch-connections, #find-empty, #delete-empty, #sql-format, #sql-analyze, #sql-load-excel, #sql-run-current, #sql-run-all, #sql-export-all, [data-sql-export], [data-sql-update], #save-excel-format-preset, #delete-excel-format-preset, #fixme-select-filtered, #fixme-clear-selection, #fixme-bulk-assign, #fixme-bulk-clear, #compare-bulk-assign, #compare-bulk-clear, [data-db-test], [data-db-load], #apply-fixmes, #apply-fixmes-preview, #refresh-compare-preview, #check-fixmes, #load-folder-pairs').forEach((button) => {
    button.disabled = busy || (button.id === "delete-excel-format-preset" && !valueOf("excel-format-preset"));
  });
  updateFixmeToolbarState();
  updateCompareBulkToolbarState();
  renderCompareKeys();
}

function appendLogs(lines) {
  const visibleLines = lines.filter((line) => !consumeSyncProgressLog(line));
  if (!visibleLines.length) return;
  appendActivityLogLines(visibleLines);
}

function appendActivityLogLines(lines) {
  const log = $("#activity-log");
  const visibleLines = lines.map((line) => String(line ?? ""));
  if (!visibleLines.length) return;
  if (log.textContent.trim() === ACTIVITY_LOG_READY_TEXT) log.textContent = "";
  const prefix = log.textContent && !log.textContent.endsWith("\n") ? "\n" : "";
  log.textContent += prefix + visibleLines.join("\n") + "\n";
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
