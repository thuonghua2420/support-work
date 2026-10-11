"use strict";
(() => {
  const el = id => document.getElementById(`sr-${id}`);
  const page = document.getElementById("page-search-replace");
  let root = "", session = "", generation = 0, previewVersion = 0, cursor = 0;
  let files = [], active = null, editors = [], marks = [], running = false, complete = false;
  let replaceMode = false, plan = null, timer = null, previewTimer = null, searchTimer = null, writing = false;
  const pressed = id => el(id).getAttribute("aria-pressed") === "true";
  const request = (operation, body = {}) => api(`/api/search-replace/${operation}`, { method: "POST", body });
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function message(text, error = false) {
    el("summary").textContent = text;
    el("summary").classList.toggle("sr-error", error);
  }
  function viewMessage(text, error = false) {
    el("view-status").textContent = text;
    el("view-status").classList.toggle("sr-error", error);
  }
  function replacementOptions() {
    return { replacement: el("replacement").value, preserve_case: pressed("preserve") };
  }
  function invalidatePlan() {
    plan = null;
    el("review-bar").classList.add("hidden");
  }
  function controls() {
    el("cancel").disabled = !running || writing;
    el("search").disabled = writing;
    el("replace-all").disabled = !complete || !files.length || writing;
    el("apply-plan").disabled = !plan || writing;
    page.classList.toggle("sr-writing", writing);
  }
  async function stop() {
    const old = session;
    generation += 1;
    clearTimeout(timer);
    running = false; complete = false;
    controls();
    if (old) await request("cancel", { id: old }).catch(() => {});
  }
  async function load() {
    if (writing) return;
    try {
      await stop();
      const loaded = await request("load", { root: el("root").value.trim() });
      root = loaded.root; el("root").value = root;
      resetResults();
      message(`Đã load: ${root}`);
      if (el("query").value) await search();
      else el("query").focus();
    } catch (error) { message(error.message, true); }
  }
  function resetResults() {
    session = ""; files = []; active = null; cursor = 0; complete = false;
    previewVersion += 1;
    invalidatePlan();
    el("results").replaceChildren();
    el("warnings").classList.add("hidden");
    controls();
  }
  async function search(keepViewer = false) {
    if (writing) return;
    clearTimeout(searchTimer);
    await stop();
    resetResults();
    if (!keepViewer) { el("filename").textContent = "Chọn kết quả để xem file"; }
    const version = generation;
    if (!el("query").value) { message("Nhập nội dung cần tìm."); return; }
    try {
      const loaded = await request("load", { root: el("root").value.trim() });
      if (version !== generation) return;
      root = loaded.root;
      const result = await request("start", {
        root, query: el("query").value, include: el("include").value, exclude: el("exclude").value,
        encoding: el("encoding").value, match_case: pressed("case"), whole_word: pressed("word"), regex: pressed("regex"),
      });
      if (version !== generation) { await request("cancel", { id: result.id }).catch(() => {}); return; }
      session = result.id; running = true; controls(); message("Đang tìm kiếm…");
      poll(version);
    } catch (error) { if (version === generation) message(error.message, true); }
  }
  async function poll(version) {
    try {
      const result = await request("poll", { id: session, cursor });
      if (version !== generation) return;
      cursor = result.cursor;
      files.push(...result.files);
      appendFiles(result.files);
      message(`${result.count || 0} kết quả trong ${files.length} file · đã quét ${result.scanned || 0}${result.done ? ` · ${result.elapsed ?? "—"}s` : " · đang tìm…"}`);
      if (result.warnings?.length) {
        el("warnings").classList.remove("hidden");
        el("warnings").querySelector("summary").textContent = `File bỏ qua / lỗi (${result.skipped || result.warnings.length})`;
        el("warning-text").textContent = result.warnings.join("\n");
      }
      if (result.done && !result.has_more) {
        running = false; complete = !result.error && !result.limited;
        if (result.error) message(result.error, true);
        if (result.limited) message("Kết quả vượt giới hạn. Thu hẹp include/exclude rồi tìm lại để replace.", true);
        controls();
      } else timer = setTimeout(() => poll(version), 180);
    } catch (error) {
      if (version !== generation) return;
      running = false; complete = false; controls(); message(error.message, true);
    }
  }
  function actionButton(text, title, action) {
    const button = make("button", "sr-result-action", text);
    button.type = "button"; button.title = title; button.setAttribute("aria-label", title);
    button.addEventListener("click", event => { event.preventDefault(); event.stopPropagation(); action(); });
    return button;
  }
  function appendFiles(items) {
    const fragment = document.createDocumentFragment();
    items.forEach(file => {
      const group = make("details", "sr-file-group"); group.open = true; group.dataset.fileId = file.id;
      const heading = make("summary", "sr-file-heading");
      const label = make("span", "sr-file-label", file.path); label.title = `${file.path} · ${file.encoding}`;
      heading.append(label, make("span", "sr-count", String(file.matches.length)),
        actionButton("⇄", `Replace trong ${file.path}`, () => prepare(file.id)),
        actionButton("×", `Bỏ ${file.path} khỏi kết quả`, () => dismiss(file.id)));
      group.append(heading);
      let rendered = 0;
      const list = make("div", "sr-file-matches");
      const more = actionButton("Xem thêm", "Hiển thị thêm 100 kết quả", renderChunk);
      function renderChunk() {
        file.matches.slice(rendered, rendered + 100).forEach(match => {
          const row = make("div", "sr-match-row"); row.dataset.fileId = file.id; row.dataset.matchId = match.id;
          const button = make("button", "sr-match"); button.type = "button";
          button.title = `${file.path}:${match.line}:${match.column}`;
          const snippet = make("span", "sr-snippet");
          const chars = Array.from(match.snippet);
          snippet.append(document.createTextNode(chars.slice(0, match.highlight_start).join("")),
            make("mark", "", chars.slice(match.highlight_start, match.highlight_end).join("") || "│"),
            document.createTextNode(chars.slice(match.highlight_end).join("")));
          button.append(make("span", "sr-line", String(match.line)), snippet);
          button.addEventListener("click", () => openFile(file.id, match.id));
          row.append(button, actionButton("⇄", "Replace kết quả này", () => prepare(file.id, match.id)),
            actionButton("×", "Bỏ kết quả này", () => dismiss(file.id, match.id)));
          list.append(row);
        });
        rendered += 100;
        more.hidden = rendered >= file.matches.length;
      }
      renderChunk(); group.append(list, more); fragment.append(group);
    });
    el("results").append(fragment);
  }
  // Dismiss is sent to the server, so Replace All has exactly the visible scope.
  async function dismiss(fileId, matchId = null) {
    if (writing || running) return;
    try {
      await request("dismiss", { id: session, file_id: fileId, match_id: matchId });
      invalidatePlan();
      if (matchId === null) files = files.filter(file => file.id !== fileId);
      else {
        const file = files.find(file => file.id === fileId);
        file.matches = file.matches.filter(match => match.id !== matchId);
        files = files.filter(file => file.matches.length);
      }
      el("results").replaceChildren(); appendFiles(files);
      if (active?.fileId === fileId) active = null;
      message(`${files.reduce((sum, file) => sum + file.matches.length, 0)} kết quả trong ${files.length} file`);
      controls();
    } catch (error) { message(error.message, true); }
  }
  function editorPosition(text, line, column) {
    // Backend offsets count Unicode code points; CodeMirror uses UTF-16 units.
    const content = text.split(/\r\n|\r|\n/)[line - 1] || "";
    return { line: line - 1, ch: Array.from(content).slice(0, column - 1).join("").length };
  }
  function modeFor(path) {
    const mode = CodeMirror.findModeByFileName(path);
    return mode && CodeMirror.modes[mode.mode] ? mode.mime : "text/plain";
  }
  async function openFile(fileId, matchId = null, scope = plan?.scope) {
    const file = files.find(item => item.id === fileId);
    if (!file || writing) return;
    const version = ++previewVersion;
    active = { fileId, matchId };
    document.querySelectorAll(".sr-match-row.active").forEach(row => row.classList.remove("active"));
    const selected = el("results").querySelector(`[data-file-id="${fileId}"][data-match-id="${matchId}"]`);
    selected?.classList.add("active");
    viewMessage("Đang mở…");
    try {
      if (scope?.file_id != null && scope.file_id !== fileId) {
        invalidatePlan(); scope = null;
      }
      const result = await request("preview", { id: session, file_id: fileId, ...replacementOptions(),
        ...(scope?.match_id != null ? { match_id: scope.match_id } : {}) });
      if (version !== previewVersion) return;
      el("filename").textContent = file.path; el("filename").title = `${root}/${file.path}`;
      el("file-meta").textContent = `${result.encoding}${result.bom ? " · BOM" : ""} · ${result.eol} · ${file.matches.length} matches`;
      el("editor").replaceChildren(); marks = [];
      el("editor-labels").lastElementChild.textContent = "Sau replace · chưa ghi";
      const options = { readOnly: true, lineNumbers: true, lineWrapping: el("wrap").checked,
        mode: modeFor(file.path), viewportMargin: 15, inputStyle: "textarea" };
      if (replaceMode) {
        const merge = CodeMirror.MergeView(el("editor"), { ...options, value: result.text,
          origRight: result.after, revertButtons: false, connect: "align", collapseIdentical: false });
        editors = [merge.editor(), merge.rightOriginal()];
      } else editors = [CodeMirror(el("editor"), { ...options, value: result.text })];
      el("editor-labels").classList.toggle("hidden", !replaceMode);
      for (const match of file.matches.slice(0, 2000)) {
        marks.push(editors[0].markText(editorPosition(result.text, match.line, match.column),
          editorPosition(result.text, match.end_line, match.end_column), { className: "sr-hit" }));
      }
      const match = file.matches.find(item => item.id === matchId) || file.matches[0];
      requestAnimationFrame(() => {
        if (version !== previewVersion) return;
        editors.forEach(editor => editor.refresh());
        if (match) {
          const pos = editorPosition(result.text, match.line, match.column);
          editors[0].setCursor(pos); editors[0].scrollIntoView(pos, 90);
        }
      });
      viewMessage(result.error || (replaceMode ? "Preview · chưa ghi file" : "Chỉ xem · Ctrl+C để copy"), Boolean(result.error));
    } catch (error) { if (version === previewVersion) viewMessage(error.message, true); }
  }
  function toggleReplace(force) {
    replaceMode = force ?? !replaceMode;
    el("replace-row").classList.toggle("hidden", !replaceMode);
    el("toggle-replace").textContent = replaceMode ? "⌄" : "›";
    el("toggle-replace").setAttribute("aria-expanded", String(replaceMode));
    page.classList.toggle("sr-replace-mode", replaceMode);
    invalidatePlan();
    if (active) openFile(active.fileId, active.matchId);
  }
  async function prepare(fileId = null, matchId = null) {
    if (!complete || writing || !files.length) return;
    if (!replaceMode) toggleReplace(true);
    invalidatePlan();
    const scope = { id: session, ...replacementOptions(), file_id: fileId, match_id: matchId };
    const version = generation;
    // Edits to any control while prepare is pending invalidate this response.
    const signature = JSON.stringify(replacementOptions());
    try {
      viewMessage("Đang kiểm tra toàn bộ file cần replace…");
      const result = await request("prepare", scope);
      if (version !== generation || signature !== JSON.stringify(replacementOptions())) return;
      if (!result.file_count) { viewMessage("Không có thay đổi byte nào để ghi."); return; }
      plan = { ...result, scope };
      el("review-label").textContent = `${result.count} matches · ${result.file_count} file sẽ thay đổi`;
      el("review-label").title = result.files.join("\n");
      el("review-bar").classList.remove("hidden"); controls();
      await openFile(fileId ?? files[0].id, matchId, scope);
    } catch (error) { viewMessage(error.message, true); }
  }
  async function applyPlan() {
    if (!plan || writing) return;
    const selected = plan;
    if (!await confirmAction("Replace các file đã xem trước?", `${selected.count} kết quả trong ${selected.file_count} file sẽ được thay thế. Encoding, BOM và byte ngoài vùng replace được giữ nguyên. Có thể Undo lần replace gần nhất trong phiên này.\n\n${selected.files.slice(0, 20).join("\n")}${selected.files.length > 20 ? "\n…" : ""}`)) return;
    if (plan !== selected) return;
    writing = true; controls();
    try {
      const result = await request("apply", { token: selected.token, confirmed: true });
      invalidatePlan(); el("undo").disabled = !result.can_undo;
      viewMessage(result.error ? `Đã ghi ${result.written.length} file; dừng vì: ${result.error}` : `Đã ghi ${result.written.length} file · giữ nguyên encoding`, Boolean(result.error));
      el("editor-labels").lastElementChild.textContent = result.error ? "Sau replace · kiểm tra trạng thái ghi" : "Sau replace · đã ghi";
      writing = false; controls(); await search(true);
    } catch (error) { viewMessage(error.message, true); }
    finally { writing = false; controls(); }
  }
  function navigate(direction) {
    const matches = files.flatMap(file => file.matches.map(match => ({ fileId: file.id, matchId: match.id })));
    if (!matches.length) return;
    const current = matches.findIndex(item => item.fileId === active?.fileId && item.matchId === active?.matchId);
    const next = matches[(current + direction + matches.length) % matches.length];
    openFile(next.fileId, next.matchId, plan?.scope);
  }
  function searchChanged(auto = true) {
    if (writing) return;
    invalidatePlan(); complete = false; previewVersion += 1; controls();
    clearTimeout(previewTimer);
    clearTimeout(searchTimer);
    if (running) stop();
    message("Tùy chọn đã đổi · nhấn Enter hoặc Search để tìm lại.");
    if (auto && el("root").value.trim() && el("query").value) searchTimer = setTimeout(() => search(), 450);
  }
  function replacementChanged() {
    invalidatePlan(); previewVersion += 1;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => { if (active) openFile(active.fileId, active.matchId); }, 250);
  }
  ["case", "word", "regex", "preserve"].forEach(id => el(id).addEventListener("click", () => {
    if (writing) return;
    el(id).setAttribute("aria-pressed", String(!pressed(id)));
    if (id === "preserve") replacementChanged(); else searchChanged();
  }));
  ["query", "include", "exclude"].forEach(id => el(id).addEventListener("input", () => searchChanged()));
  el("root").addEventListener("input", () => searchChanged(false));
  el("encoding").addEventListener("change", () => searchChanged());
  el("replacement").addEventListener("input", replacementChanged);
  ["query", "include", "exclude", "replacement"].forEach(id => el(id).addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); search(); }
  }));
  el("load").addEventListener("click", load);
  el("root").addEventListener("change", () => { searchChanged(false); });
  el("root").addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); load(); } });
  el("search").addEventListener("click", () => search());
  el("refresh").addEventListener("click", () => search());
  el("cancel").addEventListener("click", async () => { clearTimeout(searchTimer); await stop(); message("Đã dừng. Tìm lại trước khi replace."); });
  el("toggle-replace").addEventListener("click", () => toggleReplace());
  el("replace-all").addEventListener("click", () => prepare());
  el("apply-plan").addEventListener("click", applyPlan);
  el("discard-plan").addEventListener("click", invalidatePlan);
  el("prev").addEventListener("click", () => navigate(-1));
  el("next").addEventListener("click", () => navigate(1));
  el("clear").addEventListener("click", async () => { clearTimeout(searchTimer); await stop(); resetResults(); message("Đã xóa kết quả."); });
  el("collapse").addEventListener("click", () => {
    const groups = [...el("results").querySelectorAll("details")];
    const open = groups.every(group => !group.open);
    groups.forEach(group => { group.open = open; });
  });
  el("wrap").addEventListener("change", () => editors.forEach(editor => editor.setOption("lineWrapping", el("wrap").checked)));
  el("undo").addEventListener("click", async () => {
    if (writing || !await confirmAction("Undo replace?", "Khôi phục nguyên byte của lần replace gần nhất trong phiên này. Nếu file đã thay đổi bên ngoài, Undo sẽ bị chặn.")) return;
    writing = true; controls();
    try {
      const result = await request("undo", { confirmed: true });
      el("undo").disabled = !result.can_undo;
      viewMessage(result.error || `Đã hoàn tác ${result.written.length} file.`, Boolean(result.error));
      writing = false; await search();
    } catch (error) { viewMessage(error.message, true); }
    finally { writing = false; controls(); }
  });
  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && ["f", "h"].includes(event.key.toLowerCase())) {
      event.preventDefault(); showPage("search-replace", true);
      if (event.key.toLowerCase() === "h") toggleReplace(true);
      el("query").focus();
    }
    if (!page.classList.contains("active")) return;
    if (event.key === "F4") { event.preventDefault(); navigate(event.shiftKey ? -1 : 1); }
    if (event.altKey) {
      const id = { c: "case", w: "word", r: "regex", p: "preserve" }[event.key.toLowerCase()];
      if (id) { event.preventDefault(); el(id).click(); }
    }
    if (event.key === "Escape" && running) { event.preventDefault(); el("cancel").click(); }
  });
  const divider = page.querySelector(".sr-divider");
  const workbench = page.querySelector(".sr-workbench");
  function fitWorkbench() {
    if (!page.classList.contains("active")) return;
    const top = workbench.getBoundingClientRect().top + window.scrollY;
    workbench.style.height = `${Math.max(380, window.innerHeight - top - 14)}px`;
    editors.forEach(editor => editor.refresh());
  }
  function setWidth(width) { workbench.style.setProperty("--sr-sidebar-width", `${Math.max(260, Math.min(width, workbench.clientWidth * 0.6))}px`); editors.forEach(editor => editor.refresh()); }
  divider.addEventListener("pointerdown", event => { divider.setPointerCapture(event.pointerId); });
  divider.addEventListener("pointermove", event => { if (divider.hasPointerCapture(event.pointerId)) setWidth(event.clientX - workbench.getBoundingClientRect().left); });
  divider.addEventListener("pointerup", event => divider.releasePointerCapture(event.pointerId));
  divider.addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) { event.preventDefault(); setWidth(page.querySelector(".sr-sidebar").clientWidth + (event.key === "ArrowLeft" ? -20 : 20)); }
  });
  new ResizeObserver(fitWorkbench).observe(page);
  window.addEventListener("resize", fitWorkbench);
})();
