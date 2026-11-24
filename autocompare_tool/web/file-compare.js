"use strict";

// Excel and PDF comparison share one flow: pick Old and New, compare, read the answer right here.
(() => {
  const KINDS = {
    excel: { action: "excel_compare", pattern: /\.(xlsx|xlsm|xltx|xltm)$/i, accepted: ".xlsx, .xlsm, .xltx hoặc .xltm" },
    pdf: { action: "pdf_compare", extension: "pdf", pattern: /\.pdf$/i, accepted: ".pdf" },
  };
  const el = (kind, part) => document.getElementById(`${kind}-compare-${part}`);
  const text = (value) => escapeHtml(value ?? "");
  const count = (value) => Number(value || 0).toLocaleString("vi-VN");

  function splitPath(path) {
    const index = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
    const name = path.slice(index + 1);
    const dot = name.lastIndexOf(".");
    return { dir: index >= 0 ? path.slice(0, index) : "", stem: dot > 0 ? name.slice(0, dot) : name, separator: path.includes("/") && !path.includes("\\") ? "/" : "\\" };
  }

  function suggestedOutput(kind) {
    const source = el(kind, "new").value.trim() || el(kind, "old").value.trim();
    if (!source) return "";
    const { dir, stem, separator } = splitPath(source);
    return `${dir ? dir + separator : ""}${stem}_compare.${KINDS[kind].extension}`;
  }

  function updateSaveTo(kind) {
    const saveTo = el(kind, "saveto");
    if (!saveTo) return;
    const output = el(kind, "output")?.value.trim() || "";
    saveTo.textContent = output ? `Kết quả sẽ lưu tại: ${output}` : "Kết quả sẽ tự đặt tên sau khi bạn chọn file.";
    saveTo.title = output;
  }

  function refreshOutput(kind) {
    const output = el(kind, "output");
    if (!output) return;
    if (!output.dataset.manual) output.value = suggestedOutput(kind);
    updateSaveTo(kind);
  }

  function showError(kind, message) {
    const node = el(kind, "error");
    node.textContent = message;
    node.classList.toggle("hidden", !message);
  }

  function problemWith(kind, oldPath, newPath, outputPath) {
    const { pattern, accepted } = KINDS[kind];
    if (!oldPath) return "Vui lòng chọn file cũ (Old).";
    if (!newPath) return "Vui lòng chọn file mới (New).";
    if (!pattern.test(oldPath)) return `File cũ phải có định dạng ${accepted}.`;
    if (!pattern.test(newPath)) return `File mới phải có định dạng ${accepted}.`;
    if (oldPath.toLowerCase() === newPath.toLowerCase()) return "File cũ và file mới đang là cùng một file. Hãy chọn hai file khác nhau.";
    if (outputPath) {
      const output = outputPath.toLowerCase();
      if (output === oldPath.toLowerCase() || output === newPath.toLowerCase()) return "Nơi lưu kết quả không được trùng với file nguồn.";
    }
    return "";
  }

  function renderRunning(kind) {
    const panel = el(kind, "result");
    panel.className = "dc-result";
    const statusRole = kind === "excel" ? ' role="status"' : "";
    panel.innerHTML = `<div class="dc-running"><span class="dc-spinner" aria-hidden="true"></span><div${statusRole}><strong>Đang so sánh…</strong><p>File lớn có thể mất vài phút. Tiến độ chi tiết xem ở nút LOG bên trái.</p></div><button class="secondary-button small" type="button" data-dc-cancel>Hủy</button></div>`;
  }

  function clearResult(kind) {
    const panel = el(kind, "result");
    panel.className = "dc-result hidden";
    panel.innerHTML = "";
  }

  async function submit(kind, event) {
    event.preventDefault();
    const oldPath = el(kind, "old").value.trim();
    const newPath = el(kind, "new").value.trim();
    const outputPath = kind === "pdf" ? el(kind, "output").value.trim() || suggestedOutput(kind) : "";
    const problem = problemWith(kind, oldPath, newPath, outputPath);
    showError(kind, problem);
    if (problem) return;
    const payload = { old_path: oldPath, new_path: newPath };
    if (kind === "excel") payload.pair_by_position = el(kind, "pair-position").checked;
    else payload.output_path = outputPath;
    renderRunning(kind);
    await startAction(KINDS[kind].action, payload);
    const job = state.job;
    if (!(job && job.action === KINDS[kind].action && ["queued", "running"].includes(job.state))) clearResult(kind);
  }

  function pill(label, tone = "") {
    return `<span class="dc-pill ${tone}">${text(label)}</span>`;
  }

  function verdict(tone, title, detail) {
    const glyph = { ok: "✓", bad: "✕", warn: "!" }[tone] || "i";
    return `<div class="dc-verdict ${tone}"><span class="dc-glyph" aria-hidden="true">${glyph}</span><div><strong>${text(title)}</strong><p>${text(detail)}</p></div></div>`;
  }

  function stats(items) {
    return `<ul class="dc-stats">${items.map(([label, value, tone]) => `<li class="${tone || ""}"><b>${text(value)}</b><span>${text(label)}</span></li>`).join("")}</ul>`;
  }

  function openButtons(buttons) {
    return `<div class="dc-open">${buttons.map(([label, path, reveal, primary]) => `<button type="button" class="${primary ? "primary-button" : "secondary-button"} small" data-open-path="${text(path)}"${reveal ? ' data-reveal="1"' : ""}>${text(label)}</button>`).join("")}</div>`;
  }

  function sheetLabel(sheet) {
    if (sheet.pairing === "position") return `${sheet.old_name} ⇄ ${sheet.new_name}`;
    return sheet.new_name ?? sheet.old_name;
  }

  const PAIRING = {
    name: ["cùng tên", ""],
    position: ["ghép theo thứ tự tab", "warn"],
    old_only: ["chỉ có ở Old", "bad"],
    new_only: ["chỉ có ở New", "bad"],
  };

  const CHANGE_TYPES = {
    changed: ["Đổi giá trị", "warn"],
    added: ["Ô mới", "ok"],
    removed: ["Ô bị xóa", "bad"],
    kind: ["Đổi kiểu", "warn"],
    formula: ["Công thức", ""],
  };
  const PAGE_SIZE = 200;
  const VALUE_LIMIT = 300;
  const SPACE_MARKS = { " ": "·", "\t": "⇥", "\n": "↵", "\r": "␍" };

  function sheetDiffers(sheet) {
    return sheet.difference_count > 0 || sheet.pairing.endsWith("_only");
  }

  function renderSheetButton(sheet) {
    const [label, tone] = PAIRING[sheet.pairing];
    const differences = count(sheet.difference_count);
    return `<button type="button" class="dc-sheet-button" data-sheet="${text(sheet.index)}">
      <span class="dc-name">${text(sheetLabel(sheet))}</span>
      ${pill(label, tone)}${sheetDiffers(sheet) ? pill(`${differences} ô khác`, sheet.difference_count ? "bad" : "") : pill("giống nhau", "ok")}
    </button>`;
  }

  function renderValue(chars, start, end, showSpaces, expanded) {
    if (!chars.length) return '<i class="dc-empty">(trống)</i>';
    const from = expanded || chars.length <= VALUE_LIMIT ? 0 : Math.max(0, Math.min(start - 55, chars.length - VALUE_LIMIT));
    const to = expanded ? chars.length : Math.min(from + VALUE_LIMIT, chars.length);
    const markFrom = Math.min(to, Math.max(from, start));
    const markTo = Math.min(to, Math.max(markFrom, end));
    const part = (a, b) => {
      const value = chars.slice(a, b).join("");
      return text(showSpaces ? value.replace(/\s/gu, (space) => SPACE_MARKS[space] || "␣") : value);
    };
    const mark = markFrom < markTo ? `<mark>${part(markFrom, markTo)}</mark>` : "";
    return `${from ? "…" : ""}${part(from, markFrom)}${mark}${part(markTo, to)}${to < chars.length ? "…" : ""}`;
  }

  function valuePair(row) {
    const oldChars = Array.from(row.old);
    const newChars = Array.from(row.new);
    const shortest = Math.min(oldChars.length, newChars.length);
    let prefix = 0;
    let suffix = 0;
    while (prefix < shortest && oldChars[prefix] === newChars[prefix]) prefix += 1;
    while (suffix < shortest - prefix && oldChars[oldChars.length - 1 - suffix] === newChars[newChars.length - 1 - suffix]) suffix += 1;
    const showSpaces = row.old.replace(/\s/gu, "") === row.new.replace(/\s/gu, "")
      || /^\s+$/.test(row.old) || /^\s+$/.test(row.new);
    return { old: oldChars, new: newChars, prefix, suffix, showSpaces };
  }

  function valueContent(pair, side, expanded) {
    const chars = pair[side];
    return renderValue(chars, pair.prefix, chars.length - pair.suffix, pair.showSpaces, expanded);
  }

  function renderValueCell(pair, side) {
    const toggle = pair[side].length > VALUE_LIMIT
      ? `<button type="button" class="dc-link-button dc-expand" data-expand="${side}" aria-expanded="false">Xem đầy đủ</button>`
      : "";
    return `<td class="dc-value dc-value-${side}"><span class="dc-value-text">${valueContent(pair, side, false)}</span>${toggle}</td>`;
  }

  function renderDifference(row, index) {
    const [label, tone] = CHANGE_TYPES[row.change_type];
    const pair = valuePair(row);
    const header = row.header ? `<span class="dc-column-header" title="${text(row.header)}">${text(row.header)}</span>` : "";
    return `<tr data-row="${index}">
      <th scope="row"><button type="button" class="dc-link-button dc-coord" data-copy-cell="${text(row.coord)}" aria-label="Sao chép ô ${text(row.coord)}">${text(row.coord)}</button></th>
      <td>${count(row.row)}</td><td><span class="dc-column-label">${text(row.column)}${header}</span></td><td>${pill(label, tone)}</td>
      ${renderValueCell(pair, "old")}${renderValueCell(pair, "new")}
    </tr>`;
  }

  function renderChip(label, key, value, title = "") {
    return `<button type="button" class="dc-chip" data-${key}="${text(value)}" aria-pressed="false"${title ? ` title="${text(title)}"` : ""}>${text(label)}</button>`;
  }

  function renderColumnChip(item) {
    const header = Array.from(item.header);
    const shortHeader = header.length > 24 ? `${header.slice(0, 24).join("")}…` : item.header;
    const label = [item.column, shortHeader, count(item.count)].filter(Boolean).join(" · ");
    return renderChip(label, "column", item.column, item.header);
  }

  function renderExcel(result) {
    const sheets = result.sheets || [];
    const different = sheets.filter(sheetDiffers).length;
    const onlyOld = Number(result.missing_new_sheet_count || 0);
    const onlyNew = Number(result.missing_old_sheet_count || 0);
    const sheetCount = count(result.sheet_pair_count);
    const differences = count(result.difference_count);
    let head;
    if (result.identical) {
      head = verdict("ok", "Hai file giống nhau", "Nội dung các ô trùng khớp.");
    } else if (result.difference_count) {
      head = verdict("bad", `Có ${differences} ô khác nhau`, `${count(different)} / ${sheetCount} sheet có khác biệt.`);
    } else {
      head = verdict("warn", "Hai file khác nhau về danh sách sheet", `${count(onlyOld + onlyNew)} sheet chỉ có ở một file.`);
    }
    const tiles = stats([
      ["Sheet đã so sánh", sheetCount], ["Sheet có khác biệt", count(different), different ? "bad" : ""],
      ["Ô khác nhau", differences, result.difference_count ? "bad" : "ok"],
      ["Sheet chỉ có ở Old", count(onlyOld), onlyOld ? "bad" : ""],
      ["Sheet chỉ có ở New", count(onlyNew), onlyNew ? "bad" : ""],
    ]);
    const warning = result.details_truncated
      ? '<p class="dc-note warn">Chỉ xem được các ô khác đầu tiên trong giới hạn lưu chi tiết đã cấu hình. Tổng số ô khác vẫn chính xác.</p>'
      : "";
    return `${head}${tiles}${warning}
      <div class="dc-excel-body">
        <nav class="dc-sheet-nav" aria-label="Danh sách sheet">
          <label class="dc-check inline"><input type="checkbox" data-different-sheets><span>Chỉ hiện sheet có khác biệt</span></label>
          <div class="dc-sheet-list">${sheets.map(renderSheetButton).join("")}</div>
          <p class="dc-note hidden" data-no-sheets>Không có sheet có khác biệt.</p>
        </nav>
        <section class="dc-excel-detail" aria-label="Chi tiết sheet">
          <p class="dc-sheet-info" data-sheet-info></p>
          <p class="dc-note warn hidden" data-sheet-note></p>
          <div class="dc-toolbar" data-toolbar>
            <div class="dc-search-row">
              <input type="search" data-search aria-label="Tìm trong sai khác" placeholder="Tìm theo ô, giá trị hoặc tiêu đề cột" autocomplete="off">
              <button type="button" class="dc-link-button hidden" data-clear-filters>Xóa bộ lọc</button>
            </div>
            <div class="dc-chips" role="group" aria-label="Loại thay đổi" data-types></div>
            <div class="dc-column-filters" data-column-filters>
              <span>Cột khác nhiều nhất</span>
              <div class="dc-chips" role="group" aria-label="Cột khác nhiều nhất" data-columns></div>
            </div>
          </div>
          <div class="dc-table-wrap" tabindex="0" role="region" aria-label="Bảng ô khác nhau">
            <table class="dc-table">
              <thead><tr><th scope="col">Ô</th><th scope="col">Hàng</th><th scope="col">Cột</th><th scope="col">Loại</th><th scope="col">Giá trị cũ</th><th scope="col">Giá trị mới</th></tr></thead>
              <tbody></tbody>
            </table>
          </div>
          <div class="dc-table-footer">
            <span class="dc-table-status" role="status" aria-live="polite"></span>
            <div class="dc-pager" role="group" aria-label="Phân trang">
              <button type="button" data-page-step="first" aria-label="Trang đầu">«</button>
              <button type="button" data-page-step="prev" aria-label="Trang trước">‹</button>
              <span data-page-number></span>
              <button type="button" data-page-step="next" aria-label="Trang sau">›</button>
              <button type="button" data-page-step="last" aria-label="Trang cuối">»</button>
            </div>
          </div>
        </section>
      </div>
      <p class="dc-note">So sánh giá trị và công thức của từng ô theo vị trí 1:1. Chèn hoặc xóa hàng sẽ làm lệch các hàng bên dưới. Định dạng, hình ảnh, biểu đồ và bố cục ô gộp không được so sánh.</p>`;
  }

  function setupExcelDetails(panel, result) {
    const sheets = result.sheets || [];
    const get = (selector) => panel.querySelector(selector);
    const nav = get(".dc-sheet-nav");
    const detail = get(".dc-excel-detail");
    const toolbar = get("[data-toolbar]");
    const search = get("[data-search]");
    const clear = get("[data-clear-filters]");
    const typeChips = get("[data-types]");
    const columnChips = get("[data-columns]");
    const table = get(".dc-table-wrap");
    const body = get("tbody");
    const status = get(".dc-table-status");
    const pageLabel = get("[data-page-number]");
    const pager = get(".dc-pager");
    const changeTypes = new Set();
    let column = "";
    let sheet;
    let page = 1;
    let pages = 1;
    let rows = [];
    let request = 0;
    let timer;

    function syncFilters() {
      for (const chip of typeChips.children) chip.setAttribute("aria-pressed", changeTypes.has(chip.dataset.changeType));
      for (const chip of columnChips.children) chip.setAttribute("aria-pressed", column === chip.dataset.column);
      clear.classList.toggle("hidden", !(search.value || column || changeTypes.size));
    }

    function updatePager(loading) {
      pageLabel.textContent = `Trang ${count(page)} / ${count(pages)}`;
      for (const button of pager.querySelectorAll("button")) {
        const backward = ["first", "prev"].includes(button.dataset.pageStep);
        button.setAttribute("aria-disabled", loading || (backward ? page <= 1 : page >= pages));
      }
    }

    async function loadRows(id) {
      const offset = (page - 1) * PAGE_SIZE;
      try {
        const data = await api("/api/excel-compare/differences", {
          method: "POST",
          body: {
            report_id: result.report_id, sheet: sheet.index, offset, limit: PAGE_SIZE,
            search: search.value.trim(), change_types: [...changeTypes], column,
          },
        });
        if (id !== request || !body.isConnected) return;
        pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
        rows = data.rows;
        body.innerHTML = rows.map(renderDifference).join("");
        const range = rows.length
          ? `Hiển thị ${count(offset + 1)}–${count(offset + rows.length)} / ${count(data.total)}`
          : "Không có ô nào khớp bộ lọc";
        status.textContent = data.truncated ? `${range} · Chi tiết sheet đã chạm giới hạn lưu.` : range;
        updatePager(false);
      } catch (error) {
        if (id !== request || !body.isConnected) return;
        status.classList.add("dc-status-error");
        status.textContent = /hết hạn|báo cáo so sánh Excel không tồn tại/i.test(error.message)
          ? "Kết quả đã hết hạn, hãy so sánh lại."
          : error.message;
      }
      table.style.minHeight = "";
      table.setAttribute("aria-busy", "false");
    }

    function queueRows(delay = 0) {
      const id = ++request;
      clearTimeout(timer);
      if (!sheet) return;
      rows = [];
      table.style.minHeight = `${Math.max(260, table.offsetHeight)}px`;
      table.scrollTop = 0;
      body.replaceChildren();
      table.setAttribute("aria-busy", "true");
      status.classList.remove("dc-status-error");
      status.textContent = "Đang tải sai khác…";
      updatePager(true);
      if (delay) timer = setTimeout(() => { if (body.isConnected) loadRows(id); }, delay);
      else loadRows(id);
    }

    function resetFilters() {
      search.value = "";
      changeTypes.clear();
      column = "";
    }

    function filterRows(delay = 0) {
      page = pages = 1;
      syncFilters();
      queueRows(delay);
    }

    function selectSheet(next) {
      sheet = next;
      detail.classList.toggle("hidden", !sheet);
      for (const button of nav.querySelectorAll("[data-sheet]")) {
        if (Number(button.dataset.sheet) === sheet?.index) button.setAttribute("aria-current", "true");
        else button.removeAttribute("aria-current");
      }
      resetFilters();
      if (sheet) {
        const oldSize = sheet.old_name === null ? "—" : `${count(sheet.old_rows)} × ${count(sheet.old_columns)}`;
        const newSize = sheet.new_name === null ? "—" : `${count(sheet.new_rows)} × ${count(sheet.new_columns)}`;
        get("[data-sheet-info]").innerHTML = `<strong>${text(sheetLabel(sheet))}</strong> <span>Old ${oldSize} · New ${newSize} (hàng × cột)</span>`;
        const onlySide = { old_only: "Old", new_only: "New" }[sheet.pairing];
        const note = get("[data-sheet-note]");
        note.classList.toggle("hidden", !onlySide);
        note.textContent = onlySide ? `Sheet chỉ có ở ${onlySide} nên mọi ô có dữ liệu đều tính là khác.` : "";
        typeChips.innerHTML = Object.entries(CHANGE_TYPES).map(([type, [label]]) =>
          renderChip(`${label} · ${count(sheet.counts_by_type[type])}`, "change-type", type)
        ).join("");
        columnChips.innerHTML = sheet.top_columns.map(renderColumnChip).join("");
        get("[data-column-filters]").classList.toggle("hidden", !sheet.top_columns.length);
      }
      filterRows();
    }

    nav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-sheet]");
      if (!button) return;
      const next = sheets.find((item) => item.index === Number(button.dataset.sheet));
      if (next !== sheet) selectSheet(next);
    });
    nav.addEventListener("change", (event) => {
      const shown = event.target.checked ? sheets.filter(sheetDiffers) : sheets;
      const indexes = new Set(shown.map((item) => item.index));
      for (const button of nav.querySelectorAll("[data-sheet]")) button.classList.toggle("hidden", !indexes.has(Number(button.dataset.sheet)));
      get("[data-no-sheets]").classList.toggle("hidden", Boolean(shown.length));
      if (!shown.includes(sheet)) selectSheet(shown[0]);
    });

    search.addEventListener("input", () => filterRows(300));
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
    toolbar.addEventListener("click", (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      const type = button.dataset.changeType;
      const nextColumn = button.dataset.column;
      if (type) {
        if (!changeTypes.delete(type)) changeTypes.add(type);
      } else if (nextColumn) {
        column = column === nextColumn ? "" : nextColumn;
      } else {
        resetFilters();
        search.focus();
      }
      filterRows();
    });

    pager.addEventListener("click", (event) => {
      const button = event.target.closest("[data-page-step]");
      if (!button || button.getAttribute("aria-disabled") === "true") return;
      page = { first: 1, prev: page - 1, next: page + 1, last: pages }[button.dataset.pageStep];
      queueRows();
    });

    body.addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.dataset.copyCell) {
        try {
          await writeClipboardText(button.dataset.copyCell);
          if (button.isConnected && document.activeElement === document.body) button.focus({ preventScroll: true });
          showToast(`Đã sao chép ô ${button.dataset.copyCell}`, "success", 2000);
        } catch (error) {
          showToast(error.message, "error");
        }
      } else {
        const row = rows[Number(button.closest("tr").dataset.row)];
        const expanded = button.getAttribute("aria-expanded") === "false";
        button.previousElementSibling.innerHTML = valueContent(valuePair(row), button.dataset.expand, expanded);
        button.setAttribute("aria-expanded", expanded);
        button.textContent = expanded ? "Thu gọn" : "Xem đầy đủ";
      }
    });

    selectSheet(sheets.find(sheetDiffers) || sheets[0]);
  }

  function percent(ratio) {
    const value = Number(ratio || 0) * 100;
    if (!value) return "0%";
    return value < 0.01 ? "<0,01%" : `${value.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}%`;
  }

  function diffLines(lines) {
    return lines.map((line) => {
      const tone = line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@") ? "meta" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "";
      return `<span class="${tone}">${text(line) || " "}</span>`;
    }).join("");
  }

  function renderPage(page) {
    const pills = [];
    if (!page.old_present) pills.push(pill("trang chỉ có ở New", "bad"));
    else if (!page.new_present) pills.push(pill("trang chỉ có ở Old", "bad"));
    if (!page.text_identical) pills.push(pill("chữ khác", "bad"));
    if (!page.visual_identical) pills.push(pill(`hình ảnh khác · ${percent(page.difference_ratio)}`, "bad"));
    if (!page.fields_identical) pills.push(pill("form/chú thích khác", "bad"));
    if (page.status === "IDENTICAL") pills.push(pill("giống nhau", "ok"));
    const head = `<span class="dc-name">Trang ${count(page.page_number)}</span>${pills.join("")}`;
    if (page.status === "IDENTICAL") return `<div class="dc-item identical"><div class="dc-item-head">${head}</div></div>`;
    const detail = page.text_diff?.length
      ? `<pre class="dc-diff" aria-label="Khác biệt về chữ">${diffLines(page.text_diff)}</pre>`
      : '<p class="dc-note">Chữ trên trang giống nhau; khác biệt nằm ở hình ảnh hoặc bố cục. Xem ảnh Old / New / Diff của trang này trong báo cáo PDF.</p>';
    return `<details class="dc-item"><summary class="dc-item-head">${head}</summary><div class="dc-item-body">${detail}</div></details>`;
  }

  function checkTile(label, ok, detail) {
    return `<li class="${ok ? "ok" : "bad"}"><b>${ok ? "✓" : "✕"}</b><span>${text(label)}</span>${detail ? `<small>${text(detail)}</small>` : ""}</li>`;
  }

  function renderPdf(result) {
    const pages = result.pages || [];
    const sameCount = result.old_page_count === result.new_page_count;
    let head;
    if (result.binary_identical) head = verdict("ok", "Hai file giống hệt nhau", "Trùng khớp từng byte (SHA-256).");
    else if (result.identical) head = verdict("ok", "Nội dung giống nhau", `Chữ, hình ảnh và form/chú thích của ${count(result.compared_page_count)} trang đều trùng khớp. Hai file chỉ khác ở metadata hoặc cách lưu.`);
    else head = verdict("bad", "Hai file khác nhau", `${count(result.different_page_count)} / ${count(result.compared_page_count)} trang có khác biệt${sameCount ? "" : `; số trang khác nhau (Old ${count(result.old_page_count)}, New ${count(result.new_page_count)})`}.`);
    const tiles = `<ul class="dc-checks">${checkTile("Số trang", sameCount, `Old ${count(result.old_page_count)} · New ${count(result.new_page_count)}`)}${checkTile("Chữ", pages.every((page) => page.text_identical))}${checkTile("Hình ảnh", pages.every((page) => page.visual_identical), `${count(result.difference_region_count)} vùng khác`)}${checkTile("Form & chú thích", pages.every((page) => page.fields_identical))}</ul>`;
    const identicalPages = pages.filter((page) => page.status === "IDENTICAL");
    const differentPages = pages.filter((page) => page.status !== "IDENTICAL");
    const toggle = identicalPages.length && differentPages.length
      ? `<label class="dc-check inline"><input type="checkbox" data-show-identical><span>Hiện cả ${count(identicalPages.length)} trang giống nhau</span></label>`
      : "";
    const list = differentPages.length ? `<div class="dc-list" data-page-list>${differentPages.map(renderPage).join("")}</div>` : "";
    const hidden = toggle ? `<template data-identical-pages>${identicalPages.map(renderPage).join("")}</template>` : "";
    return `${head}${tiles}${toggle}${list}${hidden}${openButtons([["Mở báo cáo PDF", result.output_path, false, true], ["Hiện trong thư mục", result.output_path, true, false], ["Mở bằng chứng JSON", result.manifest_path, false, false]])}<p class="dc-path">${text(result.output_path)}</p><p class="dc-note">Báo cáo PDF có ảnh Old / New / vùng khác biệt cho từng trang khác nhau. Hai file chỉ được coi là giống nhau khi số trang, chữ, form/chú thích và từng pixel hình ảnh (200 DPI) đều trùng khớp.</p>`;
  }

  function kindOf(job) {
    return Object.keys(KINDS).find((kind) => KINDS[kind].action === job.action);
  }

  function show(job) {
    const kind = kindOf(job);
    if (!kind) return;
    const result = job.result || {};
    const panel = el(kind, "result");
    panel.className = `dc-result ${result.identical ? "match" : "different"}`;
    panel.innerHTML = kind === "excel" ? renderExcel(result) : renderPdf(result);
    if (kind === "excel") {
      setupExcelDetails(panel, result);
      panel.scrollIntoView({ block: "start" });
    } else {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function fail(job) {
    const kind = kindOf(job);
    if (!kind) return false;
    const cancelled = job.state === "cancelled";
    const panel = el(kind, "result");
    panel.className = "dc-result different";
    panel.innerHTML = `${verdict(cancelled ? "warn" : "bad", cancelled ? "Đã hủy so sánh" : "Không thể so sánh", job.error || (cancelled ? "Tác vụ đã được hủy." : "Tác vụ thất bại."))}${cancelled ? "" : '<p class="dc-note">Kiểm tra lại đường dẫn, đóng file đang mở trong Excel / trình xem PDF, rồi thử lại. Chi tiết xem ở nút LOG.</p>'}`;
    return true;
  }

  async function openResult(path, reveal) {
    try {
      await api("/api/open-result", { method: "POST", body: { path, reveal } });
    } catch (error) {
      showToast(error.message, "error", 7000);
    }
  }

  for (const kind of Object.keys(KINDS)) {
    const form = document.getElementById(`${kind}-compare-form`);
    if (!form) continue;
    for (const side of ["old", "new"]) {
      // "change" is what the file picker dispatches; "input" covers typing and pasting a path.
      for (const type of ["input", "change"]) el(kind, side).addEventListener(type, () => { showError(kind, ""); refreshOutput(kind); });
    }
    const output = el(kind, "output");
    if (output) {
      const markManual = () => { if (output.value.trim()) output.dataset.manual = "1"; else delete output.dataset.manual; updateSaveTo(kind); };
      output.addEventListener("input", markManual);
      output.addEventListener("change", markManual);
    }
    form.querySelector(".dc-swap").addEventListener("click", () => {
      const [oldInput, newInput] = [el(kind, "old"), el(kind, "new")];
      [oldInput.value, newInput.value] = [newInput.value, oldInput.value];
      refreshOutput(kind);
    });
    form.addEventListener("submit", (event) => submit(kind, event));
    form.addEventListener("click", (event) => {
      const open = event.target.closest("[data-open-path]");
      if (open) openResult(open.dataset.openPath, open.dataset.reveal === "1");
      else if (event.target.closest("[data-dc-cancel]")) cancelCurrentJob();
    });
    form.addEventListener("change", (event) => {
      if (!event.target.matches("[data-show-identical]")) return;
      const list = form.querySelector("[data-page-list]");
      const identical = form.querySelector("template[data-identical-pages]");
      list.querySelectorAll(".identical").forEach((node) => node.remove());
      if (event.target.checked) list.insertAdjacentHTML("beforeend", identical.innerHTML);
    });
    updateSaveTo(kind);
  }

  window.fileCompare = { show, fail };
})();
