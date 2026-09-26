"use strict";

(() => {
  const page = document.getElementById("page-image-compare");
  const el = (id) => document.getElementById(`ic-${id}`);
  const sources = { old: null, new: null }, revisions = { old: 0, new: 0 };
  let selected = "old", busy = false, pendingLoads = 0, result = null, view = "diff", region = -1, scale = 1;
  const escape = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function message(text, error = false) {
    el("message").textContent = text;
    el("message").classList.toggle("ic-error", error);
    if (error) showToast(text, "error");
  }
  function select(side) {
    selected = side;
    page.querySelectorAll("[data-image-side]").forEach((node) => node.classList.toggle("ic-selected", node.dataset.imageSide === side));
  }
  function controls() {
    page.querySelectorAll(".ic-input button, .ic-input input, #ic-swap").forEach((node) => { node.disabled = busy; });
    el("compare").disabled = busy || pendingLoads > 0 || !sources.old || !sources.new;
    el("compare").textContent = busy ? "Đang so sánh…" : "Compare Image";
    page.setAttribute("aria-busy", String(busy));
  }
  function invalidate() {
    result = null; el("results").classList.add("hidden");
    for (const id of ["view-a", "view-b", "view-c"]) el(id).removeAttribute("src");
    message("Ảnh đã thay đổi. Nhấn Compare Image để xem kết quả mới.");
  }
  function preview(side) {
    const source = sources[side], drop = el(`drop-${side}`), image = drop.querySelector("img");
    image.classList.toggle("hidden", !source);
    drop.querySelector("span").classList.toggle("hidden", Boolean(source));
    if (source) image.src = source.data_url; else image.removeAttribute("src");
    el(`info-${side}`).textContent = source ? `${source.name} · ${(source.bytes / 1024).toFixed(1)} KB` : "Chưa có ảnh";
    controls();
  }
  async function load(side, file) {
    if (busy || !file) return;
    const revision = ++revisions[side]; pendingLoads++; controls();
    try {
      if (file.size > 12 * 1024 * 1024) throw new Error("Tối đa 12 MB mỗi ảnh.");
      if (!file.size) throw new Error("Ảnh trống, vui lòng chọn lại.");
      if (!(/^image\/(png|jpeg|webp|bmp|x-ms-bmp)$/i.test(file.type) || /\.(png|jpe?g|webp|bmp)$/i.test(file.name || ""))) throw new Error("Chỉ hỗ trợ ảnh tĩnh PNG, JPEG, WebP và BMP.");
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Không đọc được file ảnh.")); reader.readAsDataURL(file);
      });
      // Actual format is validated by Pillow; Explorer can supply an empty MIME.
      const dataUrl = data.startsWith("data:image/") ? data : data.replace(/^data:[^;,]*;base64,/, "data:image/png;base64,");
      if (revision !== revisions[side]) return;
      sources[side] = { name: file.name || `Clipboard-${side}.png`, data_url: dataUrl, bytes: file.size };
      invalidate(); preview(side); select(side);
    } catch (error) { message(error.message, true); }
    finally { pendingLoads--; controls(); }
  }
  async function paste(side) {
    if (busy) return;
    select(side); el(`drop-${side}`).focus();
    if (!navigator.clipboard?.read) { message("Nhấn Ctrl+V để dán ảnh vào vùng đã chọn."); return; }
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const type = item.types.find((type) => /^image\//.test(type));
        if (type) { await load(side, await item.getType(type)); return; }
      }
      message("Clipboard chưa có ảnh. Hãy copy ảnh hoặc chụp màn hình rồi dán lại.", true);
    } catch { message("Chưa đọc được clipboard. Nhấn Ctrl+V để dán vào vùng đã chọn."); }
  }
  for (const side of ["old", "new"]) {
    const input = el(`file-${side}`), drop = el(`drop-${side}`);
    page.querySelector(`[data-image-import="${side}"]`).addEventListener("click", () => { select(side); input.click(); });
    page.querySelector(`[data-image-paste="${side}"]`).addEventListener("click", () => paste(side));
    page.querySelector(`[data-image-clear="${side}"]`).addEventListener("click", () => { revisions[side]++; sources[side] = null; input.value = ""; invalidate(); preview(side); });
    input.addEventListener("change", () => { const file = input.files[0]; input.value = ""; load(side, file); });
    drop.addEventListener("click", () => { select(side); drop.focus(); });
    drop.addEventListener("focus", () => select(side));
    drop.addEventListener("keydown", (event) => { if (!busy && ["Enter", " "].includes(event.key)) { event.preventDefault(); input.click(); } });
    drop.addEventListener("dragover", (event) => { event.preventDefault(); if (!busy) drop.classList.add("ic-drag"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("ic-drag"));
    drop.addEventListener("drop", (event) => {
      event.preventDefault(); drop.classList.remove("ic-drag"); if (busy) return;
      if (event.dataTransfer.files.length !== 1) { message("Mỗi vùng nhận một ảnh. Kéo từng ảnh vào Old và New.", true); return; }
      load(side, event.dataTransfer.files[0]);
    });
  }
  document.addEventListener("paste", (event) => {
    if (!page.classList.contains("active") || busy) return;
    const item = [...(event.clipboardData?.items || [])].find((item) => item.type.startsWith("image/"));
    if (item) { event.preventDefault(); load(selected, item.getAsFile()); }
  });
  el("swap").addEventListener("click", () => {
    revisions.old++; revisions.new++; [sources.old, sources.new] = [sources.new, sources.old];
    invalidate(); preview("old"); preview("new");
  });
  el("compare").addEventListener("click", async () => {
    if (busy || pendingLoads || !sources.old || !sources.new) return;
    busy = true; controls(); el("results").classList.add("hidden");
    message("Đang kiểm tra kích thước, màu và từng pixel của hai ảnh…");
    try {
      result = await api("/api/image-compare", { method: "POST", body: { old: sources.old, new: sources.new } });
      region = result.regions.length ? 0 : -1; el("zoom").value = "fit"; el("wipe").value = "50";
      el("results").classList.remove("hidden"); renderSummary(); setView("diff");
      message("So sánh hoàn tất. Có thể xem từng vùng hoặc tải báo cáo ở cuối kết quả.");
      el("results").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) { result = null; message(error.message, true); }
    finally { busy = false; controls(); }
  });
  function summaryText(r) {
    const percent = r.changed_pixels ? Math.max(r.difference_percent, 0.000001).toFixed(6) : "0";
    return `${r.changed_pixels.toLocaleString("vi-VN")} / ${r.total_pixels.toLocaleString("vi-VN")} pixel khác (${percent}%) · ${r.regions.length} vùng. Old: ${r.old.width} × ${r.old.height} px · New: ${r.new.width} × ${r.new.height} px.`;
  }
  function manifest() { const { previews, ...rest } = result; return rest; }
  function renderSummary() {
    const evidence = result.binary_identical ? "File giống hoàn toàn từng byte (SHA-256 trùng khớp)." : result.identical ? "Pixel và thông tin màu trùng khớp. Hai file có cách lưu hoặc metadata khác nhau." : "So sánh chính xác: chỉ một pixel hoặc kích thước khác cũng được báo khác.";
    el("verdict").classList.toggle("ic-match", result.identical);
    el("verdict").innerHTML = `<strong>${result.identical ? "Hai ảnh giống nhau" : "Hai ảnh khác nhau"}</strong><p>${escape(summaryText(result))}</p><p>${escape(evidence)}</p>${!result.color_metadata_identical ? "<p>Thông tin màu ICC/gamma khác nhau. Màu hiển thị có thể khác dù giá trị pixel bằng nhau; ảnh Diff chỉ đánh dấu khác biệt pixel.</p>" : ""}`;
    el("evidence").textContent = JSON.stringify(manifest(), null, 2);
  }
  function setView(mode) {
    view = mode;
    page.querySelectorAll("[data-image-view]").forEach((button) => { const active = button.dataset.imageView === view; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
    el("view-a").src = result.previews[view === "diff" ? "diff" : "old"];
    el("view-b").src = result.previews.new; el("view-c").src = result.previews.new;
    el("view-b").classList.toggle("hidden", view !== "wipe"); el("pane-b").classList.toggle("hidden", view !== "split");
    el("wipe-control").classList.toggle("hidden", view !== "wipe");
    el("label-a").textContent = view === "diff" ? "Diff · vùng đỏ là sai khác" : view === "wipe" ? "Old bên trái · New bên phải" : "Old";
    updateWipe(); layout();
  }
  function updateWipe() { el("view-b").style.clipPath = `inset(0 0 0 ${el("wipe").value}%)`; }
  function layout() {
    if (!result || el("results").classList.contains("hidden") || !page.classList.contains("active")) return;
    const count = view === "split" ? 2 : 1, available = Math.max(60, (el("viewport").clientWidth - 24 - (count-1)*16) / count);
    const maxHeight = Math.max(270, Math.min(window.innerHeight * 0.65, 680));
    scale = el("zoom").value === "fit" ? Math.min(1, available / result.width, (maxHeight - 56) / result.height) : Number(el("zoom").value);
    el("viewport").style.height = `${Math.min(maxHeight, Math.max(270, result.height * scale + 56))}px`;
    page.querySelectorAll(".ic-image-wrap").forEach((node) => { node.style.width = `${result.width*scale}px`; node.style.height = `${result.height*scale}px`; });
    focusRegion(false);
  }
  function focusRegion(scroll) {
    const box = result?.regions[region];
    el("focus").classList.toggle("hidden", !box); el("prev").disabled = el("next").disabled = !box;
    el("region").textContent = box ? `${region+1} / ${result.regions.length} vùng` : "Không có vùng";
    if (!box) return;
    const [x0, y0, x1, y1] = box;
    Object.assign(el("focus").style, { left: `${x0*scale}px`, top: `${y0*scale}px`, width: `${Math.max(4,(x1-x0)*scale)}px`, height: `${Math.max(4,(y1-y0)*scale)}px` });
    el("region").title = `x=${x0}, y=${y0}, rộng=${x1-x0}, cao=${y1-y0} pixel (tọa độ từ 0)`;
    if (scroll) el("viewport").scrollTo({ left: (x0+x1)*scale/2-el("viewport").clientWidth/2, top: (y0+y1)*scale/2+36-el("viewport").clientHeight/2, behavior: "smooth" });
  }
  function moveRegion(delta) {
    if (!result?.regions.length) return;
    region = (region+delta+result.regions.length)%result.regions.length; el("zoom").value = "1"; layout(); focusRegion(true);
  }
  page.querySelectorAll("[data-image-view]").forEach((button) => button.addEventListener("click", () => { if (result) setView(button.dataset.imageView); }));
  el("prev").addEventListener("click", () => moveRegion(-1)); el("next").addEventListener("click", () => moveRegion(1));
  el("zoom").addEventListener("change", () => { layout(); focusRegion(true); }); el("wipe").addEventListener("input", updateWipe);
  new ResizeObserver(() => layout()).observe(el("viewport"));
  function download(blob, name) {
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = name; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
  el("export-json").addEventListener("click", () => { if (result) download(new Blob([JSON.stringify(manifest(), null, 2)], { type: "application/json" }), "Compare_Image.json"); });
  el("export-png").addEventListener("click", () => {
    if (!result) return;
    const raw = atob(result.previews.diff.split(",")[1]);
    download(new Blob([Uint8Array.from(raw, (c) => c.charCodeAt(0))], { type: "image/png" }), "Compare_Image_Diff.png");
  });
  el("export-html").addEventListener("click", () => {
    if (!result) return;
    const panels = [["Old", "old"], ["New", "new"], ["Diff · pixel khác được tô đỏ", "diff"]].map(([label, key]) => `<section><h2>${label}</h2><img src="${result.previews[key]}" alt="${label}"></section>`).join("");
    const report = `<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Compare Image</title><style>body{font:15px system-ui,sans-serif;color:#183b5b;margin:32px}h1{color:${result.identical ? "#197447" : "#b4232d"}}.panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.panels section:last-child{grid-column:1/-1}img{max-width:100%;background:repeating-conic-gradient(#e2e5e9 0% 25%,white 0% 50%) 50% / 16px 16px;border:1px solid #ccd9e6}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7fa;padding:16px}h2{font-size:16px}@media(max-width:700px){.panels{grid-template-columns:1fr}}@media print{section{break-inside:avoid}}</style><h1>${result.identical ? "Hai ảnh giống nhau" : "Hai ảnh khác nhau"} · ${result.verdict}</h1><p>${escape(summaryText(result))}</p><p>Old: ${escape(result.old.name)}<br>New: ${escape(result.new.name)}</p><p>So sánh chính xác RGBA 8-bit sau khi áp dụng hướng EXIF, bao gồm độ trong suốt và vùng thiếu. Không resize hoặc dùng ngưỡng bỏ qua. Thông tin màu ICC/gamma được kiểm tra riêng; ảnh xem là pixel RGBA đã giải mã.</p>${!result.color_metadata_identical ? "<p>Thông tin màu khác nhau; màu hiển thị có thể khác dù pixel giống nhau.</p>" : ""}<div class="panels">${panels}</div><h2>Bằng chứng và tọa độ toàn bộ vùng sai khác</h2><pre>${escape(JSON.stringify(manifest(), null, 2))}</pre></html>`;
    download(new Blob([report], { type: "text/html;charset=utf-8" }), "Compare_Image_Report.html");
  });
  select("old"); controls();
})();
