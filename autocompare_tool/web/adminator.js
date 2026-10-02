"use strict";

function prepareAdminatorLayout() {
  const navigation = {
    compare: ["git-compare-arrows", "Compare CSV"],
    "folder-compare": ["folders", "Compare theo folder"],
    "excel-compare": ["file-diff", "Compare Excel"],
    "pdf-compare": ["files", "Compare PDF"],
    "image-compare": ["images", "Compare Image"],
    "file-tools": ["folder-cog", "File / Folder"],
    "copy-ut": ["copy", "Sao chép UT"],
    "excel-format": ["file-spreadsheet", "Format Excel"],
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
  prepareCompactWorkspaces();
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
      if (id === "compare-preview-card") placeComparePageToolbar(panel, expanded);
      button.setAttribute("aria-pressed", String(expanded));
      button.title = expanded ? "Thu nhỏ kết quả" : "Phóng to kết quả";
      button.setAttribute("aria-label", button.title);
      button.innerHTML = `<i data-lucide="${expanded ? "minimize-2" : "maximize-2"}"></i>`;
      window.lucide?.createIcons();
    });
    actions.append(button);
  }
  prepareComparePageToolbar();
  prepareWorkspaceDesign();
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") document.querySelector(".panel-expanded .expand-panel")?.click();
  });
  window.lucide?.createIcons();
}

function prepareWorkspaceDesign() {
  const groups = [["file-tools", "Công cụ workbook"], ["database", "Cơ sở dữ liệu"]];
  for (const [page, label] of groups) {
    const item = document.querySelector(`.nav-item[data-page="${page}"]`);
    const heading = document.createElement("span");
    heading.className = "nav-label nav-group-label";
    heading.textContent = label;
    item.before(heading);
  }

  const forms = [
    ["folder-compare-form", "folders", "So sánh hai thư mục", "Chọn dữ liệu gốc và dữ liệu cần đối chiếu, sau đó chọn cách lưu kết quả."],
    ["excel-compare-form", "file-diff", "Đối chiếu workbook", "So sánh giá trị từng ô và xem các thay đổi trong workbook kết quả."],
    ["pdf-compare-form", "files", "Đối chiếu tài liệu PDF", "Kiểm tra nội dung và hình ảnh, kèm báo cáo các điểm khác biệt."],
    ["copy-ut-form", "copy", "Sao chép dữ liệu UT", "Chọn thư mục nguồn và thư mục đích theo cấu trúc test của bạn."],
  ];
  for (const [id, icon, title, description] of forms) {
    const form = document.getElementById(id);
    if (!form) continue;
    const header = document.createElement("div");
    header.className = "workflow-heading";
    header.innerHTML = `<span class="workflow-icon" aria-hidden="true"><i data-lucide="${icon}"></i></span><div><h3>${title}</h3><p>${description}</p></div>`;
    form.prepend(header);
  }

  const sourceFields = [
    ["folder-left", "Dữ liệu gốc", "OLD"], ["folder-right", "Dữ liệu đối chiếu", "NEW"],
    ["excel-compare-old", "Workbook gốc", "OLD"], ["excel-compare-new", "Workbook đối chiếu", "NEW"],
    ["pdf-compare-old", "Tài liệu gốc", "OLD"], ["pdf-compare-new", "Tài liệu đối chiếu", "NEW"],
  ];
  for (const [id, title, side] of sourceFields) {
    const input = document.getElementById(id);
    const field = input?.closest(".field");
    const label = field?.querySelector(":scope > span:first-child");
    if (!label) continue;
    field.classList.add("comparison-source", side === "OLD" ? "source-old" : "source-new");
    label.innerHTML = `<span class="source-badge">${side}</span>${title}`;
  }

  const hints = {
    "compare-root": "Chọn thư mục chứa các case UT…",
    "folder-left": "Đường dẫn thư mục gốc…", "folder-right": "Đường dẫn thư mục đối chiếu…",
    "excel-format-root": "Chọn thư mục chứa workbook cần định dạng…",
    "copy-source": "Thư mục chứa dữ liệu nguồn…", "copy-target": "Thư mục UT đích…",
  };
  for (const [id, placeholder] of Object.entries(hints)) {
    const input = document.getElementById(id);
    if (input) input.placeholder = placeholder;
  }
}

