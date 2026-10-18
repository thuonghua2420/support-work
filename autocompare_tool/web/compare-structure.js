"use strict";

(() => {
  let saved = null;
  let busy = false;
  let saving = false;
  let request = 0;
  let activePath = ["output_dir"];
  const fields = [
    ["input_dir", "CSV nguồn", "input"], ["output_dir", "Output", "output"],
    ["before_htm_dir", "HTM / Before", "htm"], ["after_htm_dir", "HTM / After", "htm"],
    ["before_htc_dir", "HTC / Before", "htc"], ["after_htc_dir", "HTC / After", "htc"],
    ["compare_dir", "Compare", "compare"],
    ["htm_before_after_file", "HTM trước / sau", "file"],
    ["htc_before_after_file", "HTC trước / sau", "file"],
    ["after_htc_vs_htm_file", "HTC sau / HTM sau", "file"],
  ];
  const fieldInfo = Object.fromEntries(fields.map(([key, label, kind]) => [key, { label, kind }]));
  const dialog = () => $("#compare-structure-dialog");
  const controls = () => $$("[data-cs-key]", dialog());
  const draft = () => {
    const result = { folders: {}, workbooks: {} };
    controls().forEach(input => { result[input.dataset.csSection][input.dataset.csKey] = input.value; });
    return result;
  };
  const dirty = () => {
    if (!saved) return false;
    const values = draft();
    return ["folders", "workbooks"].some(section => Object.keys(saved[section]).some(key => values[section][key] !== saved[section][key]));
  };
  const icons = () => window.lucide?.createIcons({ root: dialog() });

  function row(key, children = "") {
    const { label, kind } = fieldInfo[key];
    const section = kind === "file" ? "workbooks" : "folders";
    return `<li class="cs-node cs-${kind}"><div class="cs-node-row">
      ${children ? `<button type="button" class="cs-collapse" aria-expanded="true" aria-label="Thu gọn ${label}"><i data-lucide="chevron-down" aria-hidden="true"></i></button>` : '<span class="cs-collapse-spacer"></span>'}
      <label class="cs-field"><span class="cs-node-label"><i data-lucide="${kind === "file" ? "file-spreadsheet" : "folder"}" aria-hidden="true"></i><span>${label}</span></span><input autocomplete="off" spellcheck="false" required maxlength="255" data-cs-key="${key}" data-cs-section="${section}" value="${escapeHtml(saved[section][key])}" aria-describedby="cs-error"></label>
      </div>${children ? `<ul class="cs-children">${children}</ul>` : ""}</li>`;
  }

  function render() {
    const files = fields.filter(([, , kind]) => kind === "file").map(([key]) => row(key)).join("");
    const outputs = ["before_htm_dir", "after_htm_dir", "before_htc_dir", "after_htc_dir"].map(key => row(key)).join("") + row("compare_dir", files);
    $("#compare-structure-tree").innerHTML = `<div class="cs-root"><i data-lucide="folder-open" aria-hidden="true"></i><strong>UT*</strong><span>Case</span></div><ul class="cs-children cs-root-children">${row("input_dir")}${row("output_dir", outputs)}</ul>`;
    icons();
    update();
  }

  function update() {
    const changed = dirty();
    $("#cs-edit-state").textContent = busy ? "Đang xử lý..." : changed ? "Có thay đổi chưa lưu" : "Đồng bộ với file config";
    $("#cs-edit-state").classList.toggle("is-dirty", Boolean(changed));
    $("#save-compare-structure").disabled = busy || !changed;
    $("#reload-compare-structure").disabled = busy;
    controls().forEach(input => { input.disabled = busy; });
    const values = draft();
    $("#cs-path-preview").textContent = ["UT*", ...activePath.map(key => values.folders[key] ?? values.workbooks[key] ?? "")].join(" / ");
  }

  function error(message = "") {
    $("#cs-error").textContent = message;
    $("#cs-error").classList.toggle("hidden", !message);
  }

  async function load() {
    const id = ++request;
    busy = true;
    error();
    update();
    try {
      const result = await api("/api/compare-structure");
      if (id !== request || !dialog().open) return;
      saved = result;
      updateCompareStructureHint(saved);
      render();
    } catch (failure) {
      if (id === request && dialog().open) error(failure.message);
    } finally {
      if (id === request) { busy = false; update(); }
    }
  }

  async function close() {
    if (saving) return;
    if (dirty() && !await confirmAction("Bỏ thay đổi cấu hình?", "Các thay đổi chưa lưu sẽ không được áp dụng.")) return;
    ++request;
    busy = false;
    dialog().close();
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("#open-compare-structure").addEventListener("click", () => {
      saved = null;
      $("#compare-structure-tree").replaceChildren();
      dialog().showModal();
      load();
    });
    ["#close-compare-structure", "#cancel-compare-structure"].forEach(selector => $(selector).addEventListener("click", close));
    dialog().addEventListener("cancel", event => { event.preventDefault(); close(); });
    $("#reload-compare-structure").addEventListener("click", async () => {
      if (dirty() && !await confirmAction("Tải lại cấu hình?", "Thay thế các thay đổi chưa lưu bằng cấu hình hiện có trong file.")) return;
      load();
    });
    $("#compare-structure-tree").addEventListener("input", event => {
      if (!event.target.matches("[data-cs-key]")) return;
      event.target.setCustomValidity("");
      error();
      update();
    });
    $("#compare-structure-tree").addEventListener("focusin", event => {
      const key = event.target.dataset.csKey;
      if (!key) return;
      activePath = [key];
      if (!["input_dir", "output_dir"].includes(key)) activePath.unshift("output_dir");
      if (event.target.dataset.csSection === "workbooks") activePath.splice(1, 0, "compare_dir");
      update();
    });
    $("#compare-structure-tree").addEventListener("click", event => {
      const button = event.target.closest(".cs-collapse");
      if (!button) return;
      const collapsed = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!collapsed));
      button.closest("li").querySelector(":scope > ul").hidden = collapsed;
    });
    $("#compare-structure-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (busy || !dirty()) return;
      busy = true;
      saving = true;
      error();
      const payload = { ...draft(), revision: saved.revision };
      update();
      try {
        saved = await api("/api/compare-structure/save", { method: "POST", body: payload });
        updateCompareStructureHint(saved);
        render();
        showToast("Đã lưu cấu trúc thư mục.", "success");
      } catch (failure) {
        error(failure.message);
      } finally {
        busy = false;
        saving = false;
        update();
      }
    });
  });
})();
