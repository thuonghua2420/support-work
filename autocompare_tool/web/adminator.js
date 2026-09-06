"use strict";

function prepareAdminatorLayout() {
  const navigation = {
    compare: ["git-compare-arrows", "Compare CSV"],
    "folder-compare": ["folders", "Compare theo folder"],
    "file-tools": ["folder-cog", "File / Folder"],
    "copy-ut": ["copy", "Sao chép UT"],
    "excel-format": ["file-spreadsheet", "Format EVD / Excel"],
    database: ["database", "Database"],
  };
  for (const [key, [icon, label]] of Object.entries(navigation)) {
    const button = document.querySelector(`.nav-item[data-page="${key}"]`);
    button.title = label;
    button.setAttribute("aria-label", label);
    button.querySelector("strong").textContent = label;
    button.querySelector(".nav-icon").innerHTML = `<i data-lucide="${icon}"></i>`;
  }
  document.querySelectorAll(".browse-button").forEach((button) => {
    const label = button.textContent.trim();
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML = '<i data-lucide="folder-open"></i>';
  });
  document.querySelectorAll('.primary-button > b').forEach((node) => node.remove());
  const backdrop = document.createElement("button");
  backdrop.className = "menu-backdrop";
  backdrop.id = "menu-backdrop";
  backdrop.type = "button";
  backdrop.setAttribute("aria-label", "Đóng menu");
  document.body.append(backdrop);
  prepareCompareWorkbench();
  prepareExcelWorkbench();
  for (const id of ["compare-preview-card", "fixme-expand-card"]) {
    const panel = document.getElementById(id);
    const actions = panel.querySelector(".card-heading .inline-actions");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button expand-panel";
    button.title = "Phóng to kết quả";
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = '<i data-lucide="maximize-2"></i>';
    button.addEventListener("click", () => {
      const expanded = panel.classList.toggle("panel-expanded");
      button.setAttribute("aria-pressed", String(expanded));
      button.title = expanded ? "Thu nhỏ kết quả" : "Phóng to kết quả";
      button.setAttribute("aria-label", button.title);
      button.innerHTML = `<i data-lucide="${expanded ? "minimize-2" : "maximize-2"}"></i>`;
      window.lucide?.createIcons();
    });
    actions.append(button);
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelector(".panel-expanded .expand-panel")?.click();
  });
  window.lucide?.createIcons();
}

function prepareExcelWorkbench() {
  const form = document.getElementById("excel-format-form");
  const nodes = [...form.children];
  const grid = document.createElement("div");
  grid.className = "excel-workbench";
  let section;
  let sectionIndex = 0;
  for (const node of nodes) {
    if (node.classList.contains("form-actions")) continue;
    if (node.classList.contains("divider")) {
      section = null;
      node.remove();
      continue;
    }
    if (!section) {
      section = document.createElement("section");
      section.className = `excel-section excel-section-${sectionIndex++}`;
      grid.append(section);
    }
    section.append(node);
  }
  form.prepend(grid);
}

function prepareCompareWorkbench() {
  const page = document.getElementById("page-compare");
  const tabs = document.createElement("div");
  tabs.className = "workbench-tabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "So sánh CSV");
  page.querySelector(".page-intro").after(tabs);
  const sections = [
    ["compare-form", "Cấu hình"],
    ["compare-preview-card", "Workbook"],
    ["fixme-expand-card", "Danh sách FIXME"],
  ];
  const activate = (target) => {
    tabs.querySelectorAll("button").forEach((button) => {
      const active = button === target;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      document.getElementById(button.getAttribute("aria-controls")).classList.toggle("active", active);
    });
  };
  sections.forEach(([id, label], index) => {
    const content = document.getElementById(id);
    const panel = document.createElement("div");
    panel.id = `workbench-${id}`;
    panel.className = `workbench-panel${index === 0 ? " active" : ""}`;
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", `tab-${id}`);
    const tab = document.createElement("button");
    tab.id = `tab-${id}`;
    tab.className = `workbench-tab${index === 0 ? " active" : ""}`;
    tab.type = "button";
    tab.textContent = label;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panel.id);
    tab.setAttribute("aria-selected", String(index === 0));
    tab.tabIndex = index === 0 ? 0 : -1;
    tab.addEventListener("click", () => activate(tab));
    tabs.append(tab);
    panel.append(content);
    page.append(panel);
    if (id === "compare-preview-card") {
      const empty = document.createElement("div");
      empty.className = "workbench-empty";
      empty.innerHTML = '<i data-lucide="table-2"></i><strong>Chưa có workbook</strong>';
      panel.append(empty);
      const updateEmpty = () => empty.classList.toggle("hidden", !content.classList.contains("hidden"));
      new MutationObserver(updateEmpty).observe(content, { attributes: true, attributeFilter: ["class"] });
      updateEmpty();
    }
    if (id === "fixme-expand-card") {
      content.classList.remove("collapsed");
      content.querySelector("h3").textContent = "Danh sách FIXME";
      content.querySelector("#toggle-fixme-expand").textContent = "Thu gọn";
    }
  });
  tabs.addEventListener("keydown", (event) => {
    const buttons = [...tabs.querySelectorAll("button")];
    const index = buttons.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
    activate(buttons[next]);
    buttons[next].focus();
  });
}
