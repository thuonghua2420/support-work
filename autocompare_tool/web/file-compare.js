"use strict";

// Excel and PDF comparison share one flow: pick Old and New, compare, read the answer right here.
(() => {
  const KINDS = {
    excel: { action: "excel_compare", extension: "xlsx", pattern: /\.(xlsx|xlsm|xltx|xltm)$/i, accepted: ".xlsx, .xlsm, .xltx hoặc .xltm" },
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
    const output = el(kind, "output").value.trim();
    el(kind, "saveto").textContent = output ? `Kết quả sẽ lưu tại: ${output}` : "Kết quả sẽ tự đặt tên sau khi bạn chọn file.";
    el(kind, "saveto").title = output;
  }

  function refreshOutput(kind) {
    const output = el(kind, "output");
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
    const output = outputPath.toLowerCase();
    if (output === oldPath.toLowerCase() || output === newPath.toLowerCase()) return "Nơi lưu kết quả không được trùng với file nguồn.";
    return "";
  }

  function renderRunning(kind) {
    const panel = el(kind, "result");
    panel.className = "dc-result";
    panel.innerHTML = '<div class="dc-running"><span class="dc-spinner" aria-hidden="true"></span><div><strong>Đang so sánh…</strong><p>File lớn có thể mất vài phút. Tiến độ chi tiết xem ở nút LOG bên trái.</p></div><button class="secondary-button small" type="button" data-dc-cancel>Hủy</button></div>';
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
    const outputPath = el(kind, "output").value.trim() || suggestedOutput(kind);
    const problem = problemWith(kind, oldPath, newPath, outputPath);
    showError(kind, problem);
    if (problem) return;
    const payload = { old_path: oldPath, new_path: newPath, output_path: outputPath };
    if (kind === "excel") payload.pair_by_position = el(kind, "pair-position").checked;
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

  function placeholderValue(value) {
    return value === "" ? '<i class="dc-empty">(trống)</i>' : text(value);
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

  function renderSheet(sheet, open) {
    const [pairingLabel, pairingTone] = PAIRING[sheet.pairing] || ["", ""];
    const differences = Number(sheet.difference_count || 0);
    const summary = `<span class="dc-name">${text(sheetLabel(sheet))}</span>${pill(pairingLabel, pairingTone)}${differences ? pill(`${count(differences)} ô khác`, "bad") : pill("giống nhau", "ok")}`;
    if (!differences) return `<div class="dc-item"><div class="dc-item-head">${summary}</div></div>`;
    const rows = (sheet.samples || []).map((item) => `<tr><th scope="row">${text(item.cell)}</th><td>${placeholderValue(item.old)}</td><td>${placeholderValue(item.new)}</td></tr>`).join("");
    const more = sheet.samples_truncated ? `<p class="dc-note">Đang hiển thị ${count(sheet.samples.length)} / ${count(differences)} ô đầu tiên. Mở file kết quả để xem đầy đủ.</p>` : "";
    return `<details class="dc-item"${open ? " open" : ""}><summary class="dc-item-head">${summary}</summary><div class="dc-item-body"><table class="dc-table"><thead><tr><th>Ô</th><th>Old (cũ)</th><th>New (mới)</th></tr></thead><tbody>${rows}</tbody></table>${more}</div></details>`;
  }

  function renderExcel(result) {
    const sheets = result.sheets || [];
    const different = sheets.filter((sheet) => sheet.difference_count > 0).length;
    const byPosition = sheets.filter((sheet) => sheet.pairing === "position").length;
    const onlyOld = Number(result.missing_new_sheet_count || 0);
    const onlyNew = Number(result.missing_old_sheet_count || 0);
    let head;
    if (result.identical) {
      head = verdict("ok", "Hai file giống nhau", `Đã so sánh ${count(sheets.length)} sheet, không có ô nào khác nhau.`);
    } else {
      const title = result.difference_count ? `Có ${count(result.difference_count)} ô khác nhau` : "Hai file khác nhau về danh sách sheet";
      head = verdict("bad", title, `${count(different)} / ${count(sheets.length)} sheet có khác biệt.`);
    }
    const notes = [];
    if (byPosition) notes.push(`Có ${count(byPosition)} sheet khác tên được ghép theo thứ tự tab (xem nhãn “ghép theo thứ tự tab” bên dưới). Nếu đó không phải cùng một sheet, hãy bỏ chọn “Sheet khác tên thì ghép theo thứ tự tab” trong Tùy chọn nâng cao rồi so sánh lại.`);
    if (onlyOld || onlyNew) notes.push(`Sheet chỉ có ở một phía được so với sheet trống nên mọi ô có dữ liệu đều tính là khác.`);
    const order = [...sheets.filter((sheet) => sheet.difference_count > 0), ...sheets.filter((sheet) => !sheet.difference_count)];
    let opened = false;
    const list = order.map((sheet) => { const open = !opened && sheet.difference_count > 0; opened = opened || open; return renderSheet(sheet, open); }).join("");
    return `${head}${stats([["sheet đã so sánh", count(sheets.length)], ["ô khác nhau", count(result.difference_count), result.difference_count ? "bad" : "ok"], ["sheet chỉ có ở Old", count(onlyOld), onlyOld ? "bad" : ""], ["sheet chỉ có ở New", count(onlyNew), onlyNew ? "bad" : ""]])}${notes.map((note) => `<p class="dc-note warn">${text(note)}</p>`).join("")}<div class="dc-list">${list}</div>${openButtons([["Mở file kết quả", result.output_path, false, true], ["Hiện trong thư mục", result.output_path, true, false]])}<p class="dc-path">${text(result.output_path)}</p><p class="dc-note">Chỉ so sánh nội dung ô (giá trị và công thức). Định dạng, hình ảnh và biểu đồ không được so sánh. Trong file kết quả, mỗi sheet có bộ ba <code>_Old</code>, <code>_New</code>, <code>_compare</code>; ô giống nhau để trống, ô khác ghi <code>Old:… # New:…</code>.</p>`;
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
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
    const markManual = () => { if (output.value.trim()) output.dataset.manual = "1"; else delete output.dataset.manual; updateSaveTo(kind); };
    output.addEventListener("input", markManual);
    output.addEventListener("change", markManual);
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
