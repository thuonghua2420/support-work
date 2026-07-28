from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .app_config import AppConfig, load_app_config
from .db_roundtrip import (
    DatabaseSettings,
    get_available_sql_drivers,
    process_sqlserver_roundtrip,
    test_sqlserver_connection,
)
from .copy_ut import run_copy_ut_files
from .excel_writer import WorkbookFixmeEntry
from .folder_compare import compare_csv_folders
from .fixme_notes import FixmeNote, FixmeNoteStore
from .fixme_replacements import apply_fixme_replacements
from .processor import process_root

APP_TITLE = "Công cụ AutoCompare"


class AutoCompareApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1220x900")
        self.minsize(1060, 780)

        self.app_config: AppConfig = load_app_config()
        self.root_path = tk.StringVar(value=str(Path.cwd()))
        self.copy_source_path = tk.StringVar()
        self.copy_target_path = tk.StringVar()
        self.folder_compare_left_path = tk.StringVar()
        self.folder_compare_right_path = tk.StringVar()
        self.folder_compare_output_path = tk.StringVar(
            value=str(Path.cwd() / self.app_config.workbooks.folder_compare_file)
        )
        self.compare_option_vars = {
            workflow.key: tk.BooleanVar(value=workflow.default_enabled)
            for workflow in self.app_config.compare_workflows
        }
        self.db_driver = tk.StringVar(value="ODBC Driver 18 for SQL Server")
        self.db_server = tk.StringVar()
        self.db_database = tk.StringVar()
        self.db_trusted = tk.BooleanVar(value=True)
        self.db_username = tk.StringVar()
        self.db_password = tk.StringVar()
        self.db_schema = tk.StringVar(value="dbo")
        self.db_verified = False

        self.note_store = FixmeNoteStore()
        self.fixme_notes: list[FixmeNote] = self.note_store.load()
        self.fixme_entries: list[WorkbookFixmeEntry] = []
        self.fixme_note_vars: list[tk.StringVar] = []
        self.fixme_note_combos: list[ttk.Combobox] = []
        self.note_value = tk.StringVar()
        self.note_meaning = tk.StringVar()
        self.selected_note_value: str | None = None
        self.current_page = tk.StringVar(value="compare")
        self.pages: dict[str, ttk.Frame] = {}

        self.log_queue: queue.Queue[object] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self._bind_db_change_handlers()
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, padding=(10, 12, 8, 12))
        sidebar.grid(row=0, column=0, sticky="ns")
        ttk.Label(sidebar, text="Menu chính").pack(anchor="w", pady=(0, 8))
        for page_key, label in (
            ("compare", "So sánh"),
            ("folder_compare", "So sánh 2 folder CSV"),
            ("copy", "Sao chép file UT"),
            ("sql", "Kết nối SQL Server"),
        ):
            ttk.Radiobutton(
                sidebar,
                text=label,
                value=page_key,
                variable=self.current_page,
                command=lambda key=page_key: self._show_page(key),
                style="Toolbutton",
                width=20,
            ).pack(fill="x", pady=2)

        main_frame = ttk.Frame(self)
        main_frame.grid(row=0, column=1, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=3)
        main_frame.rowconfigure(2, weight=1)

        self.page_container = ttk.Frame(main_frame, padding=(12, 12, 12, 8))
        self.page_container.grid(row=0, column=0, sticky="nsew")
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)

        self._build_compare_page()
        self._build_folder_compare_page()
        self._build_copy_page()
        self._build_sql_page()

        status_frame = ttk.Frame(main_frame, padding=(12, 0, 12, 8))
        status_frame.grid(row=1, column=0, sticky="ew")
        self.status_label = ttk.Label(status_frame, text="Sẵn sàng")
        self.status_label.pack(side="left")

        self.log_text = scrolledtext.ScrolledText(main_frame, wrap="word", state="disabled", height=8)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self._show_page("compare")

    def _build_compare_page(self) -> None:
        page = self._create_page("compare")
        page.rowconfigure(3, weight=1)

        self._build_root_selector(page, row=0)

        compare_options_frame = ttk.LabelFrame(page, text="Tùy chọn so sánh", padding=(12, 8, 12, 8))
        self._build_compare_options_ui(compare_options_frame)
        compare_options_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        action_frame = ttk.Frame(page)
        action_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.compare_button = ttk.Button(action_frame, text="Chạy so sánh", command=self._run_compare)
        self.compare_button.pack(side="left")

        fixme_frame = ttk.LabelFrame(page, text="Kiểm tra FIXME", padding=(12, 8, 12, 8))
        self._build_fixme_ui(fixme_frame)
        fixme_frame.grid(row=3, column=0, sticky="nsew")

    def _build_copy_page(self) -> None:
        page = self._create_page("copy")
        page.rowconfigure(1, weight=1)

        copy_frame = ttk.LabelFrame(page, text="Sao chép file UT", padding=(12, 8, 12, 8))
        self._build_copy_ui(copy_frame)
        copy_frame.grid(row=0, column=0, sticky="ew")

    def _build_folder_compare_page(self) -> None:
        page = self._create_page("folder_compare")
        page.rowconfigure(1, weight=1)

        compare_frame = ttk.LabelFrame(page, text="So sánh 2 folder CSV", padding=(12, 8, 12, 8))
        self._build_folder_compare_ui(compare_frame)
        compare_frame.grid(row=0, column=0, sticky="ew")

    def _build_sql_page(self) -> None:
        page = self._create_page("sql")

        self._build_root_selector(page, row=0)

        db_frame = ttk.LabelFrame(page, text="Kết nối SQL Server", padding=(12, 8, 12, 8))
        self._build_db_ui(db_frame)
        db_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        action_frame = ttk.Frame(page)
        action_frame.grid(row=2, column=0, sticky="ew")
        self.test_db_button = ttk.Button(action_frame, text="Kiểm tra đăng nhập DB", command=self._test_db_login)
        self.test_db_button.pack(side="left")
        self.db_roundtrip_button = ttk.Button(
            action_frame,
            text="Chuẩn hóa CSV",
            command=self._run_db_roundtrip,
            state="disabled",
        )
        self.db_roundtrip_button.pack(side="left", padx=(8, 0))

    def _create_page(self, key: str) -> ttk.Frame:
        page = ttk.Frame(self.page_container)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        self.pages[key] = page
        return page

    def _build_root_selector(self, parent: ttk.Frame, row: int) -> None:
        path_frame = ttk.Frame(parent)
        path_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Thư mục gốc").grid(row=0, column=0, sticky="w", padx=(0, 8))
        path_entry = ttk.Entry(path_frame, textvariable=self.root_path)
        path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(path_frame, text="Chọn...", command=self._browse).grid(row=0, column=2)

    def _show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.current_page.set(key)
        page.tkraise()

    def _build_compare_options_ui(self, compare_options_frame: ttk.LabelFrame) -> None:
        for index, workflow in enumerate(self.app_config.compare_workflows):
            ttk.Checkbutton(
                compare_options_frame,
                text=workflow.label,
                variable=self.compare_option_vars[workflow.key],
            ).grid(row=0, column=index, sticky="w", padx=(0, 24), pady=2)

    def _build_copy_ui(self, copy_frame: ttk.LabelFrame) -> None:
        copy_frame.columnconfigure(1, weight=1)

        ttk.Label(copy_frame, text="Đường dẫn nguồn 1").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(copy_frame, textvariable=self.copy_source_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(copy_frame, text="Chọn...", command=self._browse_copy_source).grid(row=0, column=2, pady=2)

        ttk.Label(copy_frame, text="Đường dẫn đích 2").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(copy_frame, textvariable=self.copy_target_path).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(copy_frame, text="Chọn...", command=self._browse_copy_target).grid(row=1, column=2, pady=2)

        self.copy_button = ttk.Button(copy_frame, text="Chạy sao chép file UT", command=self._run_copy_ut_files)
        self.copy_button.grid(row=2, column=1, sticky="w", pady=(6, 0))

    def _build_folder_compare_ui(self, compare_frame: ttk.LabelFrame) -> None:
        compare_frame.columnconfigure(1, weight=1)

        ttk.Label(compare_frame, text="Folder bên trái").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(compare_frame, textvariable=self.folder_compare_left_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(compare_frame, text="Chọn...", command=self._browse_folder_compare_left).grid(
            row=0,
            column=2,
            pady=2,
        )

        ttk.Label(compare_frame, text="Folder bên phải").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(compare_frame, textvariable=self.folder_compare_right_path).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(compare_frame, text="Chọn...", command=self._browse_folder_compare_right).grid(
            row=1,
            column=2,
            pady=2,
        )

        ttk.Label(compare_frame, text="File Excel xuất ra").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(compare_frame, textvariable=self.folder_compare_output_path).grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(compare_frame, text="Chọn...", command=self._browse_folder_compare_output).grid(
            row=2,
            column=2,
            pady=2,
        )

        self.folder_compare_button = ttk.Button(
            compare_frame,
            text="Chạy so sánh folder CSV",
            command=self._run_folder_compare,
        )
        self.folder_compare_button.grid(row=3, column=1, sticky="w", pady=(6, 0))

    def _build_fixme_ui(self, fixme_frame: ttk.LabelFrame) -> None:
        fixme_frame.columnconfigure(0, weight=1)
        fixme_frame.rowconfigure(3, weight=1)

        action_row = ttk.Frame(fixme_frame)
        action_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(action_row, text="Thêm giá trị combobox", command=self._show_note_editor).pack(side="left")
        ttk.Button(action_row, text="Áp dụng ghi chú đã chọn", command=self._apply_fixme_notes).pack(side="left", padx=(8, 0))
        self.fixme_count_label = ttk.Label(action_row, text="Số FIXME: 0")
        self.fixme_count_label.pack(side="left", padx=(12, 0))

        self.note_editor_frame = ttk.Frame(fixme_frame)
        self.note_editor_frame.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self.note_editor_frame.columnconfigure(1, weight=1)
        self.note_editor_frame.columnconfigure(3, weight=2)
        ttk.Label(self.note_editor_frame, text="Ghi chú").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(self.note_editor_frame, textvariable=self.note_value).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 12),
            pady=2,
        )
        ttk.Label(self.note_editor_frame, text="Ý nghĩa").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(self.note_editor_frame, textvariable=self.note_meaning).grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(0, 12),
            pady=2,
        )
        ttk.Button(self.note_editor_frame, text="Lưu ghi chú", command=self._save_note).grid(
            row=0,
            column=4,
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(self.note_editor_frame, text="Xóa ghi chú", command=self._delete_note).grid(row=0, column=5, pady=2)
        self.note_editor_frame.grid_remove()

        self.note_tree = ttk.Treeview(fixme_frame, columns=("value", "meaning"), show="headings", height=3)
        self.note_tree.heading("value", text="Giá trị combobox")
        self.note_tree.heading("meaning", text="Ý nghĩa")
        self.note_tree.column("value", width=260, stretch=False)
        self.note_tree.column("meaning", width=760, stretch=True)
        self.note_tree.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        self.note_tree.bind("<<TreeviewSelect>>", self._on_note_selected)

        table_container = ttk.Frame(fixme_frame)
        table_container.grid(row=3, column=0, sticky="nsew")
        table_container.columnconfigure(0, weight=1)
        table_container.rowconfigure(0, weight=1)

        self.fixme_canvas = tk.Canvas(table_container, height=220, highlightthickness=0)
        self.fixme_canvas.grid(row=0, column=0, sticky="nsew")
        table_scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=self.fixme_canvas.yview)
        table_scrollbar.grid(row=0, column=1, sticky="ns")
        self.fixme_canvas.configure(yscrollcommand=table_scrollbar.set)

        self.fixme_table_frame = ttk.Frame(self.fixme_canvas)
        self.fixme_table_window = self.fixme_canvas.create_window((0, 0), window=self.fixme_table_frame, anchor="nw")
        self.fixme_table_frame.bind(
            "<Configure>",
            lambda _event: self.fixme_canvas.configure(scrollregion=self.fixme_canvas.bbox("all")),
        )
        self.fixme_canvas.bind(
            "<Configure>",
            lambda event: self.fixme_canvas.itemconfigure(self.fixme_table_window, width=event.width),
        )

        self._refresh_note_list()
        self._refresh_fixme_table()

    def _build_db_ui(self, db_frame: ttk.LabelFrame) -> None:
        for column in (1, 3):
            db_frame.columnconfigure(column, weight=1)

        drivers = get_available_sql_drivers()
        if drivers and self.db_driver.get() not in drivers:
            self.db_driver.set(drivers[-1])

        ttk.Label(db_frame, text="Driver ODBC").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        driver_box = ttk.Combobox(db_frame, textvariable=self.db_driver, values=drivers, state="normal")
        driver_box.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Máy chủ").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_server).grid(row=0, column=3, sticky="ew", pady=2)

        ttk.Label(db_frame, text="Cơ sở dữ liệu").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_database).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Checkbutton(
            db_frame,
            text="Xác thực Windows",
            variable=self.db_trusted,
            command=self._sync_auth_fields,
        ).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=2)

        schema_frame = ttk.Frame(db_frame)
        schema_frame.grid(row=1, column=3, sticky="e", pady=2)
        ttk.Label(schema_frame, text="Schema DB").pack(side="left", padx=(0, 8))
        ttk.Entry(schema_frame, textvariable=self.db_schema, width=16).pack(side="left")

        ttk.Label(db_frame, text="Người dùng").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self.user_entry = ttk.Entry(db_frame, textvariable=self.db_username)
        self.user_entry.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Mật khẩu").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=2)
        self.password_entry = ttk.Entry(db_frame, textvariable=self.db_password, show="*")
        self.password_entry.grid(row=2, column=3, sticky="ew", pady=2)

        self._sync_auth_fields()

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.root_path.get() or str(Path.cwd()))
        if folder:
            self.root_path.set(folder)

    def _browse_copy_source(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.copy_source_path.get() or str(Path.cwd()))
        if folder:
            self.copy_source_path.set(folder)

    def _browse_copy_target(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.copy_target_path.get() or str(Path.cwd()))
        if folder:
            self.copy_target_path.set(folder)

    def _browse_folder_compare_left(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_compare_left_path.get() or str(Path.cwd()))
        if folder:
            self.folder_compare_left_path.set(folder)
            self._refresh_folder_compare_default_output()

    def _browse_folder_compare_right(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_compare_right_path.get() or str(Path.cwd()))
        if folder:
            self.folder_compare_right_path.set(folder)
            self._refresh_folder_compare_default_output()

    def _browse_folder_compare_output(self) -> None:
        raw_output_path = self.folder_compare_output_path.get().strip()
        initial_path = Path(raw_output_path) if raw_output_path else Path.cwd() / self.app_config.workbooks.folder_compare_file
        file_name = filedialog.asksaveasfilename(
            initialdir=str(initial_path.parent if initial_path.parent else Path.cwd()),
            initialfile=initial_path.name or self.app_config.workbooks.folder_compare_file,
            defaultextension=".xlsx",
            filetypes=(("File Excel", "*.xlsx"), ("Tất cả file", "*.*")),
        )
        if file_name:
            self.folder_compare_output_path.set(file_name)

    def _run_compare(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.root_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn thư mục gốc.")
            return
        selected_workflows = self._selected_compare_workflows()
        if not selected_workflows:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn ít nhất một tùy chọn so sánh.")
            return

        self._clear_log()
        self._set_fixme_entries([])
        self._set_actions_busy(True)
        self.status_label.configure(text="Đang chạy...")

        self.worker = threading.Thread(target=self._run_compare_worker, args=(root, selected_workflows), daemon=True)
        self.worker.start()

    def _run_copy_ut_files(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        source = self.copy_source_path.get().strip()
        target = self.copy_target_path.get().strip()
        if not source:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn đường dẫn nguồn 1.")
            return
        if not target:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn đường dẫn đích 2.")
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Đang sao chép file UT...")

        self.worker = threading.Thread(target=self._copy_ut_worker, args=(source, target), daemon=True)
        self.worker.start()

    def _run_folder_compare(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        left = self.folder_compare_left_path.get().strip()
        right = self.folder_compare_right_path.get().strip()
        output = self.folder_compare_output_path.get().strip()
        if not left:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder bên trái.")
            return
        if not right:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder bên phải.")
            return
        if not output:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn file Excel xuất ra.")
            return

        self._clear_log()
        self._set_fixme_entries([])
        self._set_actions_busy(True)
        self.status_label.configure(text="Đang so sánh folder CSV...")

        self.worker = threading.Thread(target=self._folder_compare_worker, args=(left, right, output), daemon=True)
        self.worker.start()

    def _test_db_login(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Đang kiểm tra đăng nhập DB...")

        self.worker = threading.Thread(target=self._test_db_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _run_db_roundtrip(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.root_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn thư mục gốc.")
            return
        if not self.db_verified:
            messagebox.showerror(APP_TITLE, "Vui lòng kiểm tra đăng nhập DB thành công trước.")
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Đang chuẩn hóa CSV...")

        self.worker = threading.Thread(target=self._db_roundtrip_worker, args=(root, settings), daemon=True)
        self.worker.start()

    def _run_compare_worker(self, root: str, selected_workflows: set[str]) -> None:
        try:
            summary = process_root(
                root,
                log=self._log_from_worker,
                selected_workflow_keys=selected_workflows,
                config=self.app_config,
            )
            self.log_queue.put(("__FIXME_ENTRIES__", summary.fixme_entries))
            if summary.errors:
                self._log_from_worker("")
                self._log_from_worker("Hoàn tất với lỗi.")
                self.log_queue.put("__STATUS__:Hoàn tất với lỗi")
                self.log_queue.put("__MESSAGE_ERROR__:Hoàn tất với lỗi. Vui lòng kiểm tra log.")
            else:
                self._log_from_worker("")
                self._log_from_worker(f"Hoàn tất thành công. Đã xử lý {summary.processed_count} case test.")
                self.log_queue.put("__STATUS__:Hoàn tất")
                self.log_queue.put("__MESSAGE_INFO__:Hoàn tất thành công.")
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:Thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _copy_ut_worker(self, source: str, target: str) -> None:
        try:
            log_path = run_copy_ut_files(source, target, log=self._log_from_worker)
            self.log_queue.put("__STATUS__:Sao chép hoàn tất")
            self.log_queue.put(f"__MESSAGE_INFO__:Sao chép hoàn tất. File log: {log_path}")
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:Sao chép thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _folder_compare_worker(self, left: str, right: str, output: str) -> None:
        try:
            summary = compare_csv_folders(left, right, output, log=self._log_from_worker, config=self.app_config)
            self.log_queue.put(("__FIXME_ENTRIES__", summary.fixme_entries))
            self._log_from_worker("")
            self._log_from_worker(
                f"So sánh folder CSV hoàn tất. Đã tạo {summary.output_path} "
                f"với {summary.sheet_count} sheet."
            )
            self.log_queue.put("__STATUS__:So sánh folder CSV hoàn tất")
            self.log_queue.put(f"__MESSAGE_INFO__:So sánh folder CSV hoàn tất. File xuất ra: {summary.output_path}")
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:So sánh folder CSV thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _test_db_worker(self, settings: DatabaseSettings) -> None:
        try:
            test_sqlserver_connection(settings)
            self._log_from_worker("Đăng nhập DB thành công.")
            self.log_queue.put("__DB_VERIFIED__:1")
            self.log_queue.put("__STATUS__:Đăng nhập DB thành công")
            self.log_queue.put("__MESSAGE_INFO__:Đăng nhập DB thành công.")
        except Exception as exc:
            self._log_from_worker(f"Đăng nhập DB thất bại: {exc}")
            self.log_queue.put("__DB_VERIFIED__:0")
            self.log_queue.put("__STATUS__:Đăng nhập DB thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:Đăng nhập DB thất bại: {exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _db_roundtrip_worker(self, root: str, settings: DatabaseSettings) -> None:
        try:
            summary = process_sqlserver_roundtrip(root, settings, log=self._log_from_worker)
            if summary.errors:
                self._log_from_worker("")
                self._log_from_worker("Chuẩn hóa CSV theo DB hoàn tất với lỗi.")
                self.log_queue.put("__STATUS__:Hoàn tất với lỗi")
                self.log_queue.put(
                    "__MESSAGE_ERROR__:Chuẩn hóa CSV theo DB hoàn tất với lỗi. Vui lòng kiểm tra log."
                )
            else:
                self._log_from_worker("")
                self._log_from_worker(f"Chuẩn hóa CSV hoàn tất. Đã xử lý {summary.csv_count} file CSV.")
                self.log_queue.put("__STATUS__:Chuẩn hóa CSV hoàn tất")
                self.log_queue.put("__MESSAGE_INFO__:Chuẩn hóa CSV hoàn tất thành công.")
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:Thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _log_from_worker(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if isinstance(message, tuple) and message and message[0] == "__FIXME_ENTRIES__":
                    self._set_fixme_entries(message[1])
                elif message == "__ENABLE_ACTIONS__":
                    self._set_actions_busy(False)
                elif isinstance(message, str) and message.startswith("__DB_VERIFIED__:"):
                    self.db_verified = message.split(":", 1)[1] == "1"
                    self._refresh_db_button_state()
                elif isinstance(message, str) and message.startswith("__STATUS__:"):
                    self.status_label.configure(text=message.split(":", 1)[1])
                elif isinstance(message, str) and message.startswith("__MESSAGE_ERROR__:"):
                    messagebox.showerror(APP_TITLE, message.split(":", 1)[1])
                elif isinstance(message, str) and message.startswith("__MESSAGE_INFO__:"):
                    messagebox.showinfo(APP_TITLE, message.split(":", 1)[1])
                else:
                    self._append_log(str(message))
        except queue.Empty:
            pass

        self.after(100, self._drain_log_queue)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _get_db_settings(self) -> DatabaseSettings:
        server = self.db_server.get().strip()
        database = self.db_database.get().strip()
        driver = self.db_driver.get().strip()
        schema = self.db_schema.get().strip() or "dbo"

        if not driver:
            raise ValueError("Vui lòng nhập ODBC driver.")
        if not server:
            raise ValueError("Vui lòng nhập tên SQL Server.")
        if not database:
            raise ValueError("Vui lòng nhập tên cơ sở dữ liệu.")
        if not self.db_trusted.get() and not self.db_username.get().strip():
            raise ValueError("Vui lòng nhập người dùng hoặc dùng xác thực Windows.")

        return DatabaseSettings(
            driver=driver,
            server=server,
            database=database,
            trusted_connection=self.db_trusted.get(),
            username=self.db_username.get().strip(),
            password=self.db_password.get(),
            schema=schema,
        )

    def _set_actions_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.compare_button.configure(state=state)
        self.folder_compare_button.configure(state=state)
        self.copy_button.configure(state=state)
        self.test_db_button.configure(state=state)
        if busy:
            self.db_roundtrip_button.configure(state="disabled")
        else:
            self._refresh_db_button_state()

    def _refresh_db_button_state(self) -> None:
        if not hasattr(self, "db_roundtrip_button"):
            return
        self.db_roundtrip_button.configure(state="normal" if self.db_verified else "disabled")

    def _mark_db_unverified(self, *_args) -> None:
        self.db_verified = False
        self._refresh_db_button_state()

    def _bind_db_change_handlers(self) -> None:
        for variable in (
            self.db_driver,
            self.db_server,
            self.db_database,
            self.db_username,
            self.db_password,
            self.db_schema,
        ):
            variable.trace_add("write", self._mark_db_unverified)

    def _sync_auth_fields(self) -> None:
        auth_state = "disabled" if self.db_trusted.get() else "normal"
        self.user_entry.configure(state=auth_state)
        self.password_entry.configure(state=auth_state)
        self._mark_db_unverified()

    def _refresh_folder_compare_default_output(self) -> None:
        if self.folder_compare_output_path.get().strip():
            return
        base_dir = self.folder_compare_right_path.get().strip() or self.folder_compare_left_path.get().strip()
        if not base_dir:
            return
        self.folder_compare_output_path.set(str(Path(base_dir) / self.app_config.workbooks.folder_compare_file))

    def _selected_compare_workflows(self) -> set[str]:
        return {
            workflow_key
            for workflow_key, selected in self.compare_option_vars.items()
            if selected.get()
        }

    def _show_note_editor(self) -> None:
        self.selected_note_value = None
        self.note_value.set("")
        self.note_meaning.set("")
        self.note_editor_frame.grid()

    def _save_note(self) -> None:
        try:
            if self.selected_note_value:
                self.fixme_notes = self.note_store.replace(
                    self.selected_note_value,
                    self.note_value.get(),
                    self.note_meaning.get(),
                )
            else:
                self.fixme_notes = self.note_store.upsert(self.note_value.get(), self.note_meaning.get())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.selected_note_value = self.note_value.get().strip()
        self._refresh_note_list()
        self._refresh_fixme_combo_values()

    def _delete_note(self) -> None:
        try:
            self.fixme_notes = self.note_store.delete(self.selected_note_value or self.note_value.get())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.note_value.set("")
        self.note_meaning.set("")
        self.selected_note_value = None
        self._refresh_note_list()
        self._refresh_fixme_combo_values()

    def _on_note_selected(self, _event: tk.Event) -> None:
        selected = self.note_tree.selection()
        if not selected:
            return
        values = self.note_tree.item(selected[0], "values")
        if len(values) >= 2:
            self.note_value.set(str(values[0]))
            self.note_meaning.set(str(values[1]))
            self.selected_note_value = str(values[0])
            self.note_editor_frame.grid()

    def _refresh_note_list(self) -> None:
        children = self.note_tree.get_children()
        if children:
            self.note_tree.delete(*children)
        for note in self.fixme_notes:
            self.note_tree.insert("", "end", values=(note.value, note.meaning))

    def _set_fixme_entries(self, entries: list[WorkbookFixmeEntry]) -> None:
        self.fixme_entries = entries
        self._refresh_fixme_table()

    def _refresh_fixme_table(self) -> None:
        for child in self.fixme_table_frame.winfo_children():
            child.destroy()

        self.fixme_note_vars = []
        self.fixme_note_combos = []

        columns = [
            ("Tên folder/case", 16),
            ("File Excel", 28),
            ("Tên sheet", 18),
            ("Tên cột", 22),
            ("Giá trị bên trái", 32),
            ("Giá trị bên phải", 32),
            ("STT record", 8),
            ("Ghi chú", 24),
        ]
        for column_index, (title, width) in enumerate(columns):
            label = ttk.Label(self.fixme_table_frame, text=title, width=width, anchor="w")
            label.grid(row=0, column=column_index, sticky="ew", padx=2, pady=(0, 4))

        if not self.fixme_entries:
            ttk.Label(self.fixme_table_frame, text="Không tìm thấy FIXME.").grid(
                row=1,
                column=0,
                columnspan=len(columns),
                sticky="w",
                pady=4,
            )
            self.fixme_count_label.configure(text="Số FIXME: 0")
            return

        for row_index, entry in enumerate(self.fixme_entries, start=1):
            values = [
                entry.case_folder_name,
                entry.workbook_name,
                entry.sheet_name,
                entry.column_name,
                entry.left_value,
                entry.right_value,
                str(entry.record_number),
            ]
            for column_index, value in enumerate(values):
                ttk.Label(
                    self.fixme_table_frame,
                    text=_short_text(value),
                    width=columns[column_index][1],
                    anchor="w",
                    wraplength=240,
                ).grid(row=row_index, column=column_index, sticky="ew", padx=2, pady=1)

            note_var = tk.StringVar()
            combo = ttk.Combobox(
                self.fixme_table_frame,
                textvariable=note_var,
                values=self._note_values(),
                state="readonly" if self.fixme_notes else "disabled",
                width=columns[-1][1],
            )
            combo.grid(row=row_index, column=len(columns) - 1, sticky="ew", padx=2, pady=1)
            self.fixme_note_vars.append(note_var)
            self.fixme_note_combos.append(combo)

        self.fixme_count_label.configure(text=f"Số FIXME: {len(self.fixme_entries)}")

    def _refresh_fixme_combo_values(self) -> None:
        values = self._note_values()
        valid_values = set(values)
        for note_var, combo in zip(self.fixme_note_vars, self.fixme_note_combos):
            if note_var.get() and note_var.get() not in valid_values:
                note_var.set("")
            combo.configure(values=values, state="readonly" if values else "disabled")

    def _note_values(self) -> list[str]:
        return [note.value for note in self.fixme_notes]

    def _apply_fixme_notes(self) -> None:
        selected_notes = {
            index: note_var.get()
            for index, note_var in enumerate(self.fixme_note_vars)
            if note_var.get().strip()
        }
        if not selected_notes:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn ít nhất một ghi chú cho các dòng FIXME.")
            return

        try:
            result = apply_fixme_replacements(self.fixme_entries, selected_notes)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Áp dụng ghi chú thất bại: {exc}")
            return

        messagebox.showinfo(
            APP_TITLE,
            (
                f"Đã áp dụng ghi chú cho {result.cell_count} ô FIXME "
                f"trong {result.workbook_count} file Excel."
            ),
        )


def _short_text(value: str, limit: int = 140) -> str:
    value = value.replace("\r", "\\r").replace("\n", "\\n")
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def main() -> None:
    app = AutoCompareApp()
    app.mainloop()
