"use strict";

// File Compare: a WinMerge-style diff/merge workspace.
// Three views share one page: "select" (choose paths), "files" (diff + merge) and "folder" (folder-compare grid).
(() => {
  const $tc = id => document.getElementById(`tc-${id}`);
  const page = document.getElementById("page-text-compare");
  const Pos = CodeMirror.Pos;
  const labels = ["A", "B", "C"];
  const OPTIONS_KEY = "autocompare:file-compare-options";
  const RECENT_KEY = "autocompare:file-compare-recent";
  const defaults = { ws: false, case: false, blank: false, onlyDiff: false, moved: true, lines: true, wrap: true, editable: true, language: "auto" };
  const store = {
    read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
    write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* a convenience only */ } },
  };
  const opts = { ...defaults, ...store.read(OPTIONS_KEY, {}) };
  const docs = Array.from({ length: 3 }, () => ({ text: "", savedText: "", meta: null, eol: "original" }));
  let editors = [], merge = null, count = 2, loading = false, timer = 0;
  let allChunks = [], chunks = [], current = -1, lastEditor = null, lastChanged = null, revealing = false, pendingSelect = null;
  let lineMarks = [], currentMarks = [], movedMarks = [], observers = [];
  let origin = "select", folderOrder = [], folderParams = null;
  let folders = null;
  const folderUi = { filter: "diff", tree: true, collapsed: new Set(), sort: { key: "name", dir: 1 }, selected: "", limit: 1500 };

  const normalize = text => text.replace(/\r\n?/g, "\n");
  const eolName = eol => ({ "\n": "LF", "\r\n": "CRLF", "\r": "CR", mixed: "EOL hỗn hợp" }[eol] || "LF");
  const statusNames = { same: "Giống nhau", different: "Khác nhau", "left-only": "Chỉ có bên trái", "right-only": "Chỉ có bên phải", "type-conflict": "Khác loại", error: "Lỗi đọc", skipped: "Bỏ qua liên kết", folder: "Thư mục" };
  const DIFF_STATUSES = new Set(["different", "left-only", "right-only", "type-conflict", "error", "skipped"]);

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  const icons = root => window.lucide?.createIcons(root ? { root } : undefined);
  const baseName = path => String(path || "").split(/[\\/]/).pop();
  function message(text, error = false) { $tc("message").textContent = text; $tc("message").classList.toggle("tc-error", error); }
  function selectMessage(text, error = false) { $tc("select-message").textContent = text; $tc("select-message").classList.toggle("tc-error", error); }
  function syncDocs() { editors.forEach((editor, i) => { docs[i].text = editor.getValue(); }); }
  function dirty(i) { return docs[i].text !== docs[i].savedText; }
  const anyDirty = () => { syncDocs(); return docs.slice(0, count).some((_, i) => dirty(i)); };
  async function allowReplace() {
    return !anyDirty() || await confirmAction("Bỏ bản chỉnh sửa chưa lưu?", "Thao tác này sẽ thay nội dung trong các khung. Hãy lưu hoặc tải bản sao nếu cần giữ chỉnh sửa.");
  }

  // ---- Views ------------------------------------------------------------------------------------------------------

  function showView(name) {
    page.dataset.view = name;
    $tc("select-view").classList.toggle("hidden", name !== "select");
    $tc("files-view").classList.toggle("hidden", name !== "files");
    $tc("folder-view").classList.toggle("hidden", name !== "folder");
    page.classList.toggle("tc-fixed", name !== "select");
    closeMenus();
    if (name === "files") requestAnimationFrame(() => { editors.forEach(editor => editor.refresh()); schedule(0); });
  }

  function selectMode(mode) {
    page.querySelectorAll("[data-tc-mode]").forEach(button => {
      const active = button.dataset.tcMode === mode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    $tc("file-select").classList.toggle("hidden", mode !== "files");
    $tc("folder-form").classList.toggle("hidden", mode !== "folders");
    selectMessage("");
  }

  // ---- Recent pairs -----------------------------------------------------------------------------------------------

  function remember(entry) {
    const key = JSON.stringify(entry);
    const list = [entry, ...store.read(RECENT_KEY, []).filter(item => JSON.stringify(item) !== key)].slice(0, 8);
    store.write(RECENT_KEY, list);
    renderRecent();
  }
  function renderRecent() {
    const list = store.read(RECENT_KEY, []);
    $tc("recent").classList.toggle("hidden", !list.length);
    $tc("recent-list").replaceChildren(...list.map((entry, index) => {
      const item = node("li"), button = node("button", "tc-recent-item"); button.type = "button";
      const paths = entry.kind === "files" ? entry.paths : [entry.left, entry.right];
      button.append(node("i"), node("span", "", paths.map(baseName).join("  ↔  ")), node("small", "", paths[0]));
      button.firstChild.setAttribute("data-lucide", entry.kind === "files" ? "file-diff" : "folders");
      button.addEventListener("click", () => runRecent(entry));
      item.append(button); return item;
    }));
    icons($tc("recent-list"));
  }
  function runRecent(entry) {
    if (entry.kind === "files") {
      count = entry.paths.length; $tc("count").value = String(count); applyCount();
      entry.paths.forEach((path, i) => { $tc(`path-${i}`).value = path; });
      selectMode("files"); loadPaths(entry.paths);
    } else {
      selectMode("folders");
      $tc("folder-left").value = entry.left; $tc("folder-right").value = entry.right;
      $tc("include").value = entry.include ?? ""; $tc("exclude").value = entry.exclude ?? $tc("exclude").value;
      scanFolders();
    }
  }

  // ---- Syntax and options -----------------------------------------------------------------------------------------

  function modeFor(i) {
    if (opts.language !== "auto") return opts.language;
    const found = CodeMirror.findModeByFileName(docs[i].meta?.name || "");
    return found && CodeMirror.modes[found.mode] ? found.mime : "text/plain";
  }
  function saveOptions() { store.write(OPTIONS_KEY, opts); }
  function applyOptions() {
    editors.forEach((editor, i) => {
      editor.setOption("mode", modeFor(i));
      editor.setOption("readOnly", !opts.editable);
      editor.setOption("lineNumbers", opts.lines);
    });
    page.classList.toggle("tc-readonly", !opts.editable);
    $tc("flags").textContent = [opts.ws && "khoảng trắng", opts.case && "hoa/thường", opts.blank && "dòng trống"].filter(Boolean).join(", ")
      ? `Bỏ qua: ${[opts.ws && "khoảng trắng", opts.case && "hoa/thường", opts.blank && "dòng trống"].filter(Boolean).join(", ")}` : "";
    updateToolbar();
    schedule(0);
  }

  // ---- Building the merge view ------------------------------------------------------------------------------------

  const commands = {
    next: () => navigate(1), prev: () => navigate(-1), first: () => go("first"), last: () => go("last"),
    copyRight: () => copyCurrent("right", false), copyLeft: () => copyCurrent("left", false),
    copyRightNext: () => copyCurrent("right", true), copyLeftNext: () => copyCurrent("left", true),
    save: () => saveDocs(docs.slice(0, count).map((_, i) => i)), find: () => openFind(), goto: () => openFind(true),
    refresh: () => refreshFiles(), back: () => goBack(),
  };
  const keyTable = {
    "Alt-Down": "next", "Alt-Up": "prev", "Alt-Home": "first", "Alt-End": "last",
    "Alt-Right": "copyRight", "Alt-Left": "copyLeft", "Ctrl-Alt-Right": "copyRightNext", "Ctrl-Alt-Left": "copyLeftNext",
    "Ctrl-S": "save", "Ctrl-F": "find", "Ctrl-G": "goto", "F5": "refresh", "Ctrl-O": "back",
  };
  const extraKeys = Object.fromEntries(Object.entries(keyTable).map(([key, name]) => [key, () => commands[name]()]));

  function build() {
    syncDocs();
    observers.forEach(observer => observer.disconnect()); observers = [];
    clearAllMarks(); current = -1; allChunks = []; chunks = [];
    $tc("editor").replaceChildren();
    merge = CodeMirror.MergeView($tc("editor"), {
      value: docs[count === 3 ? 1 : 0].text,
      origLeft: count === 3 ? docs[0].text : null,
      origRight: docs[count - 1].text,
      allowEditingOriginals: true, revertButtons: true, connect: "align",
      collapseIdentical: opts.onlyDiff ? 3 : false,
      lineNumbers: opts.lines, lineWrapping: opts.wrap, readOnly: !opts.editable,
      gutters: ["CodeMirror-linenumbers", "tc-move-gutter"], indentUnit: 2, tabSize: 4,
      viewportMargin: 15, inputStyle: "textarea", extraKeys,
      phrases: { "Toggle locked scrolling": "Khóa cuộn đồng bộ", "Identical text collapsed. Click to expand.": "Đoạn giống nhau đã thu gọn. Bấm để mở." },
    });
    editors = count === 3 ? [merge.leftOriginal(), merge.editor(), merge.rightOriginal()] : [merge.editor(), merge.rightOriginal()];
    lastEditor = editors[0]; lastChanged = null;
    editors.forEach((editor, i) => {
      editor.getInputField().setAttribute("aria-label", `Nội dung file ${labels[i]}`);
      editor.on("beforeChange", (_cm, change) => {
        if (change.origin === "setValue") return;
        const incoming = change.text.join("\n");
        const removed = editor.getRange(change.from, change.to).length;
        if (editor.getValue().length - removed + incoming.length > 1_000_000 || editor.lineCount() - (change.to.line - change.from.line) + change.text.length - 1 > 10000) {
          change.cancel(); message("Editor giới hạn 1 MB / 10.000 dòng. Nội dung vừa nhập vượt giới hạn.", true);
        }
      });
      editor.on("change", () => { lastChanged = editor; docs[i].text = editor.getValue(); refreshHeaders(); updateToolbar(); schedule(); });
      editor.on("focus", () => { lastEditor = editor; updateCursor(); updateToolbar(); });
      editor.on("cursorActivity", () => { updateCursor(); if (!revealing) selectChunkAtCursor(editor); });
      editor.on("updateDiff", () => schedule(0));
      editor.on("scroll", () => requestAnimationFrame(drawMap));
    });
    for (const dv of [merge.left, merge.right]) {
      if (!dv?.copyButtons) continue;
      const observer = new MutationObserver(decorateCopyButtons);
      observer.observe(dv.copyButtons, { childList: true });
      observers.push(observer);
    }
    $tc("headings").classList.toggle("tc-three", count === 3);
    $tc("third").classList.toggle("hidden", count !== 3);
    refreshHeaders(true); applyOptions();
    requestAnimationFrame(() => { editors.forEach(editor => editor.refresh()); schedule(0); });
  }

  function refreshHeaders(force = false) {
    if (!force && $tc("headings").contains(document.activeElement)) return;
    const parts = [];
    editors.forEach((_, i) => {
      const doc = docs[i], box = node("div", `tc-title${dirty(i) ? " tc-dirty" : ""}`);
      const name = node("strong", "", `${labels[i]} · ${doc.meta?.name || "Văn bản mới"}${count === 3 && i === 1 ? " · mốc" : ""}`);
      name.title = doc.meta?.path || "Nội dung chỉ nằm trong trình duyệt";
      const meta = node("small", "", doc.meta ? `${doc.meta.encoding} · ${eolName(doc.meta.eol)} · ${doc.meta.size.toLocaleString()} B` : "Bản nháp · UTF-8");
      const actions = node("div", "tc-title-actions");
      const save = node("button", "tc-tool", ""); save.type = "button"; save.disabled = !doc.meta || loading;
      save.title = `Lưu file ${labels[i]} (ghi đè file gốc)`; save.setAttribute("aria-label", save.title); save.dataset.tcSave = String(i);
      save.innerHTML = '<i data-lucide="save" aria-hidden="true"></i>';
      save.addEventListener("click", () => saveDocs([i], true));
      const download = node("button", "tc-tool", ""); download.type = "button";
      download.title = `Tải bản sao UTF-8 của ${labels[i]} (không thay đổi file gốc)`; download.setAttribute("aria-label", download.title);
      download.innerHTML = '<i data-lucide="download" aria-hidden="true"></i>';
      download.addEventListener("click", () => {
        const url = URL.createObjectURL(new Blob([editors[i].getValue()], { type: "text/plain;charset=utf-8" }));
        const link = node("a"); link.href = url; link.download = doc.meta?.name || `File-${labels[i]}.txt`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      const eol = node("select"); eol.setAttribute("aria-label", `Xuống dòng khi lưu file ${labels[i]}`); eol.title = "Xuống dòng khi lưu";
      for (const [value, label] of [["original", "EOL gốc"], ["\n", "LF"], ["\r\n", "CRLF"]]) { const option = node("option", "", label); option.value = value; eol.append(option); }
      eol.value = doc.eol; eol.addEventListener("change", () => { doc.eol = eol.value; });
      const text = node("div", "tc-title-text"); text.append(name, meta);
      actions.append(save, download, eol); box.append(text, actions);
      if (i) parts.push(node("div", "tc-title-gap"));
      parts.push(box);
    });
    $tc("headings").replaceChildren(...parts);
    icons($tc("headings"));
  }

  // ---- Saving -----------------------------------------------------------------------------------------------------

  async function saveDocs(indexes, force = false) {
    if (loading) return;
    syncDocs();
    const targets = indexes.filter(i => docs[i].meta && (force || dirty(i)));
    if (!targets.length) { message(docs.slice(0, count).some(doc => !doc.meta) ? "Không có file đã mở nào chỉnh sửa. Khung dán chỉ tải được bản sao." : "Không có thay đổi cần lưu."); return; }
    const lines = targets.map(i => `• ${labels[i]}: ${docs[i].meta.path} (EOL: ${docs[i].eol === "original" ? "giữ gốc" : eolName(docs[i].eol)})`).join("\n");
    if (!await confirmAction("Ghi đè file văn bản?", `Lưu nội dung các khung sau vào file gốc:\n${lines}\n\nGiữ encoding gốc. Thao tác không tạo bản backup tự động; file đổi bên ngoài sẽ bị chặn ghi đè.`)) return;
    loading = true; refreshHeaders(true); updateToolbar();
    const done = [];
    try {
      for (const i of targets) {
        const doc = docs[i], text = editors[i].getValue();
        const saved = await api("/api/text-compare/save", { method: "POST", body: { token: doc.meta.token, sha256: doc.meta.sha256, text, eol: doc.eol, confirmed: true } });
        doc.savedText = text; doc.meta.sha256 = saved.sha256; doc.meta.size = saved.size;
        if (doc.eol !== "original") doc.meta.eol = doc.eol;
        done.push(labels[i]);
      }
      message(`Đã lưu file ${done.join(", ")}.`);
    } catch (error) {
      message(`${done.length ? `Đã lưu ${done.join(", ")}; ` : ""}${error.message}`, true);
      showToast(error.message, "error", 6000);
    } finally { loading = false; refreshHeaders(true); updateToolbar(); schedule(0); }
  }

  // ---- Loading files ----------------------------------------------------------------------------------------------

  async function loadPaths(paths, { from = "select" } = {}) {
    if (loading || !await allowReplace()) return false;
    loading = true; $tc("open").disabled = true; selectMessage("Đang đọc file…");
    try {
      const loaded = await Promise.all(paths.map(path => api("/api/text-compare/open", { method: "POST", body: { path } })));
      count = paths.length; $tc("count").value = String(count); applyCount();
      docs.forEach((_, i) => {
        const meta = loaded[i] || null;
        docs[i] = { text: meta ? normalize(meta.text) : "", savedText: meta ? normalize(meta.text) : "", meta, eol: "original" };
      });
      origin = from; configureNavigation();
      showView("files"); editors = []; build(); pendingSelect = "first";
      message("Đã mở file. Chỉnh sửa chỉ là bản nháp cho tới khi bạn lưu (Ctrl+S).");
      selectMessage("");
      if (from === "select") remember({ kind: "files", paths: loaded.map(file => file.path) });
      return true;
    } catch (error) {
      if (page.dataset.view === "files") { message(error.message, true); showToast(error.message, "error"); }
      else selectMessage(error.message, true);
      return false;
    } finally { loading = false; $tc("open").disabled = false; refreshHeaders(true); updateToolbar(); }
  }

  async function openBlank() {
    if (!await allowReplace()) return;
    count = Number($tc("count").value);
    docs.forEach((_, i) => { docs[i] = { text: "", savedText: "", meta: null, eol: "original" }; });
    origin = "select"; configureNavigation(); showView("files"); editors = []; build();
    message("Dán nội dung vào hai khung để so sánh. Khung dán không lưu được vào file, chỉ tải bản sao.");
  }

  async function refreshFiles() {
    const paths = docs.slice(0, count).map(doc => doc.meta?.path);
    if (paths.some(path => !path)) { message("Chỉ tải lại được khi cả hai khung đều mở từ file.", true); return; }
    await loadPaths(paths, { from: origin });
  }

  async function swapSides() {
    syncDocs();
    if (count === 3) { [docs[0], docs[2]] = [docs[2], docs[0]]; } else { [docs[0], docs[1]] = [docs[1], docs[0]]; }
    editors = []; build(); pendingSelect = "first";
    message("Đã đổi chỗ trái / phải.");
  }

  function goBack() {
    if (anyDirty()) {
      confirmAction("Rời khỏi so sánh?", "Bản chỉnh sửa chưa lưu vẫn còn trong bộ nhớ trình duyệt cho tới khi bạn mở file khác. Bạn vẫn muốn quay lại?").then(ok => { if (ok) leave(); });
    } else leave();
    function leave() { showView(origin === "folder" ? "folder" : "select"); }
  }

  // ---- Diff bookkeeping -------------------------------------------------------------------------------------------

  function schedule(delay = 450) { clearTimeout(timer); timer = setTimeout(refreshDiff, delay); }

  function textOf(part) { return part.ed.getRange(Pos(part.from, 0), Pos(part.to, 0)); }
  function normalizedLines(text) {
    let lines = text.split("\n");
    if (opts.blank) lines = lines.filter(line => line.trim() !== "");
    if (opts.ws) lines = lines.map(line => line.replace(/\s+/g, ""));
    let joined = lines.join("\n");
    if (opts.case) joined = joined.toLowerCase();
    return joined;
  }
  function chunkIgnored(left, right) {
    return (opts.ws || opts.case || opts.blank) && normalizedLines(textOf(left)) === normalizedLines(textOf(right));
  }

  function collectChunks() {
    if (!merge) return [];
    const center = merge.editor(), out = [];
    const add = (side, chunk, left, right, pos) => {
      const l = left.to - left.from, r = right.to - right.from;
      out.push({
        side, pos, l: left, r: right,
        key: `${chunk.origFrom}:${chunk.origTo}:${chunk.editFrom}:${chunk.editTo}`,
        type: l && !r ? "left-only" : !l && r ? "right-only" : "change",
        ignored: chunkIgnored(left, right),
      });
    };
    for (const chunk of merge.rightChunks() || []) {
      add("right", chunk, { ed: center, from: chunk.editFrom, to: chunk.editTo }, { ed: merge.rightOriginal(), from: chunk.origFrom, to: chunk.origTo }, chunk.editFrom);
    }
    if (count === 3) {
      for (const chunk of merge.leftChunks() || []) {
        add("left", chunk, { ed: merge.leftOriginal(), from: chunk.origFrom, to: chunk.origTo }, { ed: center, from: chunk.editFrom, to: chunk.editTo }, chunk.editFrom);
      }
    }
    return out.sort((a, b) => a.pos - b.pos || (a.side === "left" ? -1 : 1));
  }

  function paintLines(part, cls, where, bucket) {
    for (let n = part.from; n < part.to && n < part.ed.lineCount(); n++) bucket.push([part.ed, part.ed.addLineClass(n, where, cls), where, cls]);
  }
  function clearBucket(bucket) { bucket.forEach(([ed, handle, where, cls]) => ed.removeLineClass(handle, where, cls)); bucket.length = 0; }
  function clearAllMarks() { clearBucket(lineMarks); clearBucket(currentMarks); clearMoved(); }

  function paintChunks() {
    clearBucket(lineMarks);
    for (const chunk of allChunks) {
      if (chunk.ignored) {
        for (const part of [chunk.l, chunk.r]) { paintLines(part, "tc-ignored-bg", "background", lineMarks); paintLines(part, "tc-ignored-text", "text", lineMarks); }
      } else {
        const cls = chunk.type === "left-only" ? "tc-lo" : chunk.type === "right-only" ? "tc-ro" : "tc-ch";
        for (const part of [chunk.l, chunk.r]) { paintLines(part, cls, "background", lineMarks); paintLines(part, `${cls}-t`, "text", lineMarks); }
      }
    }
  }
  function paintCurrent() {
    clearBucket(currentMarks);
    const chunk = chunks[current];
    if (!chunk) return;
    for (const part of [chunk.l, chunk.r]) {
      paintLines(part, "tc-cur-bg", "background", currentMarks);
      if (part.to === part.from && part.from < part.ed.lineCount()) {
        // The side without lines still shows the position of the difference.
        currentMarks.push([part.ed, part.ed.addLineClass(part.from, "background", "tc-cur-edge"), "background", "tc-cur-edge"]);
      }
    }
  }

  function clearMoved() { movedMarks.forEach(([editor, handle]) => editor.removeLineClass(handle, "background", "tc-moved-line")); movedMarks = []; editors.forEach(editor => editor.clearGutter("tc-move-gutter")); }
  function movedPair(edit, orig, ranges) {
    const index = editor => {
      const map = new Map();
      editor.eachLine(handle => { const text = handle.text; const line = editor.getLineNumber(handle); if (text.trim().length > 2) map.set(text, map.has(text) ? -1 : line); });
      return map;
    };
    const a = index(edit), b = index(orig), changedA = new Set(), changedB = new Set();
    ranges.forEach(c => { for (let n = c.editFrom; n < c.editTo; n++) changedA.add(n); for (let n = c.origFrom; n < c.origTo; n++) changedB.add(n); });
    let total = 0;
    for (const [text, from] of a) {
      const to = b.get(text);
      if (from < 0 || to === undefined || to < 0 || from === to || !changedA.has(from) || !changedB.has(to)) continue;
      total++;
      for (const [editor, line, other, destination] of [[edit, from, orig, to], [orig, to, edit, from]]) {
        const handle = editor.addLineClass(line, "background", "tc-moved-line"); movedMarks.push([editor, handle]);
        const marker = node("button", "tc-move-marker", "↔"); marker.type = "button";
        marker.title = `Dòng di chuyển → dòng ${destination + 1} ở khung đối chiếu`;
        marker.setAttribute("aria-label", marker.title);
        marker.addEventListener("click", () => { other.scrollIntoView({ line: destination, ch: 0 }, 80); other.setCursor(destination, 0); other.focus(); });
        editor.setGutterMarker(line, "tc-move-gutter", marker);
      }
    }
    return total;
  }

  function refreshDiff() {
    if (!merge || page.dataset.view !== "files") return;
    allChunks = collectChunks();
    chunks = allChunks.filter(chunk => !chunk.ignored);
    const ignoredKeys = { left: new Set(), right: new Set() };
    allChunks.filter(chunk => chunk.ignored).forEach(chunk => ignoredKeys[chunk.side].add(chunk.key));
    merge.ignoredKeys = ignoredKeys;
    paintChunks();
    clearMoved();
    let moved = 0;
    if (opts.moved) {
      moved += movedPair(merge.editor(), merge.rightOriginal(), (merge.rightChunks() || []).filter(c => !ignoredKeys.right.has(`${c.origFrom}:${c.origTo}:${c.editFrom}:${c.editTo}`)));
      if (count === 3) moved += movedPair(merge.editor(), merge.leftOriginal(), (merge.leftChunks() || []).filter(c => !ignoredKeys.left.has(`${c.origFrom}:${c.origTo}:${c.editFrom}:${c.editTo}`)));
    }
    if (pendingSelect === "first") current = chunks.length ? 0 : -1;
    else if (typeof pendingSelect === "number") current = chunks.length ? Math.min(pendingSelect, chunks.length - 1) : -1;
    else current = Math.min(current, chunks.length - 1);
    const select = pendingSelect; pendingSelect = null;

    const draft = anyDirty();
    const loaded = docs.slice(0, count).every(doc => doc.meta);
    const byteEqual = loaded && !draft && docs.slice(1, count).every(doc => doc.meta.sha256 === docs[0].meta.sha256);
    let summary;
    if (chunks.length) {
      const sides = count === 3 ? ` (A↔B: ${chunks.filter(c => c.side === "left").length} · B↔C: ${chunks.filter(c => c.side === "right").length})` : "";
      summary = `${chunks.length} sai khác${sides}`;
    } else if (allChunks.length) summary = `Không còn sai khác (${allChunks.length} vùng chỉ khác khoảng trắng / hoa-thường / dòng trống đã bỏ qua)`;
    else summary = loaded && !draft ? (byteEqual ? "Các file giống nhau 100% về byte" : "Nội dung dòng giống nhau · encoding / BOM / xuống dòng khác") : "Nội dung giống nhau";
    if (moved) summary += ` · ${moved} dòng di chuyển`;
    if (draft) summary += " · đang so sánh bản nháp";
    $tc("summary").textContent = summary;
    paintCurrent(); decorateCopyButtons(); updateToolbar(); drawMap();
    if (select != null && current >= 0) reveal(false);
  }

  function decorateCopyButtons() {
    if (!merge) return;
    for (const [dv, side] of [[merge.left, "left"], [merge.right, "right"]]) {
      if (!dv?.copyButtons) continue;
      const ignored = merge.ignoredKeys?.[side] || new Set();
      dv.copyButtons.querySelectorAll(".CodeMirror-merge-copy, .CodeMirror-merge-copy-reverse").forEach(button => {
        const reverse = button.classList.contains("CodeMirror-merge-copy-reverse");
        // Right gap: "copy" pulls from the right pane (→ left), "reverse" pushes right. Left gap: the opposite.
        const toRight = (side === "right") === reverse;
        const c = button.chunk;
        const key = c ? (reverse ? `${c.editFrom}:${c.editTo}:${c.origFrom}:${c.origTo}` : `${c.origFrom}:${c.origTo}:${c.editFrom}:${c.editTo}`) : "";
        const text = toRight ? "→" : "←";
        if (button.textContent !== text) button.textContent = text;
        button.title = toRight ? "Chép vùng này sang phải" : "Chép vùng này sang trái";
        button.setAttribute("aria-label", button.title);
        button.classList.toggle("tc-copy-ignored", ignored.has(key));
      });
    }
  }

  // ---- Navigation -------------------------------------------------------------------------------------------------

  function reveal(focus = false) {
    const chunk = chunks[current];
    if (!chunk) return;
    revealing = true;
    for (const part of [chunk.l, chunk.r]) part.ed.scrollIntoView({ from: Pos(Math.max(0, part.from - 2), 0), to: Pos(Math.min(part.ed.lastLine(), Math.max(part.to, part.from + 1)), 0) }, 120);
    const center = chunk.side === "left" ? chunk.r : chunk.l;
    center.ed.setCursor(Math.min(center.from, center.ed.lastLine()), 0);
    if (focus) center.ed.focus();
    revealing = false;
    paintCurrent(); updateToolbar(); drawMap();
  }
  function navigate(direction) {
    if (!chunks.length) return;
    current = current < 0 ? (direction > 0 ? 0 : chunks.length - 1) : (current + direction + chunks.length) % chunks.length;
    reveal();
  }
  function go(where) { if (!chunks.length) return; current = where === "first" ? 0 : chunks.length - 1; reveal(); }
  function selectChunkAtCursor(editor) {
    if (!chunks.length) return;
    const line = editor.getCursor().line;
    const index = chunks.findIndex(chunk => [chunk.l, chunk.r].some(part => part.ed === editor && line >= part.from && line < Math.max(part.to, part.from + 1)));
    if (index >= 0 && index !== current) { current = index; paintCurrent(); updateToolbar(); drawMap(); }
  }

  // ---- Merging ----------------------------------------------------------------------------------------------------

  // Same boundary rule as CodeMirror's own revert button, so a chunk at the end of a file copies its newline correctly.
  function replaceLines(to, from) {
    const src = from.ed, dst = to.ed;
    const srcStart = from.to > src.lastLine() ? Pos(from.from - 1) : Pos(from.from, 0);
    const dstStart = to.to > dst.lastLine() ? Pos(to.from - 1) : Pos(to.from, 0);
    dst.replaceRange(src.getRange(srcStart, Pos(from.to, 0)), dstStart, Pos(to.to, 0));
  }
  function copyChunk(chunk, direction) { direction === "right" ? replaceLines(chunk.r, chunk.l) : replaceLines(chunk.l, chunk.r); }

  function copyCurrent(direction, advance) {
    if (!opts.editable) { message("Đang tắt chỉnh sửa; bật “Cho phép chỉnh sửa và merge” trong Tùy chọn.", true); return; }
    const chunk = chunks[current];
    if (!chunk) { message("Chưa chọn vùng sai khác nào.", true); return; }
    const index = current;
    copyChunk(chunk, direction);
    if (advance) pendingSelect = index; // the copied chunk disappears, so the same index is the next one
    message(`Đã chép vùng ${index + 1} sang ${direction === "right" ? "phải" : "trái"} (Ctrl+Z để hoàn tác).`);
    schedule(300);
  }

  function copyAll(direction) {
    if (!opts.editable) { message("Đang tắt chỉnh sửa; bật “Cho phép chỉnh sửa và merge” trong Tùy chọn.", true); return; }
    if (count === 3 || !chunks.length) return;
    const target = direction === "right" ? chunks[0].r.ed : chunks[0].l.ed;
    const total = chunks.length;
    target.operation(() => { [...chunks].sort((a, b) => b.pos - a.pos).forEach(chunk => copyChunk(chunk, direction)); });
    pendingSelect = "first";
    message(`Đã chép ${total} vùng sang ${direction === "right" ? "phải" : "trái"}; hai bên giờ giống nhau (Ctrl+Z để hoàn tác).`);
    schedule(300);
  }

  function undoRedo(kind) {
    const editor = lastChanged || lastEditor || editors[0];
    if (!editor) return;
    editor[kind](); editor.focus(); schedule(300);
  }

  // ---- Toolbar state, cursor, find --------------------------------------------------------------------------------

  function updateToolbar() {
    if (!merge) return;
    const has = chunks.length > 0, editable = opts.editable;
    for (const id of ["first", "prev", "next", "last"]) $tc(id).disabled = !has;
    for (const id of ["copy-right", "copy-left", "copy-right-next", "copy-left-next"]) $tc(id).disabled = !has || current < 0 || !editable;
    for (const id of ["copy-all-right", "copy-all-left"]) {
      $tc(id).disabled = !has || !editable || count === 3;
      $tc(id).title = count === 3 ? "Chỉ dùng khi so sánh 2 file" : $tc(id).title;
    }
    const editor = lastChanged || lastEditor || editors[0];
    const history = editor?.historySize?.() || { undo: 0, redo: 0 };
    $tc("undo").disabled = !editable || !history.undo; $tc("redo").disabled = !editable || !history.redo;
    $tc("save-all").disabled = loading || !docs.slice(0, count).some((doc, i) => doc.meta && dirty(i));
    $tc("position").textContent = has ? `${current >= 0 ? current + 1 : "–"} / ${chunks.length}` : "0 / 0";
  }
  function updateCursor() {
    const editor = lastEditor || editors[0];
    if (!editor) return;
    const cursor = editor.getCursor();
    $tc("cursor").textContent = `${labels[editors.indexOf(editor)] || ""} · Dòng ${cursor.line + 1}, Cột ${cursor.ch + 1}`;
  }

  function openFind(goto = false) {
    $tc("findbar").classList.remove("hidden");
    const input = goto ? $tc("goto-input") : $tc("find-input");
    const selected = (lastEditor || editors[0])?.getSelection();
    if (!goto && selected && !selected.includes("\n")) $tc("find-input").value = selected;
    input.focus(); input.select();
    $tc("find-input").placeholder = `Tìm trong khung ${labels[editors.indexOf(lastEditor || editors[0])] || "A"}`;
  }
  function closeFind() { $tc("findbar").classList.add("hidden"); (lastEditor || editors[0])?.focus(); }
  function find(direction) {
    const editor = lastEditor || editors[0], term = $tc("find-input").value;
    if (!editor || !term) return;
    const sensitive = $tc("find-case").getAttribute("aria-pressed") === "true";
    const hay = sensitive ? editor.getValue() : editor.getValue().toLowerCase();
    const needle = sensitive ? term : term.toLowerCase();
    let total = 0, at = -1;
    while ((at = hay.indexOf(needle, at + 1)) >= 0 && total < 9999) total++;
    const start = editor.indexFromPos(editor.getCursor(direction > 0 ? "to" : "from"));
    let found = direction > 0 ? hay.indexOf(needle, start) : start > 0 ? hay.lastIndexOf(needle, start - 1) : -1;
    if (found < 0) found = direction > 0 ? hay.indexOf(needle) : hay.lastIndexOf(needle);
    if (found < 0) { $tc("find-info").textContent = "Không tìm thấy"; return; }
    const from = editor.posFromIndex(found), to = editor.posFromIndex(found + needle.length);
    editor.setSelection(from, to);
    editor.scrollIntoView({ from, to }, 120);
    $tc("find-info").textContent = `${total >= 9999 ? "9999+" : total} kết quả`;
  }
  function gotoLine() {
    const editor = lastEditor || editors[0], line = Math.max(1, Number($tc("goto-input").value) || 1);
    if (!editor) return;
    const target = Math.min(line, editor.lineCount()) - 1;
    editor.setCursor(target, 0); editor.scrollIntoView({ line: target, ch: 0 }, 160); editor.focus();
  }

  // ---- Location pane ----------------------------------------------------------------------------------------------

  const MAP_COLORS = { "left-only": "#e46b78", "right-only": "#4fb37a", change: "#e2b73c" };
  function drawMap() {
    const host = $tc("map");
    if (!merge || !host.clientHeight || page.dataset.view !== "files") return;
    let canvas = host.firstChild;
    if (!canvas) { canvas = node("canvas"); host.append(canvas); bindMap(canvas); }
    const dpr = window.devicePixelRatio || 1, width = host.clientWidth, height = host.clientHeight;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) { canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr); }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
    const bars = count === 3 ? [4, 24, 44] : [6, 40], barWidth = count === 3 ? 12 : 14;
    const slot = editor => editors.indexOf(editor);
    const y = (editor, line) => line / Math.max(editor.lineCount(), 1) * height;
    ctx.fillStyle = "#eceef1";
    bars.forEach(x => ctx.fillRect(x, 0, barWidth, height));
    allChunks.forEach(chunk => {
      if (chunk.ignored) return;
      const color = MAP_COLORS[chunk.type], active = chunks[current] === chunk;
      const li = slot(chunk.l.ed), ri = slot(chunk.r.ed);
      const ly0 = y(chunk.l.ed, chunk.l.from), ly1 = Math.max(ly0 + 2, y(chunk.l.ed, chunk.l.to));
      const ry0 = y(chunk.r.ed, chunk.r.from), ry1 = Math.max(ry0 + 2, y(chunk.r.ed, chunk.r.to));
      const lx = bars[li] + barWidth, rx = bars[ri];
      ctx.globalAlpha = active ? 0.55 : 0.28; ctx.fillStyle = color;
      ctx.beginPath(); ctx.moveTo(lx, ly0); ctx.lineTo(rx, ry0); ctx.lineTo(rx, ry1); ctx.lineTo(lx, ly1); ctx.closePath(); ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillRect(bars[li], ly0, barWidth, ly1 - ly0); ctx.fillRect(bars[ri], ry0, barWidth, ry1 - ry0);
      if (active) { ctx.strokeStyle = "#2f5fd0"; ctx.lineWidth = 1.5; ctx.strokeRect(bars[li] - 1, ly0 - 1, barWidth + 2, ly1 - ly0 + 2); ctx.strokeRect(bars[ri] - 1, ry0 - 1, barWidth + 2, ry1 - ry0 + 2); }
    });
    const center = merge.editor(), info = center.getScrollInfo();
    const top = info.top / Math.max(info.height, 1) * height, size = Math.max(8, info.clientHeight / Math.max(info.height, 1) * height);
    ctx.fillStyle = "rgba(60, 100, 190, .12)"; ctx.fillRect(0, top, width, size);
    ctx.strokeStyle = "rgba(60, 100, 190, .55)"; ctx.lineWidth = 1; ctx.strokeRect(.5, top + .5, width - 1, size - 1);
  }
  function bindMap(canvas) {
    const scrollTo = event => {
      const rect = canvas.getBoundingClientRect(), ratio = (event.clientY - rect.top) / rect.height, center = merge.editor(), info = center.getScrollInfo();
      center.scrollTo(null, Math.max(0, ratio * info.height - info.clientHeight / 2));
    };
    canvas.addEventListener("pointerdown", event => {
      const rect = canvas.getBoundingClientRect(), ratio = (event.clientY - rect.top) / rect.height;
      const hit = chunks.findIndex(chunk => [chunk.l, chunk.r].some(part => { const a = part.from / Math.max(part.ed.lineCount(), 1), b = Math.max(part.to, part.from + 1) / Math.max(part.ed.lineCount(), 1); return ratio >= a - 0.004 && ratio <= b + 0.004; }));
      if (hit >= 0) { current = hit; reveal(); return; }
      canvas.setPointerCapture(event.pointerId); canvas.dataset.drag = "1"; scrollTo(event);
    });
    canvas.addEventListener("pointermove", event => { if (canvas.dataset.drag) scrollTo(event); });
    canvas.addEventListener("pointerup", () => { delete canvas.dataset.drag; });
  }

  // ---- Menus and expand -------------------------------------------------------------------------------------------

  function closeMenus() {
    for (const [button, menu] of [["options-btn", "options-menu"], ["help-btn", "help-pop"]]) {
      $tc(menu).classList.add("hidden"); $tc(button).setAttribute("aria-expanded", "false");
    }
  }
  function toggleMenu(button, menu) {
    const open = $tc(menu).classList.contains("hidden");
    closeMenus();
    $tc(menu).classList.toggle("hidden", !open); $tc(button).setAttribute("aria-expanded", String(open));
  }
  function setExpanded(expanded) {
    $tc("files-view").classList.toggle("tc-expanded", expanded);
    $tc("expand").setAttribute("aria-pressed", String(expanded));
    editors.forEach(editor => editor.refresh()); schedule(0);
  }

  function applyCount() {
    $tc("third").classList.toggle("hidden", count !== 3);
    $tc("label-b").textContent = count === 3 ? "Giữa (mốc)" : "Phải";
  }

  // ---- Folder results ---------------------------------------------------------------------------------------------

  function fmtSize(value) {
    if (value == null) return "";
    if (value < 1024) return `${value} B`;
    return value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`;
  }
  function fmtTime(value) {
    if (!value) return "";
    const date = new Date(value * 1000), pad = n => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  const openable = row => row.kind === "file" && !["error", "skipped", "type-conflict"].includes(row.status);

  function matchesFilter(row) {
    if (row.status === "folder") return folderUi.filter === "all";
    if (folderUi.filter === "all") return true;
    if (folderUi.filter === "diff") return DIFF_STATUSES.has(row.status);
    return row.status === folderUi.filter;
  }

  function filteredRows() { return folders ? folders.rows.filter(matchesFilter) : []; }

  function renderChips() {
    const rows = folders?.rows.filter(row => row.status !== "folder") || [];
    const count = predicate => rows.filter(predicate).length;
    const defs = [["diff", "Khác biệt", count(row => DIFF_STATUSES.has(row.status))], ["different", "Khác nhau", count(row => row.status === "different")],
      ["left-only", "Chỉ trái", count(row => row.status === "left-only")], ["right-only", "Chỉ phải", count(row => row.status === "right-only")],
      ["same", "Giống nhau", count(row => row.status === "same")], ["all", "Tất cả", rows.length]];
    const errors = count(row => ["error", "skipped", "type-conflict"].includes(row.status));
    if (errors) defs.splice(4, 0, ["error", "Lỗi / bỏ qua", errors]);
    $tc("chips").replaceChildren(...defs.map(([key, label, total]) => {
      const button = node("button", `tc-chip tc-chip-${key}${folderUi.filter === key ? " active" : ""}`); button.type = "button";
      button.setAttribute("aria-pressed", String(folderUi.filter === key));
      button.append(node("span", "", label), node("b", "", String(total)));
      button.addEventListener("click", () => { folderUi.filter = key; folderUi.limit = 1500; renderFolders(); });
      return button;
    }));
  }

  function treeItems(rows) {
    const root = { children: new Map(), path: "" };
    for (const row of rows) {
      let branch = root, path = "";
      for (const part of row.path.split("/")) {
        path = path ? `${path}/${part}` : part;
        if (!branch.children.has(part)) branch.children.set(part, { name: part, path, children: new Map() });
        branch = branch.children.get(part);
      }
      branch.row = row;
    }
    const items = [];
    (function walk(branch, depth) {
      const kids = [...branch.children.values()].sort((a, b) => (b.children.size > 0) - (a.children.size > 0) || a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
      for (const child of kids) {
        const isDir = child.children.size > 0 || child.row?.kind === "directory";
        const row = child.row || { path: child.path, kind: "directory", status: "folder", left: "", right: "" };
        items.push({ row, name: child.name, dir: "", depth, isDir, open: !folderUi.collapsed.has(child.path) });
        if (isDir && !folderUi.collapsed.has(child.path)) walk(child, depth + 1);
      }
    })(root, 0);
    return items;
  }
  function flatItems(rows) {
    const { key, dir } = folderUi.sort;
    const value = row => {
      const parts = row.path.split("/");
      return { name: parts.at(-1).toLowerCase(), dir: parts.slice(0, -1).join("/").toLowerCase(), status: statusNames[row.status] }[key] ?? row[key] ?? "";
    };
    return rows.filter(row => row.status !== "folder").map(row => { const parts = row.path.split("/"); return { row, name: parts.at(-1), dir: parts.slice(0, -1).join("/"), depth: 0, isDir: row.kind === "directory" }; })
      .sort((a, b) => { const x = value(a.row), y = value(b.row); return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true })) * dir || a.row.path.localeCompare(b.row.path); });
  }

  function renderFolders() {
    if (!folders) return;
    renderChips();
    const rows = filteredRows();
    const items = folderUi.tree ? treeItems(rows) : flatItems(rows);
    const shown = items.slice(0, folderUi.limit);
    $tc("grid-empty").classList.toggle("hidden", Boolean(items.length));
    $tc("grid-empty").textContent = rows.length ? "" : "Không có mục khớp bộ lọc.";
    $tc("grid-body").innerHTML = shown.map((item, index) => {
      const { row } = item, status = row.status;
      const caret = item.isDir && folderUi.tree ? `<button type="button" class="tc-caret" data-toggle="${escapeHtml(row.path)}" aria-label="${item.open ? "Thu gọn" : "Mở rộng"}">${item.open ? "▾" : "▸"}</button>` : '<span class="tc-caret-gap"></span>';
      const icon = item.isDir ? "📁" : "📄";
      const name = `<span class="tc-name" data-depth="${item.depth}">${caret}<span class="tc-file-icon" aria-hidden="true">${icon}</span><span>${escapeHtml(item.name)}</span></span>`;
      return `<tr data-i="${index}" class="tc-r-${status}${folderUi.selected === row.path ? " selected" : ""}" title="${escapeHtml(row.detail || row.path)}">
        <td>${name}</td><td class="tc-dir">${escapeHtml(item.dir)}</td>
        <td>${status === "folder" ? "" : `<span class="tc-status tc-status-${status}">${statusNames[status]}</span>`}</td>
        <td class="tc-num">${fmtSize(row.left_size)}</td><td class="tc-num">${fmtSize(row.right_size)}</td>
        <td class="tc-time">${fmtTime(row.left_mtime)}</td><td class="tc-time">${fmtTime(row.right_mtime)}</td></tr>`;
    }).join("") + (items.length > shown.length ? `<tr class="tc-more-row"><td colspan="7"><button type="button" class="secondary-button" data-more>Hiện thêm (${items.length - shown.length} mục)</button></td></tr>` : "");
    renderedItems = shown;
    // The page CSP forbids style attributes in markup, so indentation is applied through the DOM.
    $tc("grid-body").querySelectorAll(".tc-name[data-depth]").forEach(el => { el.style.paddingLeft = `${Number(el.dataset.depth) * 16}px`; });
    folderOrder = (folderUi.tree ? flatItems(rows) : items).map(item => item.row).filter(openable);
    const selectedRow = folders.rows.find(row => row.path === folderUi.selected);
    $tc("folder-open").disabled = !selectedRow || !openable(selectedRow);
    const counts = folders.counts || {};
    $tc("folder-summary").title = `${folders.left} ↔ ${folders.right}`;
    $tc("folder-summary").textContent = `${rows.filter(row => row.status !== "folder").length} mục hiển thị · ` + (Object.entries(counts).map(([key, value]) => `${statusNames[key]}: ${value}`).join(" · ") || "Hai thư mục đều trống hoặc không có file khớp bộ lọc");
    $tc("folder-paths").innerHTML = `<span><b>Trái</b> ${escapeHtml(folders.left)}</span><span><b>Phải</b> ${escapeHtml(folders.right)}</span>`;
  }
  let renderedItems = [];

  function selectRow(path, scroll = false) {
    folderUi.selected = path;
    $tc("grid-body").querySelectorAll("tr.selected").forEach(tr => tr.classList.remove("selected"));
    const index = renderedItems.findIndex(item => item.row.path === path);
    const tr = index >= 0 ? $tc("grid-body").querySelector(`tr[data-i="${index}"]`) : null;
    tr?.classList.add("selected");
    if (scroll) tr?.scrollIntoView({ block: "nearest" });
    const row = folders?.rows.find(item => item.path === path);
    $tc("folder-open").disabled = !row || !openable(row);
  }

  async function openPair(row, { stay = false } = {}) {
    if (!row || !openable(row)) return;
    if (!stay && !await allowReplace()) return;
    folderUi.selected = row.path;
    await loadPaths([row.left || "", row.right || ""].map(path => path), { from: "folder" });
  }
  function configureNavigation() {
    const fromFolder = origin === "folder";
    $tc("file-nav").classList.toggle("hidden", !fromFolder);
    $tc("back-label").textContent = fromFolder ? "Thư mục" : "Chọn lại";
    $tc("back").title = fromFolder ? "Quay lại danh sách thư mục (Ctrl+O)" : "Chọn file khác (Ctrl+O)";
  }
  function openRelative(delta) {
    const index = folderOrder.findIndex(row => row.path === folderUi.selected);
    const next = folderOrder[index < 0 ? (delta > 0 ? 0 : folderOrder.length - 1) : index + delta];
    if (!next) { message("Đã hết cặp file trong danh sách thư mục.", true); return; }
    openPair(next);
  }

  function scanFolders() {
    const params = { left: $tc("folder-left").value.trim(), right: $tc("folder-right").value.trim(), include: $tc("include").value, exclude: $tc("exclude").value };
    if (!params.left || !params.right) { selectMessage("Hãy chọn đủ hai thư mục.", true); return; }
    folderParams = params;
    selectMessage("Đang quét… xem tiến độ ở nút LOG.");
    setTimeout(() => { if ($tc("select-message").textContent.startsWith("Đang quét")) selectMessage(""); }, 8000);
    startAction("text_folder_compare", params);
  }

  // ---- Public hook used by the job runner ----------------------------------------------------------------------

  window.textCompare = {
    showFolders(result) {
      folders = result;
      folderUi.selected = ""; folderUi.collapsed = new Set(); folderUi.limit = 1500;
      if (folderParams) remember({ kind: "folders", ...folderParams });
      selectMessage("");
      showView("folder"); renderFolders();
    },
  };

  // ---- Wiring -------------------------------------------------------------------------------------------------------

  function bindOptions() {
    const map = { "opt-ws": "ws", "opt-case": "case", "opt-blank": "blank", "only-diff": "onlyDiff", moved: "moved", lines: "lines", wrap: "wrap", editable: "editable" };
    for (const [id, key] of Object.entries(map)) {
      $tc(id).checked = Boolean(opts[key]);
      $tc(id).addEventListener("change", () => {
        opts[key] = $tc(id).checked; saveOptions();
        // Wrapping and collapsing change line layout, which only a rebuild re-aligns reliably.
        if (key === "wrap" || key === "onlyDiff") { if (merge) { syncDocs(); editors = []; build(); } } else applyOptions();
      });
    }
    $tc("language").value = opts.language;
    $tc("language").addEventListener("change", () => { opts.language = $tc("language").value; saveOptions(); applyOptions(); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindOptions(); applyCount(); renderRecent(); icons(page);
    page.querySelectorAll("[data-tc-mode]").forEach(button => button.addEventListener("click", () => selectMode(button.dataset.tcMode)));
    $tc("count").addEventListener("change", () => { count = Number($tc("count").value); applyCount(); });
    $tc("swap-paths").addEventListener("click", () => { const a = $tc("path-0"), b = $tc("path-1"); [a.value, b.value] = [b.value, a.value]; });
    $tc("file-select").addEventListener("submit", event => {
      event.preventDefault();
      const paths = Array.from({ length: Number($tc("count").value) }, (_, i) => $tc(`path-${i}`).value.trim());
      if (paths.some(path => !path)) { selectMessage("Hãy nhập đủ đường dẫn cho mọi file, hoặc bấm “Dán văn bản…” để so sánh nội dung dán.", true); return; }
      loadPaths(paths);
    });
    $tc("blank").addEventListener("click", openBlank);
    $tc("recent-clear").addEventListener("click", () => { store.write(RECENT_KEY, []); renderRecent(); });
    $tc("folder-form").addEventListener("submit", event => { event.preventDefault(); scanFolders(); });

    $tc("back").addEventListener("click", goBack);
    $tc("refresh").addEventListener("click", refreshFiles);
    $tc("swap").addEventListener("click", swapSides);
    $tc("save-all").addEventListener("click", commands.save);
    $tc("undo").addEventListener("click", () => undoRedo("undo")); $tc("redo").addEventListener("click", () => undoRedo("redo"));
    for (const [id, name] of [["first", "first"], ["prev", "prev"], ["next", "next"], ["last", "last"], ["copy-right", "copyRight"], ["copy-left", "copyLeft"], ["copy-right-next", "copyRightNext"], ["copy-left-next", "copyLeftNext"]]) $tc(id).addEventListener("click", commands[name]);
    $tc("copy-all-right").addEventListener("click", () => copyAll("right")); $tc("copy-all-left").addEventListener("click", () => copyAll("left"));
    $tc("file-prev").addEventListener("click", () => openRelative(-1)); $tc("file-next").addEventListener("click", () => openRelative(1));
    $tc("find-btn").addEventListener("click", () => openFind());
    $tc("options-btn").addEventListener("click", event => { event.stopPropagation(); toggleMenu("options-btn", "options-menu"); });
    $tc("help-btn").addEventListener("click", event => { event.stopPropagation(); toggleMenu("help-btn", "help-pop"); });
    document.addEventListener("click", event => { if (!event.target.closest(".tc-menu-wrap")) closeMenus(); });
    $tc("expand").addEventListener("click", () => setExpanded(!$tc("files-view").classList.contains("tc-expanded")));

    $tc("find-input").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); find(event.shiftKey ? -1 : 1); } });
    $tc("find-input").addEventListener("input", () => { $tc("find-info").textContent = ""; });
    $tc("find-next").addEventListener("click", () => find(1)); $tc("find-prev").addEventListener("click", () => find(-1));
    $tc("find-case").addEventListener("click", () => $tc("find-case").setAttribute("aria-pressed", String($tc("find-case").getAttribute("aria-pressed") !== "true")));
    $tc("goto-input").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); gotoLine(); } });
    $tc("goto-go").addEventListener("click", gotoLine); $tc("find-close").addEventListener("click", closeFind);

    // Keys pressed outside the editors (inside them CodeMirror's extraKeys already handled the event).
    document.addEventListener("keydown", event => {
      if (!page.classList.contains("active")) return;
      if (event.key === "Escape") {
        if (!$tc("options-menu").classList.contains("hidden") || !$tc("help-pop").classList.contains("hidden")) { closeMenus(); return; }
        if (page.dataset.view === "files" && !$tc("findbar").classList.contains("hidden")) { closeFind(); return; }
        if ($tc("files-view").classList.contains("tc-expanded")) setExpanded(false);
        return;
      }
      if (page.dataset.view !== "files" || event.defaultPrevented) return;
      const names = [];
      if (event.ctrlKey) names.push("Ctrl"); if (event.altKey) names.push("Alt");
      const key = { ArrowDown: "Down", ArrowUp: "Up", ArrowLeft: "Left", ArrowRight: "Right" }[event.key] || (event.key.length === 1 ? event.key.toUpperCase() : event.key);
      const combo = [...names, key].join("-"), command = keyTable[combo];
      // Inside the find / goto boxes only the global shortcuts apply, so Alt+arrows there never merges by accident.
      const typing = event.target.matches("input, select, textarea");
      if (command && (!typing || /^(Ctrl-S|Ctrl-F|Ctrl-G|F5|Ctrl-O)$/.test(combo))) { event.preventDefault(); commands[command](); }
    });

    // Folder grid.
    $tc("tree").checked = folderUi.tree;
    $tc("tree").addEventListener("change", () => { folderUi.tree = $tc("tree").checked; renderFolders(); });
    $tc("expand-all").addEventListener("click", () => { folderUi.collapsed = new Set(); renderFolders(); });
    $tc("collapse-all").addEventListener("click", () => { folderUi.collapsed = new Set((folders?.rows || []).filter(row => row.kind === "directory").map(row => row.path)); renderFolders(); });
    $tc("folder-back").addEventListener("click", () => showView("select"));
    $tc("folder-rescan").addEventListener("click", () => { if (folderParams) startAction("text_folder_compare", folderParams); else showView("select"); });
    $tc("folder-open").addEventListener("click", () => openPair(folders?.rows.find(row => row.path === folderUi.selected)));
    page.querySelectorAll(".tc-grid th[data-sort]").forEach(th => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      folderUi.sort = { key, dir: folderUi.sort.key === key ? -folderUi.sort.dir : 1 };
      if (folderUi.tree) { folderUi.tree = false; $tc("tree").checked = false; }
      renderFolders();
    }));
    $tc("grid-body").addEventListener("click", event => {
      const toggle = event.target.closest("[data-toggle]");
      if (toggle) { const path = toggle.dataset.toggle; folderUi.collapsed.has(path) ? folderUi.collapsed.delete(path) : folderUi.collapsed.add(path); renderFolders(); return; }
      if (event.target.closest("[data-more]")) { folderUi.limit += 1500; renderFolders(); return; }
      const tr = event.target.closest("tr[data-i]");
      if (tr) selectRow(renderedItems[Number(tr.dataset.i)].row.path);
    });
    $tc("grid-body").addEventListener("dblclick", event => {
      const tr = event.target.closest("tr[data-i]");
      if (!tr) return;
      const item = renderedItems[Number(tr.dataset.i)];
      if (item.isDir && folderUi.tree) { const path = item.row.path; folderUi.collapsed.has(path) ? folderUi.collapsed.delete(path) : folderUi.collapsed.add(path); renderFolders(); }
      else openPair(item.row);
    });
    $tc("folder-results").addEventListener("keydown", event => {
      const index = renderedItems.findIndex(item => item.row.path === folderUi.selected);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const next = renderedItems[Math.max(0, Math.min(renderedItems.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
        if (next) selectRow(next.row.path, true);
      } else if (event.key === "Enter" && index >= 0) { event.preventDefault(); openPair(renderedItems[index].row); }
    });

    new ResizeObserver(() => { if (page.classList.contains("active") && page.dataset.view === "files") { editors.forEach(editor => editor.refresh()); drawMap(); } }).observe($tc("editor"));
    new MutationObserver(() => { if (page.classList.contains("active") && page.dataset.view === "files") requestAnimationFrame(() => { editors.forEach(editor => editor.refresh()); drawMap(); }); }).observe(page, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("beforeunload", event => { if (anyDirty()) { event.preventDefault(); event.returnValue = ""; } });
    selectMode("files");
  });
})();