function prepareComparePageToolbar() {
  const page = document.getElementById("page-compare");
  const intro = page?.querySelector(".page-intro");
  const panel = document.getElementById("compare-preview-card");
  const heading = panel?.querySelector(":scope > .card-heading");
  const bulk = document.getElementById("compare-bulk-tools");
  if (!intro || !panel || !heading || !bulk || document.getElementById("compare-page-toolbar")) return;
  const toolbar = document.createElement("div");
  toolbar.id = "compare-page-toolbar";
  toolbar.className = "compare-page-toolbar hidden";
  toolbar.setAttribute("aria-label", "Thao tác workbook compare");
  toolbar.append(heading, bulk);
  intro.append(toolbar);
}

function placeComparePageToolbar(panel, expanded) {
  const toolbar = document.getElementById("compare-page-toolbar");
  const intro = document.querySelector("#page-compare > .page-intro");
  if (!toolbar || !intro) return;
  if (expanded) {
    panel.prepend(toolbar);
    toolbar.classList.remove("hidden");
  } else {
    intro.append(toolbar);
  }
}

function prepareCompactWorkspaces() {
  const csvForm = document.getElementById("db-csv-form");

  document.querySelectorAll("#page-database .import-mode-card, #page-database .switch-row").forEach((label) => {
    const description = label.querySelector("small");
    if (description) label.title = description.textContent;
  });
  const loader = document.querySelector(".sql-excel-loader");
  const details = document.createElement("details");
  details.className = "sql-excel-details";
  details.innerHTML = '<summary><i data-lucide="file-spreadsheet" aria-hidden="true"></i>SQL từ Excel</summary>';
  loader.before(details);
  details.append(loader);

  const icons = {
    "copy-current-sql": ["copy", "Copy SQL", false],
    "sql-format": ["align-left", "Format SQL", false],
    "sql-analyze": ["scan-search", "Phân tích", false],
    "sql-run-current": ["play", "Chạy hiện tại", false],
    "sql-run-all": ["list-start", "Chạy toàn bộ", false],
    "db-scan-csv": ["list-checks", "Quét file CSV", false],
    "db-copy-all-tables": ["copy", "Copy all table", false],
    "db-import": ["upload", "Import All", false],
    "db-import-selected": ["upload-cloud", "Import Single", false],
    "db-export": ["download", "Export CSV", false],
  };
  for (const [id, [icon, label, iconOnly]] of Object.entries(icons)) {
    const button = document.getElementById(id);
    if (!button) continue;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.classList.add("compact-tool-button");
    if (iconOnly) button.classList.add("icon-button");
    button.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i>${iconOnly ? "" : `<span>${label}</span>`}`;
  }
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
  ];
  document.getElementById("fixme-expand-card")?.classList.add("hidden");
  const activate = (target) => {
    tabs.querySelectorAll("button").forEach((button) => {
      const active = button === target;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      document.getElementById(button.getAttribute("aria-controls")).classList.toggle("active", active);
    });
    const compareToolbar = document.getElementById("compare-page-toolbar");
    const comparePanel = document.getElementById("compare-preview-card");
    compareToolbar?.classList.toggle(
      "hidden",
      target.id !== "tab-compare-preview-card" || comparePanel?.classList.contains("hidden"),
    );
    if (target.id === "tab-compare-preview-card" && !comparePanel?.classList.contains("hidden")) {
      window.requestAnimationFrame(expandComparePanelFromTab);
    }
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

function expandComparePanelFromTab() {
  const panel = document.getElementById("compare-preview-card");
  if (!panel || panel.classList.contains("hidden") || panel.classList.contains("panel-expanded")) return;
  const button = document.querySelector("#compare-page-toolbar .expand-panel")
    || panel.querySelector(".expand-panel");
  button?.click();
}
