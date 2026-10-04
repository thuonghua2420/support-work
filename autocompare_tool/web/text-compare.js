"use strict";
(() => {
  const $tc = id => document.getElementById(`tc-${id}`);
  const page = document.getElementById("page-text-compare");
  const labels = ["A", "B", "C"];
  const docs = Array.from({ length: 3 }, () => ({ text: "", savedText: "", meta: null, eol: "original" }));
  let editors = [], merge = null, count = 2, loading = false, timer, chunks = [], current = -1, marked = [], folders = null;
  const normalize = text => text.replace(/\r\n?/g, "\n");
  const eolName = eol => ({ "\n": "LF", "\r\n": "CRLF", "\r": "CR", mixed: "EOL hỗn hợp" }[eol] || "LF");
  const statusNames = { same: "Giống byte", different: "Khác nội dung", "left-only": "Left only", "right-only": "Right only", "type-conflict": "Khác loại", error: "Lỗi đọc", skipped: "Bỏ qua liên kết", folder: "Thư mục" };
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function message(text, error = false) { $tc("message").textContent = text; $tc("message").classList.toggle("tc-error", error); }
  function syncDocs() { editors.forEach((editor, i) => { docs[i].text = editor.getValue(); }); }
  function dirty(i) { return docs[i].text !== docs[i].savedText; }
  async function allowReplace() { syncDocs(); return !docs.some((_, i) => dirty(i)) || await confirmAction("Bỏ bản chỉnh sửa chưa lưu?", "Mở cặp file khác sẽ thay nội dung trong các khung. Hãy lưu hoặc tải bản sao nếu cần giữ chỉnh sửa."); }
  function modeFor(i) {
    if ($tc("language").value !== "auto") return $tc("language").value;
    const found = CodeMirror.findModeByFileName(docs[i].meta?.name || "");
    return found && CodeMirror.modes[found.mode] ? found.mime : "text/plain";
  }
  function updateOptions() {
    editors.forEach((editor, i) => {
      editor.setOption("mode", modeFor(i));
      editor.setOption("lineWrapping", $tc("wrap").checked);
      editor.setOption("readOnly", !$tc("editable").checked);
    });
    schedule();
  }
  function build() {
    syncDocs(); marked = []; current = -1;
    $tc("editor").replaceChildren();
    merge = CodeMirror.MergeView($tc("editor"), {
      value: docs[count === 3 ? 1 : 0].text,
      origLeft: count === 3 ? docs[0].text : null,
      origRight: docs[count - 1].text,
      allowEditingOriginals: true, lineNumbers: true, lineWrapping: $tc("wrap").checked,
      connect: "align", revertButtons: false, ignoreWhitespace: false,
      gutters: ["CodeMirror-linenumbers", "tc-move-gutter"], indentUnit: 2, tabSize: 4,
      viewportMargin: 15, inputStyle: "textarea",
      extraKeys: { "Alt-Up": () => navigate(-1), "Alt-Down": () => navigate(1) },
    });
    editors = count === 3 ? [merge.leftOriginal(), merge.editor(), merge.rightOriginal()] : [merge.editor(), merge.rightOriginal()];
    editors.forEach((editor, i) => {
      editor.getInputField().setAttribute("aria-label", `Nội dung file ${labels[i]}`);
      editor.on("beforeChange", (_cm, change) => {
        const incoming = change.text.join("\n");
        const removed = editor.getRange(change.from, change.to).length;
        if (editor.getValue().length - removed + incoming.length > 1_000_000 || editor.lineCount() - (change.to.line - change.from.line) + change.text.length - 1 > 10000) {
          change.cancel(); message("Editor giới hạn 1 MB / 10.000 dòng. Nội dung vừa nhập vượt giới hạn.", true);
        }
      });
      editor.on("change", () => { docs[i].text = editor.getValue(); refreshHeaders(); schedule(); });
      editor.on("updateDiff", schedule);
    });
    $tc("sources").classList.toggle("tc-three", count === 3);
    $tc("headings").classList.toggle("tc-three", count === 3);
    $tc("third").classList.toggle("hidden", count !== 3);
    refreshHeaders(true); updateOptions();
    requestAnimationFrame(() => { editors.forEach(editor => editor.refresh()); refreshDiff(); });
  }
  function refreshHeaders(force = false) {
    const active = document.activeElement;
    if (!force && $tc("headings").contains(active)) return;
    $tc("headings").replaceChildren(...editors.map((_, i) => {
      const doc = docs[i], box = node("div", `tc-document${dirty(i) ? " tc-dirty" : ""}`);
      const title = node("strong", "", `${labels[i]} · ${doc.meta?.name || "Văn bản mới"}${count === 3 && i === 1 ? " · mốc đối chiếu" : ""}`);
      title.title = doc.meta?.path || "Nội dung chỉ nằm trong trình duyệt";
      box.append(title, node("small", "", doc.meta ? `${doc.meta.encoding} · ${eolName(doc.meta.eol)} · ${doc.meta.size.toLocaleString()} byte` : "Bản nháp · UTF-8"));
      const actions = node("div", "tc-document-actions");
      const save = node("button", "secondary-button", "Lưu file"); save.type = "button"; save.disabled = !doc.meta || loading;
      save.addEventListener("click", () => saveDoc(i));
      const download = node("button", "ghost-button", "Tải UTF-8"); download.type = "button";
      download.title = "Tải bản sao UTF-8, xuống dòng LF; không thay đổi file gốc";
      download.addEventListener("click", () => {
        const url = URL.createObjectURL(new Blob([editors[i].getValue()], { type: "text/plain;charset=utf-8" }));
        const link = node("a"); link.href = url; link.download = doc.meta?.name || `File-${labels[i]}.txt`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
      const eol = node("select"); eol.setAttribute("aria-label", `Xuống dòng khi lưu file ${labels[i]}`);
      for (const [value, label] of [["original", "EOL: giữ gốc"], ["\n", "EOL: LF"], ["\r\n", "EOL: CRLF"]]) { const option = node("option", "", label); option.value = value; eol.append(option); }
      eol.value = doc.eol; eol.addEventListener("change", () => { doc.eol = eol.value; });
      actions.append(save, download, eol); box.append(actions); return box;
    }));
  }
  async function saveDoc(i) {
    const doc = docs[i];
    if (loading || !doc.meta) return;
    const text = editors[i].getValue();
    if (!await confirmAction("Ghi đè file văn bản?", `Lưu nội dung khung ${labels[i]} vào:\n${doc.meta.path}\n\nGiữ encoding gốc; EOL: ${doc.eol === "original" ? "giữ gốc" : eolName(doc.eol)}. Thao tác không tạo bản backup tự động. File đổi bên ngoài sẽ bị chặn ghi đè.`)) return;
    loading = true; refreshHeaders();
    try {
      const saved = await api("/api/text-compare/save", { method: "POST", body: { token: doc.meta.token, sha256: doc.meta.sha256, text, eol: doc.eol, confirmed: true } });
      doc.savedText = text; doc.meta.sha256 = saved.sha256; doc.meta.size = saved.size;
      if (doc.eol !== "original") doc.meta.eol = doc.eol;
      message(`Đã lưu file ${labels[i]}.`);
    } catch (error) { message(error.message, true); }
    finally { loading = false; refreshHeaders(); schedule(); }
  }
  async function loadPaths(paths, replace = true) {
    if (loading || (replace && !await allowReplace())) return false;
    loading = true; $tc("open").disabled = true; $tc("count").disabled = true;
    editors.forEach(editor => editor.setOption("readOnly", true)); message("Đang đọc file…");
    try {
      const loaded = await Promise.all(paths.map(path => path ? api("/api/text-compare/open", { method: "POST", body: { path } }) : null));
      count = paths.length; $tc("count").value = String(count);
      docs.forEach((_, i) => {
        const meta = loaded[i] || null;
        docs[i] = { text: meta ? normalize(meta.text) : "", savedText: meta ? normalize(meta.text) : "", meta, eol: "original" };
      });
      editors = []; build(); message("Đã mở file. Thay đổi trong editor chỉ là bản nháp cho tới khi bạn lưu."); return true;
    } catch (error) { message(error.message, true); showToast(error.message, "error"); return false; }
    finally { loading = false; $tc("open").disabled = false; $tc("count").disabled = false; refreshHeaders(true); updateOptions(); }
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(refreshDiff, 450); }
  function clearMoved() { marked.forEach(([editor, handle]) => editor.removeLineClass(handle, "background", "tc-moved-line")); marked = []; editors.forEach(editor => editor.clearGutter("tc-move-gutter")); }
  function movedPair(edit, orig, ranges) {
    const all = editor => {
      const index = new Map();
      editor.eachLine(handle => { const text = handle.text; const line = editor.getLineNumber(handle); if (text.trim().length > 2) index.set(text, index.has(text) ? -1 : line); });
      return index;
    };
    const a = all(edit), b = all(orig), changedA = new Set(), changedB = new Set();
    ranges.forEach(c => { for (let n = c.editFrom; n < c.editTo; n++) changedA.add(n); for (let n = c.origFrom; n < c.origTo; n++) changedB.add(n); });
    let total = 0;
    for (const [text, from] of a) {
      const to = b.get(text);
      if (from < 0 || to === undefined || to < 0 || from === to || !changedA.has(from) || !changedB.has(to)) continue;
      total++;
      for (const [editor, line, other, destination] of [[edit, from, orig, to], [orig, to, edit, from]]) {
        const handle = editor.addLineClass(line, "background", "tc-moved-line"); marked.push([editor, handle]);
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
    if (!merge) return;
    const central = merge.editor(), right = merge.rightChunks() || [], left = merge.leftChunks() || [];
    chunks = [...left.map(c => ({ ...c, other: merge.leftOriginal() })), ...right.map(c => ({ ...c, other: merge.rightOriginal() }))].sort((a, b) => a.editFrom - b.editFrom);
    clearMoved();
    let moved = 0;
    if ($tc("moved").checked) { moved += movedPair(central, merge.rightOriginal(), right); if (count === 3) moved += movedPair(central, merge.leftOriginal(), left); }
    const draft = docs.slice(0, count).some((_, i) => dirty(i));
    const loaded = docs.slice(0, count).every(doc => doc.meta);
    const byteEqual = loaded && !draft && docs.slice(1, count).every(doc => doc.meta.sha256 === docs[0].meta.sha256);
    let summary = chunks.length ? `${chunks.length} vùng sai khác${count === 3 ? ` · A↔B: ${left.length} / B↔C: ${right.length}` : ""}` : "Nội dung dòng giống nhau";
    if (!chunks.length && loaded && !draft) summary = byteEqual ? "Các bản đã mở giống nhau 100% về byte" : "Nội dung dòng giống · encoding / BOM / xuống dòng khác";
    if (moved) summary += ` · ${moved} dòng di chuyển`;
    if (draft) summary += " · đang so sánh bản nháp";
    $tc("summary").textContent = summary;
    current = Math.min(current, chunks.length - 1); $tc("position").textContent = `${current + 1} / ${chunks.length}`;
    $tc("prev").disabled = $tc("next").disabled = !chunks.length;
    const canvas = node("canvas"); canvas.width = 26; canvas.height = 800;
    canvas.setAttribute("aria-label", `${chunks.length} vùng sai khác; dùng nút Trước/Sau để điều hướng bằng bàn phím`);
    const ctx = canvas.getContext("2d"); const lines = Math.max(central.lineCount(), 1);
    chunks.forEach((chunk, i) => { ctx.fillStyle = i === current ? "#5068ac" : "#d6ad53"; ctx.fillRect(4, chunk.editFrom / lines * 800, 18, Math.max(4, (chunk.editTo - chunk.editFrom) / lines * 800)); });
    canvas.addEventListener("click", event => {
      const line = (event.clientY - canvas.getBoundingClientRect().top) / canvas.getBoundingClientRect().height * lines;
      if (!chunks.length) return;
      current = chunks.reduce((best, chunk, i) => Math.abs(chunk.editFrom - line) < Math.abs(chunks[best].editFrom - line) ? i : best, 0); reveal();
    });
    $tc("map").replaceChildren(canvas);
  }
  function reveal() {
    const chunk = chunks[current]; if (!chunk) return;
    merge.editor().scrollIntoView({ line: chunk.editFrom, ch: 0 }, 80);
    chunk.other.scrollIntoView({ line: chunk.origFrom, ch: 0 }, 80);
    merge.editor().setCursor(Math.min(chunk.editFrom, merge.editor().lastLine()), 0);
    $tc("position").textContent = `${current + 1} / ${chunks.length}`;
  }
  function navigate(direction) { if (chunks.length) { current = current < 0 ? (direction > 0 ? 0 : chunks.length - 1) : (current + direction + chunks.length) % chunks.length; reveal(); } }
  function tab(name) {
    page.querySelectorAll("[data-tc-tab]").forEach(button => button.classList.toggle("active", button.dataset.tcTab === name));
    $tc("text-panel").classList.toggle("hidden", name !== "text"); $tc("folder-panel").classList.toggle("hidden", name !== "folder");
    if (name === "text") requestAnimationFrame(() => editors.forEach(editor => editor.refresh()));
  }
  async function openPair(row) {
    if (row.kind !== "file" || ["error", "skipped", "type-conflict"].includes(row.status)) return;
    if (!await allowReplace()) return;
    if (await loadPaths([row.left, row.right], false)) {
      $tc("path-0").value = row.left; $tc("path-1").value = row.right; tab("text");
    }
  }
  function fileRow(row, name) {
    const item = node("div", "tc-file-row");
    const button = node("button", "", name || row.path); button.type = "button"; button.title = row.detail || row.path;
    button.disabled = row.kind !== "file" || ["error", "skipped", "type-conflict"].includes(row.status);
    button.addEventListener("click", () => openPair(row));
    const status = node("span", `tc-status tc-status-${row.status}`, statusNames[row.status]); status.title = row.detail || "";
    item.append(button, status); if (row.detail) item.title = row.detail; return item;
  }
  function renderFolders() {
    if (!folders) return;
    const filter = $tc("folder-status").value;
    const rows = folders.rows.filter(row => filter === "all" || (filter === "changes" ? !["same", "folder"].includes(row.status) : filter === "error" ? ["error", "skipped"].includes(row.status) : row.status === filter));
    const box = $tc("folder-results"); box.replaceChildren();
    if (!rows.length) { box.append(node("p", "empty-note", "Không có mục khớp bộ lọc.")); return; }
    function appendPaged(container, entries, create) {
      let offset = 0;
      function more() {
        container.querySelector(":scope > .tc-more")?.remove();
        entries.slice(offset, offset + 300).forEach(entry => container.append(create(entry))); offset += 300;
        if (offset < entries.length) { const button = node("button", "secondary-button tc-more", `Hiện thêm (${entries.length - offset} mục)`); button.type = "button"; button.addEventListener("click", more); container.append(button); }
      }
      more();
    }
    if (!$tc("tree").checked) { appendPaged(box, rows, row => fileRow(row)); return; }
    const root = { children: new Map() };
    for (const row of rows) {
      let branch = root;
      for (const name of row.path.split("/")) { if (!branch.children.has(name)) branch.children.set(name, { name, children: new Map() }); branch = branch.children.get(name); }
      branch.row = row;
    }
    function renderBranch(branch) {
      if (!branch.children.size && branch.row?.kind !== "directory") return fileRow(branch.row, branch.name);
      const details = node("details", "tc-tree-branch");
      const summary = node("summary", "", `▸ ${branch.name} /`);
      if (branch.row && branch.row.status !== "folder") summary.append(node("span", `tc-status tc-status-${branch.row.status}`, statusNames[branch.row.status]));
      const children = node("div"); details.append(summary, children);
      details.addEventListener("toggle", () => { if (details.open && !children.childNodes.length) appendPaged(children, [...branch.children.values()], renderBranch); });
      return details;
    }
    appendPaged(box, [...root.children.values()], renderBranch);
  }
  window.textCompare = { showFolders(result) {
    folders = result;
    if (!$tc("folder-left").value) $tc("folder-left").value = result.left;
    if (!$tc("folder-right").value) $tc("folder-right").value = result.right;
    $tc("folder-summary").title = `${result.left} ↔ ${result.right}`;
    $tc("folder-summary").textContent = Object.entries(result.counts).map(([key, value]) => `${statusNames[key]}: ${value}`).join(" · ") || "Hai thư mục đều trống / không có file khớp bộ lọc.";
    renderFolders();
  } };
  document.addEventListener("DOMContentLoaded", () => {
    build();
    page.querySelectorAll("[data-tc-tab]").forEach(button => button.addEventListener("click", () => tab(button.dataset.tcTab)));
    $tc("count").addEventListener("change", () => { count = Number($tc("count").value); build(); });
    $tc("open").addEventListener("click", () => {
      const paths = Array.from({ length: count }, (_, i) => $tc(`path-${i}`).value.trim());
      if (!paths.some(Boolean)) { refreshDiff(); message("Dán nội dung vào các khung để so sánh, hoặc chọn đường dẫn file."); return; }
      loadPaths(paths);
    });
    for (const name of ["wrap", "editable", "language"]) $tc(name).addEventListener("change", updateOptions);
    $tc("moved").addEventListener("change", schedule);
    $tc("prev").addEventListener("click", () => navigate(-1)); $tc("next").addEventListener("click", () => navigate(1));
    $tc("folder-form").addEventListener("submit", event => { event.preventDefault(); startAction("text_folder_compare", { left: $tc("folder-left").value, right: $tc("folder-right").value, include: $tc("include").value, exclude: $tc("exclude").value }); });
    $tc("folder-status").addEventListener("change", renderFolders); $tc("tree").addEventListener("change", renderFolders);
    $tc("expand").addEventListener("click", () => {
      const expanded = $tc("text-panel").classList.toggle("tc-expanded");
      $tc("expand").textContent = expanded ? "Thu nhỏ" : "Phóng to";
      $tc("expand").setAttribute("aria-pressed", String(expanded));
      editors.forEach(editor => editor.refresh());
    });
    document.addEventListener("keydown", event => { if (event.key === "Escape" && $tc("text-panel").classList.contains("tc-expanded")) $tc("expand").click(); });
    new ResizeObserver(() => { if (page.classList.contains("active")) editors.forEach(editor => editor.refresh()); }).observe($tc("editor"));
    new MutationObserver(() => { if (page.classList.contains("active")) requestAnimationFrame(() => editors.forEach(editor => editor.refresh())); }).observe(page, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("beforeunload", event => { syncDocs(); if (docs.some((_, i) => dirty(i))) { event.preventDefault(); event.returnValue = ""; } });
  });
})();
