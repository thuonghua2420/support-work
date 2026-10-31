"use strict";

// Compare CSV page helpers: the folder-structure view, the case preview and the 2-folder mode controls.
(() => {
  const SHORT_LABELS = { htm_before_after: "HTM trước/sau", htc_before_after: "HTC trước/sau", after_htc_vs_htm: "HTC ↔ HTM sau" };
  // Which configured folders / workbook each workflow reads or writes; lets the tree dim what is not needed.
  const WORKFLOW_ITEMS = {
    htm_before_after: ["before_htm_dir", "after_htm_dir", "htm_before_after_file"],
    htc_before_after: ["before_htc_dir", "after_htc_dir", "htc_before_after_file"],
    after_htc_vs_htm: ["after_htc_dir", "after_htm_dir", "after_htc_vs_htm_file"],
  };
  const PAIR_MODES = ["separate", "paired_single"];
  const shortLabel = (workflow) => SHORT_LABELS[workflow.key] || workflow.label;
  const selectedWorkflows = () => $$("input[name='compare-workflow']:checked").map((input) => input.value);
  let scanTimer = 0;
  let scanRequest = 0;
  let scanData = null;

  // ---- Folder structure view -------------------------------------------------------------------------------

  function renderStructure() {
    const host = document.getElementById("compare-structure-view");
    const structure = state.bootstrap?.compare_structure;
    if (!host || !structure?.folders) return;
    const { folders, workbooks } = structure;
    const node = (key, name, note, tag, children = "", kind = "folder") => `<li class="cc-node" data-item="${key}"><div class="cc-node-row"><i data-lucide="${kind === "file" ? "file-spreadsheet" : "folder"}" aria-hidden="true"></i><b title="${escapeHtml(name)}">${escapeHtml(name)}</b>${note ? `<em>${note}</em>` : ""}${tag ? `<span class="cc-tag ${tag[0]}">${tag[1]}</span>` : ""}</div>${children ? `<ul>${children}</ul>` : ""}</li>`;
    const required = ["req", "cần có"];
    const files = Object.entries(workbooks).filter(([key]) => key.endsWith("_file") && key !== "folder_compare_file")
      .map(([key, name]) => node(key, name, "", ["auto", "tự tạo"], "", "file")).join("");
    const output = node("output_dir", folders.output_dir, "dữ liệu hai hệ thống xuất ra", null,
      node("before_htm_dir", folders.before_htm_dir, "HTM trước", required)
      + node("after_htm_dir", folders.after_htm_dir, "HTM sau", required)
      + node("before_htc_dir", folders.before_htc_dir, "HTC trước", required)
      + node("after_htc_dir", folders.after_htc_dir, "HTC sau", required)
      + node("compare_dir", folders.compare_dir, "kết quả so sánh", ["auto", "tự tạo"], files));
    const input = node("input_dir", folders.input_dir, "CSV nguồn để copy sang folder trước", ["opt", "tùy chọn"]);
    const caseNode = node("case_pattern", folders.case_pattern || "UT*", "mỗi case một thư mục", null, input + output);
    host.innerHTML = `<ul class="cc-tree-root"><li class="cc-node cc-root"><div class="cc-node-row"><i data-lucide="folder-open" aria-hidden="true"></i><b>Thư mục gốc</b><em>chọn ở bên trái</em></div><ul>${caseNode}</ul></li></ul>`;
    window.lucide?.createIcons({ root: host });
    dimUnusedItems();
  }

  function dimUnusedItems() {
    const used = new Set(selectedWorkflows().flatMap((key) => WORKFLOW_ITEMS[key] || []));
    document.querySelectorAll("#compare-structure-view [data-item]").forEach((item) => {
      const key = item.dataset.item;
      const governed = Object.values(WORKFLOW_ITEMS).some((items) => items.includes(key));
      item.classList.toggle("is-unused", governed && !used.has(key));
    });
  }

  // ---- Case preview ------------------------------------------------------------------------------------------

  function setSummary(text, tone = "") {
    const node = document.getElementById("compare-cases-summary");
    node.textContent = text;
    node.className = tone;
  }

  function renderCases() {
    const head = document.getElementById("compare-cases-head");
    const body = document.getElementById("compare-cases-body");
    if (!scanData) {
      head.innerHTML = "";
      body.innerHTML = "";
      return;
    }
    const selected = new Set(selectedWorkflows());
    const workflows = scanData.workflows;
    const needs = (workflow) => selected.has(workflow.key);
    const complete = (item) => item.workflows.every((flow) => !selected.has(flow.key) || flow.ready);
    const ready = scanData.cases.filter(complete).length;
    if (!scanData.total) {
      setSummary(`Không có case nào khớp “${scanData.case_pattern}” trong thư mục này.`, "warn");
      head.innerHTML = "";
      body.innerHTML = "";
      return;
    }
    const missing = scanData.cases.length - ready;
    setSummary(
      `${scanData.total} case${scanData.truncated ? ` (hiện ${scanData.cases.length})` : ""} · ${ready} đủ folder cho các luồng đã chọn${missing ? ` · ${missing} thiếu` : ""}`,
      missing ? "warn" : "ok",
    );
    head.innerHTML = `<tr><th>Case</th><th title="Folder input">Input</th>${workflows.map((workflow) => `<th title="${escapeHtml(workflow.label)}"${needs(workflow) ? "" : ' class="is-unused"'}>${escapeHtml(shortLabel(workflow))}</th>`).join("")}</tr>`;
    body.innerHTML = scanData.cases.map((item) => {
      const cells = item.workflows.map((flow, index) => {
        const unused = needs(workflows[index]) ? "" : ' class="is-unused"';
        if (flow.ready) return `<td${unused} title="Trước ${flow.left.csv_count} CSV · Sau ${flow.right.csv_count} CSV"><span class="cc-ok">✓</span> ${flow.left.csv_count} / ${flow.right.csv_count}</td>`;
        const lacking = [flow.left, flow.right].filter((side) => !side.exists).map((side) => side.name).join(", ");
        return `<td${unused} title="Thiếu folder: ${escapeHtml(lacking)}"><span class="cc-bad">✕</span> thiếu folder</td>`;
      }).join("");
      const input = item.has_input ? `${item.input_count} CSV` : "—";
      return `<tr><th scope="row" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</th><td>${input}</td>${cells}</tr>`;
    }).join("");
  }

  async function scanCases() {
    const root = valueOf("compare-root");
    const request = ++scanRequest;
    if (!root) {
      scanData = null;
      setSummary("Chọn thư mục gốc để xem danh sách case.");
      renderCases();
      return;
    }
    setSummary("Đang quét…");
    try {
      const data = await api(`/api/compare-cases?${new URLSearchParams({ root })}`);
      if (request !== scanRequest) return;
      scanData = data;
      renderCases();
    } catch (error) {
      if (request !== scanRequest) return;
      scanData = null;
      setSummary(error.message, "warn");
      renderCases();
    }
  }

  function scheduleScan(delay = 400) {
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(scanCases, delay);
  }

  // ---- 2-folder mode -----------------------------------------------------------------------------------------

  const exportMode = () => $('input[name="folder-export-mode"]:checked')?.value || "single";
  const hints = {
    single: "CSV chỉ có ở một phía vẫn được đưa vào workbook, phía còn lại để trống.",
    separate: "Mỗi cặp CSV tạo một workbook riêng trong thư mục đã chọn.",
    paired_single: "Mỗi cặp một sheet; tên sheet lấy theo tên CSV bên phải.",
  };

  function suggestedOutput(separate) {
    const right = valueOf("folder-right");
    const base = (right && parentPath(right)) || state.bootstrap.cwd;
    const file = state.bootstrap.folder_compare_file || "Compare_2_Folder_CSV.xlsx";
    return joinPath(base, separate ? file.replace(/\.xlsx$/i, "") : file);
  }

  function applyFolderMode() {
    const separate = exportMode() === "separate";
    const output = document.getElementById("folder-output");
    document.getElementById("folder-output-label").textContent = separate ? "Lưu các file vào thư mục" : "Lưu file Excel tại";
    const browse = document.getElementById("folder-output-browse");
    browse.dataset.browseKind = separate ? "directory" : "save";
    browse.dataset.browseExt = separate ? "" : "xlsx";
    document.getElementById("folder-compare-hint").textContent = hints[exportMode()];
    if (!output.dataset.manual) output.value = suggestedOutput(separate);
    else if (separate) output.value = output.value.replace(/\.xlsx$/i, "");
    else if (output.value && !/\.xlsx$/i.test(output.value)) output.value += ".xlsx";
    scanPairsIfNeeded();
  }

  function scanPairsIfNeeded() {
    if (PAIR_MODES.includes(exportMode()) && valueOf("folder-left") && valueOf("folder-right") && !state.folderComparePairs.length) {
      loadFolderComparePairs({ silent: true });
    }
  }

  function bindFolderMode() {
    const output = document.getElementById("folder-output");
    const markManual = () => { if (output.value.trim()) output.dataset.manual = "1"; else delete output.dataset.manual; };
    output.addEventListener("input", markManual);
    output.addEventListener("change", markManual);
    // A path restored from the last session that differs from the default counts as the user's own choice.
    if (output.value && output.value !== suggestedOutput(false) && output.value !== suggestedOutput(true)
      && output.value !== joinPath(state.bootstrap.cwd, state.bootstrap.folder_compare_file)) output.dataset.manual = "1";
    $$('input[name="folder-export-mode"]').forEach((radio) => radio.addEventListener("change", applyFolderMode));
    ["folder-left", "folder-right"].forEach((id) => {
      const input = document.getElementById(id);
      input.addEventListener("change", () => {
        if (!output.dataset.manual) output.value = suggestedOutput(exportMode() === "separate");
        scanPairsIfNeeded();
      });
    });
    document.getElementById("folder-swap").addEventListener("click", () => {
      const [left, right] = [document.getElementById("folder-left"), document.getElementById("folder-right")];
      [left.value, right.value] = [right.value, left.value];
      resetFolderComparePairs();
      if (!output.dataset.manual) output.value = suggestedOutput(exportMode() === "separate");
      scanPairsIfNeeded();
    });
    applyFolderMode();
  }

  // ---- Wiring ------------------------------------------------------------------------------------------------

  function updateResultCount() {
    const badge = document.getElementById("compare-result-count");
    if (!badge) return;
    const count = (state.compareView?.cases || []).reduce((total, item) => total + item.workbooks.length, 0);
    badge.textContent = String(count);
    badge.classList.toggle("hidden", !count);
  }

  function ready() {
    renderStructure();
    bindFolderMode();
    const root = document.getElementById("compare-root");
    root.addEventListener("input", () => scheduleScan());
    root.addEventListener("change", () => scheduleScan(0));
    document.getElementById("rescan-compare-cases").addEventListener("click", () => scheduleScan(0));
    document.getElementById("compare-workflows").addEventListener("change", () => { renderCases(); dimUnusedItems(); });
    document.getElementById("toggle-workflows").addEventListener("click", () => { renderCases(); dimUnusedItems(); });
    updateResultCount();
    scheduleScan(0);
  }

  window.compareCsv = {
    ready,
    updateResultCount,
    structureChanged() { renderStructure(); if (document.getElementById("compare-root")?.value) scheduleScan(0); },
  };
})();
