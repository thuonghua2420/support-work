from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .app_config import AppConfig, load_app_config
from .copy_ut import run_copy_ut_files
from .database_io import (
    DatabaseConnectionSettings,
    DatabaseCsvSummary,
    DatabaseSyncSummary,
    database_type_options,
    default_port,
    default_schema,
    export_csv_folder,
    get_available_sqlserver_drivers,
    import_csv_folder,
    list_database_names,
    list_database_tables,
    normalize_csv_folder,
    sync_database_tables,
    test_database_connection,
    validate_connection_settings,
)
from .excel_writer import WorkbookFixmeEntry
from .file_utilities import (
    FileUtilitySummary,
    delete_contains_text,
    delete_empty_folders,
    find_empty_folders,
    move_files_contains_text,
    rename_contains_text,
    rename_exact_name,
    rename_excel_sheets_contains,
)
from .folder_compare import compare_csv_folders
from .fixme_notes import FixmeNote, FixmeNoteStore
from .fixme_replacements import apply_fixme_replacements
from .processor import process_root

APP_TITLE = "Công cụ AutoCompare"
NAV_ITEMS = (
    ("compare", "So sánh"),
    ("folder_compare", "So sánh 2 folder CSV"),
    ("file_tools", "Tiện ích file"),
    ("copy", "Sao chép file UT"),
    ("sql", "Cơ sở dữ liệu"),
)


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
        self.utility_root_path = tk.StringVar(value=str(Path.cwd()))
        self.rename_exact_old_name = tk.StringVar()
        self.rename_exact_new_name = tk.StringVar()
        self.rename_exact_include_files = tk.BooleanVar(value=True)
        self.rename_exact_include_folders = tk.BooleanVar(value=True)
        self.rename_contains_text = tk.StringVar()
        self.rename_contains_replacement = tk.StringVar()
        self.rename_contains_include_files = tk.BooleanVar(value=True)
        self.rename_contains_include_folders = tk.BooleanVar(value=True)
        self.delete_contains_text = tk.StringVar()
        self.delete_contains_include_files = tk.BooleanVar(value=True)
        self.delete_contains_include_folders = tk.BooleanVar(value=True)
        self.sheet_excel_path = tk.StringVar()
        self.sheet_contains_text = tk.StringVar()
        self.sheet_replacement_text = tk.StringVar()
        self.move_contains_text = tk.StringVar()
        self.move_target_folder_name = tk.StringVar()
        self.compare_option_vars = {
            workflow.key: tk.BooleanVar(value=workflow.default_enabled)
            for workflow in self.app_config.compare_workflows
        }
        self.db_type = tk.StringVar(value="SQL Server")
        self.db_driver = tk.StringVar(value="ODBC Driver 18 for SQL Server")
        self.db_server = tk.StringVar()
        self.db_port = tk.StringVar(value=default_port(self.db_type.get()))
        self.db_database = tk.StringVar()
        self.db_trusted = tk.BooleanVar(value=True)
        self.db_username = tk.StringVar()
        self.db_password = tk.StringVar()
        self.db_schema = tk.StringVar(value=default_schema(self.db_type.get()) or "dbo")
        self.db_csv_path = tk.StringVar(value=str(Path.cwd()))
        self.db_keep_identity = tk.BooleanVar(value=False)
        self.db_export_tables = tk.StringVar()
        self.db_verified = False
        self.sync_db_vars = {
            "source": self._create_sync_db_vars(),
            "target": self._create_sync_db_vars(),
        }
        self.sync_db_widgets: dict[str, dict[str, object]] = {"source": {}, "target": {}}
        self.sync_source_tables: list[str] = []
        self.sync_filtered_tables: list[str] = []
        self.sync_selected_tables: list[str] = []
        self.sync_table_filter = tk.StringVar()
        self.sync_all_tables = tk.BooleanVar(value=False)
        self.sync_record_limit = tk.StringVar()
        self.sync_keep_identity = tk.BooleanVar(value=True)
        self.sync_truncate_before_sync = tk.BooleanVar(value=False)

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
        self.utility_buttons: list[ttk.Button] = []
        self.db_action_buttons: list[ttk.Button] = []
        self.sync_control_buttons: list[ttk.Button] = []

        self.log_queue: queue.Queue[object] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._configure_styles()
        self._build_ui()
        self._bind_db_change_handlers()
        self.after(100, self._drain_log_queue)

    def _create_sync_db_vars(self) -> dict[str, tk.Variable]:
        return {
            "type": tk.StringVar(value="SQL Server"),
            "driver": tk.StringVar(value="ODBC Driver 18 for SQL Server"),
            "server": tk.StringVar(),
            "port": tk.StringVar(value=default_port("SQL Server")),
            "database": tk.StringVar(),
            "schema": tk.StringVar(value=default_schema("SQL Server") or "dbo"),
            "trusted": tk.BooleanVar(value=True),
            "username": tk.StringVar(),
            "password": tk.StringVar(),
            "verified": tk.BooleanVar(value=False),
        }

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.configure("MenuPanel.TLabelframe", borderwidth=2, relief="ridge")
        style.configure("MenuPanel.TLabelframe.Label", font=("", 9, "bold"))
        style.configure("MenuTag.Toolbutton", anchor="w", borderwidth=2, padding=(10, 7), relief="raised")
        style.map(
            "MenuTag.Toolbutton",
            background=[("selected", "#dbeafe"), ("active", "#eff6ff")],
            relief=[("pressed", "sunken"), ("selected", "sunken"), ("active", "raised")],
        )
        style.configure("TagNotebook.TNotebook", borderwidth=2)
        style.configure("TagNotebook.TNotebook.Tab", borderwidth=1, padding=(14, 6))
        style.map(
            "TagNotebook.TNotebook.Tab",
            background=[("selected", "#e0f2fe"), ("active", "#f0f9ff")],
        )
        style.configure(
            "FixmeHeader.TLabel",
            background="#eef4fb",
            borderwidth=1,
            font=("", 9, "bold"),
            padding=(6, 4),
            relief="solid",
        )

    def _build_ui(self) -> None:
        self.columnconfigure(1, weight=1)
        self.columnconfigure(0, weight=0)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.LabelFrame(
            self,
            text="Menu chính",
            padding=(8, 8, 8, 8),
            style="MenuPanel.TLabelframe",
        )
        sidebar.grid(row=0, column=0, sticky="ns", padx=(2, 8), pady=(4, 4))
        self._build_navigation_tags(sidebar, "MenuTag.Toolbutton", width=22)

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
        self._build_file_tools_page()
        self._build_copy_page()
        self._build_sql_page()

        status_frame = ttk.Frame(main_frame, padding=(12, 0, 12, 8))
        status_frame.grid(row=1, column=0, sticky="ew")
        self.status_label = ttk.Label(status_frame, text="Sẵn sàng")
        self.status_label.pack(side="left")

        self.log_text = scrolledtext.ScrolledText(main_frame, wrap="word", state="disabled", height=8)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        self._show_page("compare")

    def _build_navigation_tags(self, parent: ttk.Widget, style_name: str, width: int) -> None:
        for index, (page_key, label) in enumerate(NAV_ITEMS, start=1):
            tag_text = f"{index}. {label}"
            ttk.Radiobutton(
                parent,
                text=tag_text,
                value=page_key,
                variable=self.current_page,
                command=lambda key=page_key: self._show_page(key),
                style=style_name,
                width=width,
            ).pack(fill="x", pady=4)

    def _build_compare_page(self) -> None:
        page = self._create_page("compare")
        page.rowconfigure(3, weight=1)

        self._build_root_selector(page, row=0)

        compare_options_frame = ttk.LabelFrame(page, text="Tùy chọn so sánh", padding=(12, 8, 12, 8))
        self._build_compare_options_ui(compare_options_frame)
        compare_options_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        action_frame = ttk.Frame(page)
        action_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.compare_button = ttk.Button(action_frame, text="Export File Compare", command=self._run_compare)
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

    def _build_file_tools_page(self) -> None:
        page = self._create_page("file_tools")
        page.rowconfigure(1, weight=1)

        self._build_utility_root_selector(page, row=0)

        notebook = ttk.Notebook(page, style="TagNotebook.TNotebook")
        notebook.grid(row=1, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)

        rename_tab = ttk.Frame(notebook, padding=(12, 10, 12, 10))
        delete_tab = ttk.Frame(notebook, padding=(12, 10, 12, 10))
        sheet_tab = ttk.Frame(notebook, padding=(12, 10, 12, 10))
        move_tab = ttk.Frame(notebook, padding=(12, 10, 12, 10))
        empty_tab = ttk.Frame(notebook, padding=(12, 10, 12, 10))

        notebook.add(rename_tab, text="Đổi tên")
        notebook.add(delete_tab, text="Xóa")
        notebook.add(sheet_tab, text="Sheet Excel")
        notebook.add(move_tab, text="Di chuyển")
        notebook.add(empty_tab, text="Folder trống")

        self._build_rename_tools_ui(rename_tab)
        self._build_delete_tools_ui(delete_tab)
        self._build_sheet_tools_ui(sheet_tab)
        self._build_move_tools_ui(move_tab)
        self._build_empty_folder_tools_ui(empty_tab)

    def _build_sql_page(self) -> None:
        page = self._create_page("sql")
        page.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(page, style="TagNotebook.TNotebook")
        notebook.grid(row=0, column=0, sticky="nsew")

        csv_tab = ttk.Frame(notebook, padding=(8, 8, 8, 8))
        csv_tab.columnconfigure(0, weight=1)
        sync_tab = ttk.Frame(notebook, padding=(8, 8, 8, 8))
        sync_tab.columnconfigure(0, weight=1)
        sync_tab.rowconfigure(2, weight=1)

        notebook.add(csv_tab, text="Nhập/Xuất CSV")
        notebook.add(sync_tab, text="Đồng bộ 2 CSDL")

        db_frame = ttk.LabelFrame(csv_tab, text="Thông tin kết nối CSDL", padding=(12, 8, 12, 8))
        self._build_db_ui(db_frame)
        db_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        csv_frame = ttk.LabelFrame(csv_tab, text="Nhập/Xuất CSV", padding=(12, 8, 12, 8))
        self._build_db_csv_ui(csv_frame)
        csv_frame.grid(row=1, column=0, sticky="ew")

        self._build_db_sync_ui(sync_tab)

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

    def _build_utility_root_selector(self, parent: ttk.Frame, row: int) -> None:
        path_frame = ttk.LabelFrame(parent, text="Folder thao tác", padding=(12, 8, 12, 8))
        path_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Đường dẫn folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(path_frame, textvariable=self.utility_root_path).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(path_frame, text="Chọn...", command=self._browse_utility_root).grid(row=0, column=2)

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
            text="Compare folder CSV",
            command=self._run_folder_compare,
        )
        self.folder_compare_button.grid(row=3, column=1, sticky="w", pady=(6, 0))

    def _build_rename_tools_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        exact_frame = ttk.LabelFrame(parent, text="Đổi tên theo tên chính xác", padding=(12, 8, 12, 8))
        exact_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        exact_frame.columnconfigure(1, weight=1)
        exact_frame.columnconfigure(2, minsize=190)

        ttk.Label(exact_frame, text="Tên cũ").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(exact_frame, textvariable=self.rename_exact_old_name).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Label(exact_frame, text="Tên mới").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(exact_frame, textvariable=self.rename_exact_new_name).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        action_frame = ttk.Frame(exact_frame)
        action_frame.grid(row=0, column=2, rowspan=2, sticky="nsw", padx=(12, 0))
        self._build_file_folder_checks(
            action_frame,
            row=0,
            file_var=self.rename_exact_include_files,
            folder_var=self.rename_exact_include_folders,
        )
        button = ttk.Button(action_frame, text="Chạy đổi tên chính xác", command=self._run_rename_exact)
        button.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self.utility_buttons.append(button)

        contains_frame = ttk.LabelFrame(parent, text="Đổi tên khi tên chứa text", padding=(12, 8, 12, 8))
        contains_frame.grid(row=1, column=0, sticky="ew")
        contains_frame.columnconfigure(1, weight=1)
        contains_frame.columnconfigure(2, minsize=190)

        ttk.Label(contains_frame, text="Text cần tìm").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(contains_frame, textvariable=self.rename_contains_text).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Label(contains_frame, text="Text thay thế").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(contains_frame, textvariable=self.rename_contains_replacement).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        action_frame = ttk.Frame(contains_frame)
        action_frame.grid(row=0, column=2, rowspan=2, sticky="nsw", padx=(12, 0))
        self._build_file_folder_checks(
            action_frame,
            row=0,
            file_var=self.rename_contains_include_files,
            folder_var=self.rename_contains_include_folders,
        )
        button = ttk.Button(action_frame, text="Chạy đổi tên chứa text", command=self._run_rename_contains)
        button.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self.utility_buttons.append(button)

    def _build_delete_tools_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        delete_frame = ttk.LabelFrame(parent, text="Xóa khi tên chứa text", padding=(12, 8, 12, 8))
        delete_frame.grid(row=0, column=0, sticky="ew")
        delete_frame.columnconfigure(1, weight=1)
        delete_frame.columnconfigure(2, minsize=190)

        ttk.Label(delete_frame, text="Text cần tìm").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(delete_frame, textvariable=self.delete_contains_text).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        action_frame = ttk.Frame(delete_frame)
        action_frame.grid(row=0, column=2, rowspan=2, sticky="nsw", padx=(12, 0))
        self._build_file_folder_checks(
            action_frame,
            row=0,
            file_var=self.delete_contains_include_files,
            folder_var=self.delete_contains_include_folders,
        )
        button = ttk.Button(action_frame, text="Chạy xóa chứa text", command=self._run_delete_contains)
        button.grid(row=1, column=0, sticky="ew", pady=(8, 2))
        self.utility_buttons.append(button)

    def _build_sheet_tools_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        sheet_frame = ttk.LabelFrame(parent, text="Đổi tên sheet Excel khi tên chứa text", padding=(12, 8, 12, 8))
        sheet_frame.grid(row=0, column=0, sticky="ew")
        sheet_frame.columnconfigure(1, weight=1)
        sheet_frame.columnconfigure(2, minsize=90)
        sheet_frame.columnconfigure(3, minsize=170)

        ttk.Label(sheet_frame, text="File Excel").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(sheet_frame, textvariable=self.sheet_excel_path).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(sheet_frame, text="Chọn...", command=self._browse_sheet_excel).grid(row=0, column=2, pady=2)

        ttk.Label(sheet_frame, text="Text cần tìm").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(sheet_frame, textvariable=self.sheet_contains_text).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Label(sheet_frame, text="Text thay thế").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(sheet_frame, textvariable=self.sheet_replacement_text).grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )

        button = ttk.Button(sheet_frame, text="Chạy đổi tên sheet", command=self._run_rename_sheets)
        button.grid(row=1, column=3, rowspan=2, sticky="ew", padx=(12, 0), pady=(8, 2))
        self.utility_buttons.append(button)

    def _build_move_tools_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        move_frame = ttk.LabelFrame(parent, text="Di chuyển file khi tên chứa text", padding=(12, 8, 12, 8))
        move_frame.grid(row=0, column=0, sticky="ew")
        move_frame.columnconfigure(1, weight=1)
        move_frame.columnconfigure(2, minsize=190)

        ttk.Label(move_frame, text="Text cần tìm").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(move_frame, textvariable=self.move_contains_text).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Label(move_frame, text="Folder đích").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(move_frame, textvariable=self.move_target_folder_name).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )

        button = ttk.Button(move_frame, text="Chạy di chuyển file", command=self._run_move_files)
        button.grid(row=0, column=2, rowspan=2, sticky="ew", padx=(12, 0), pady=(8, 2))
        self.utility_buttons.append(button)

    def _build_empty_folder_tools_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        empty_frame = ttk.LabelFrame(parent, text="Kiểm tra và xóa folder trống", padding=(12, 8, 12, 8))
        empty_frame.grid(row=0, column=0, sticky="ew")

        check_button = ttk.Button(empty_frame, text="Kiểm tra folder trống", command=self._run_find_empty_folders)
        check_button.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.utility_buttons.append(check_button)

        delete_button = ttk.Button(empty_frame, text="Xóa folder trống", command=self._run_delete_empty_folders)
        delete_button.grid(row=0, column=1, sticky="w")
        self.utility_buttons.append(delete_button)

    def _build_file_folder_checks(
        self,
        parent: ttk.Frame,
        row: int,
        file_var: tk.BooleanVar,
        folder_var: tk.BooleanVar,
    ) -> None:
        option_frame = ttk.Frame(parent)
        option_frame.grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Checkbutton(option_frame, text="File", variable=file_var).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(option_frame, text="Folder", variable=folder_var).pack(side="left")

    def _build_fixme_ui(self, fixme_frame: ttk.LabelFrame) -> None:
        fixme_frame.columnconfigure(0, weight=1)
        fixme_frame.rowconfigure(3, weight=1)

        action_row = ttk.Frame(fixme_frame)
        action_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(action_row, text="Add note", command=self._show_note_editor).pack(side="left")
        ttk.Button(action_row, text="Apply selected notes", command=self._apply_fixme_notes).pack(side="left", padx=(8, 0))
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

        drivers = get_available_sqlserver_drivers()
        if drivers and self.db_driver.get() not in drivers:
            self.db_driver.set(drivers[-1])

        ttk.Label(db_frame, text="Loại CSDL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self.db_type_box = ttk.Combobox(
            db_frame,
            textvariable=self.db_type,
            values=database_type_options(),
            state="readonly",
        )
        self.db_type_box.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Server").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_server).grid(row=0, column=3, sticky="ew", pady=2)

        ttk.Label(db_frame, text="Port").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_port).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Database").grid(row=1, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_database).grid(row=1, column=3, sticky="ew", pady=2)

        self.db_driver_label = ttk.Label(db_frame, text="Driver ODBC")
        self.db_driver_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self.db_driver_box = ttk.Combobox(db_frame, textvariable=self.db_driver, values=drivers, state="normal")
        self.db_driver_box.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Schema").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_schema).grid(row=2, column=3, sticky="ew", pady=2)

        ttk.Label(db_frame, text="User").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        self.user_entry = ttk.Entry(db_frame, textvariable=self.db_username)
        self.user_entry.grid(row=3, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Password").grid(row=3, column=2, sticky="w", padx=(0, 8), pady=2)
        self.password_entry = ttk.Entry(db_frame, textvariable=self.db_password, show="*")
        self.password_entry.grid(row=3, column=3, sticky="ew", pady=2)

        self.trusted_check = ttk.Checkbutton(
            db_frame,
            text="Windows Authentication",
            variable=self.db_trusted,
            command=self._sync_auth_fields,
        )
        self.trusted_check.grid(row=4, column=0, sticky="w", padx=(0, 8), pady=2)

        self.test_db_button = ttk.Button(db_frame, text="Test Database Connection", command=self._test_db_login)
        self.test_db_button.grid(row=4, column=1, sticky="w", pady=(6, 0))

        self._sync_db_type_fields()

    def _build_db_csv_ui(self, csv_frame: ttk.LabelFrame) -> None:
        csv_frame.columnconfigure(1, weight=1)
        csv_frame.columnconfigure(3, weight=1)

        ttk.Label(csv_frame, text="Folder CSV").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(csv_frame, textvariable=self.db_csv_path).grid(
            row=0,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Button(csv_frame, text="Chọn...", command=self._browse_db_csv_path).grid(row=0, column=4, pady=2)

        ttk.Checkbutton(
            csv_frame,
            text="Giữ nguyên giá trị identity khi nhập",
            variable=self.db_keep_identity,
        ).grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(csv_frame, text="Bảng xuất").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(csv_frame, textvariable=self.db_export_tables).grid(
            row=2,
            column=1,
            columnspan=3,
            sticky="ew",
            padx=(0, 8),
            pady=2,
        )
        ttk.Label(csv_frame, text="Bỏ trống để xuất tất cả bảng trong schema").grid(
            row=3,
            column=1,
            columnspan=3,
            sticky="w",
            pady=(0, 4),
        )

        action_frame = ttk.Frame(csv_frame)
        action_frame.grid(row=4, column=1, columnspan=3, sticky="w", pady=(6, 0))

        self.db_roundtrip_button = ttk.Button(
            action_frame,
            text="Chuẩn hóa CSV",
            command=self._run_db_roundtrip,
            state="disabled",
        )
        self.db_roundtrip_button.pack(side="left")
        self.db_action_buttons.append(self.db_roundtrip_button)

        self.db_import_button = ttk.Button(
            action_frame,
            text="Nhập CSV vào CSDL",
            command=self._run_db_import,
            state="disabled",
        )
        self.db_import_button.pack(side="left", padx=(8, 0))
        self.db_action_buttons.append(self.db_import_button)

        self.db_export_button = ttk.Button(
            action_frame,
            text="Xuất CSDL ra CSV",
            command=self._run_db_export,
            state="disabled",
        )
        self.db_export_button.pack(side="left", padx=(8, 0))
        self.db_action_buttons.append(self.db_export_button)

    def _build_db_sync_ui(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        guide_frame = ttk.LabelFrame(parent, text="Ghi chú sử dụng", padding=(12, 8, 12, 8))
        guide_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        guide_text = (
            "Đồng bộ sẽ sao chép dữ liệu từ CSDL nguồn sang CSDL đích. Hai bên cần cùng DDL/cùng column; "
            "computed/generated/rowversion sẽ tự bỏ qua khi insert. Nếu bật truncate, dữ liệu table đích sẽ bị xóa sạch "
            "trước khi insert dữ liệu nguồn."
        )
        ttk.Label(guide_frame, text=guide_text, wraplength=980, justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(
            guide_frame,
            text="Bấm Tải CSDL để lấy danh sách database từ connection, chọn database/schema rồi bấm Test kết nối cho từng bên.",
            wraplength=980,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            guide_frame,
            text="Sau khi test nguồn thành công, danh sách table của database nguồn sẽ được tải xuống ô chọn table.",
            wraplength=980,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(
            guide_frame,
            text="Muốn dữ liệu 2 bên giống nhau đầy đủ: bật truncate trước khi đồng bộ và bỏ trống ô số record.",
            wraplength=980,
            justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

        connection_frame = ttk.Frame(parent)
        connection_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        connection_frame.columnconfigure(0, weight=1)
        connection_frame.columnconfigure(1, weight=1)

        source_frame = ttk.LabelFrame(connection_frame, text="CSDL nguồn", padding=(12, 8, 12, 8))
        source_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        target_frame = ttk.LabelFrame(connection_frame, text="CSDL đích", padding=(12, 8, 12, 8))
        target_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_sync_connection_ui(source_frame, "source")
        self._build_sync_connection_ui(target_frame, "target")

        table_frame = ttk.LabelFrame(parent, text="Table và số record đồng bộ", padding=(12, 8, 12, 8))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(1, weight=1)
        table_frame.rowconfigure(3, weight=1)

        ttk.Checkbutton(
            table_frame,
            text="Chọn toàn bộ table trong database nguồn",
            variable=self.sync_all_tables,
            command=self._on_sync_all_tables_changed,
        ).grid(row=0, column=1, sticky="w", pady=(0, 4))

        ttk.Label(table_frame, text="Table nguồn").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        self.sync_table_combo = ttk.Combobox(
            table_frame,
            textvariable=self.sync_table_filter,
            values=[],
            state="normal",
            postcommand=self._refresh_sync_table_combo_values,
        )
        self.sync_table_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.sync_table_combo.bind("<KeyRelease>", lambda _event: self._refresh_sync_table_combo_values())
        self.sync_table_combo.bind("<<ComboboxSelected>>", lambda _event: self._add_sync_table_from_combo())
        self.sync_add_table_button = ttk.Button(table_frame, text="Thêm table", command=self._add_sync_table_from_combo)
        self.sync_add_table_button.grid(row=1, column=2, sticky="ew", pady=2)
        self.sync_control_buttons.append(self.sync_add_table_button)
        self.sync_add_filtered_button = ttk.Button(
            table_frame,
            text="Thêm kết quả lọc",
            command=self._add_filtered_sync_tables,
        )
        self.sync_add_filtered_button.grid(row=2, column=2, sticky="ew", pady=(0, 4))
        self.sync_control_buttons.append(self.sync_add_filtered_button)

        ttk.Label(
            table_frame,
            text="Gõ text để search trong combobox, chọn table rồi bấm Thêm table; bấm Thêm kết quả lọc để thêm nhiều table cùng lúc.",
            wraplength=980,
            justify="left",
        ).grid(row=2, column=1, sticky="w", pady=(0, 4))

        ttk.Label(table_frame, text="Table đã chọn").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=2)
        selected_frame = ttk.Frame(table_frame)
        selected_frame.grid(row=3, column=1, sticky="nsew", padx=(0, 8), pady=2)
        selected_frame.columnconfigure(0, weight=1)
        selected_frame.rowconfigure(0, weight=1)
        self.sync_selected_table_listbox = tk.Listbox(
            selected_frame,
            selectmode="extended",
            exportselection=False,
            height=5,
        )
        self.sync_selected_table_listbox.grid(row=0, column=0, sticky="nsew")
        selected_scrollbar = ttk.Scrollbar(
            selected_frame,
            orient="vertical",
            command=self.sync_selected_table_listbox.yview,
        )
        selected_scrollbar.grid(row=0, column=1, sticky="ns")
        self.sync_selected_table_listbox.configure(yscrollcommand=selected_scrollbar.set)

        selected_buttons = ttk.Frame(table_frame)
        selected_buttons.grid(row=3, column=2, sticky="new", pady=2)
        self.sync_remove_table_button = ttk.Button(
            selected_buttons,
            text="Xóa table chọn",
            command=self._remove_selected_sync_tables,
        )
        self.sync_remove_table_button.pack(fill="x")
        self.sync_control_buttons.append(self.sync_remove_table_button)
        self.sync_clear_tables_button = ttk.Button(
            selected_buttons,
            text="Xóa danh sách",
            command=self._clear_sync_tables,
        )
        self.sync_clear_tables_button.pack(fill="x", pady=(6, 0))
        self.sync_control_buttons.append(self.sync_clear_tables_button)

        ttk.Label(table_frame, text="Số record đồng bộ").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(table_frame, textvariable=self.sync_record_limit, width=18).grid(row=4, column=1, sticky="w", pady=2)
        ttk.Label(table_frame, text="Bỏ trống để đồng bộ toàn bộ data trong table và làm 2 bên giống nhau đầy đủ.").grid(
            row=5,
            column=1,
            columnspan=2,
            sticky="w",
            pady=(0, 4),
        )

        ttk.Checkbutton(
            table_frame,
            text="Giữ nguyên giá trị identity khi đồng bộ",
            variable=self.sync_keep_identity,
        ).grid(row=6, column=1, sticky="w", pady=2)

        ttk.Checkbutton(
            table_frame,
            text="Truncate dữ liệu CSDL đích trước khi đồng bộ",
            variable=self.sync_truncate_before_sync,
        ).grid(row=7, column=1, sticky="w", pady=2)
        ttk.Label(
            table_frame,
            text=(
                "Khi bật option này, toàn bộ dữ liệu của các table đích đã chọn sẽ bị xóa sạch trước khi insert dữ liệu nguồn. "
                "Nếu table có foreign key/ràng buộc không cho truncate, database sẽ báo lỗi."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=8, column=1, columnspan=2, sticky="w", pady=(0, 4))

        self.sync_run_button = ttk.Button(
            table_frame,
            text="Chạy đồng bộ dữ liệu",
            command=self._run_db_sync,
            state="disabled",
        )
        self.sync_run_button.grid(row=9, column=1, sticky="w", pady=(8, 0))
        self.sync_control_buttons.append(self.sync_run_button)

        self._refresh_sync_button_state()

    def _build_sync_connection_ui(self, parent: ttk.LabelFrame, role: str) -> None:
        parent.columnconfigure(1, weight=1)
        vars_by_name = self.sync_db_vars[role]
        widgets = self.sync_db_widgets[role]
        drivers = get_available_sqlserver_drivers()
        driver_var = vars_by_name["driver"]
        if drivers and driver_var.get() not in drivers:
            driver_var.set(drivers[-1])

        ttk.Label(parent, text="Loại CSDL").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        type_box = ttk.Combobox(
            parent,
            textvariable=vars_by_name["type"],
            values=database_type_options(),
            state="readonly",
        )
        type_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        widgets["type_box"] = type_box

        ttk.Label(parent, text="Máy chủ").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(parent, textvariable=vars_by_name["server"]).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=2,
        )

        ttk.Label(parent, text="Cổng").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(parent, textvariable=vars_by_name["port"]).grid(row=2, column=1, columnspan=2, sticky="ew", pady=2)

        ttk.Label(parent, text="CSDL").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=2)
        database_box = ttk.Combobox(parent, textvariable=vars_by_name["database"], values=[], state="normal")
        database_box.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=2)
        widgets["database_box"] = database_box
        load_button = ttk.Button(parent, text="Tải CSDL", command=lambda key=role: self._load_sync_databases(key))
        load_button.grid(row=3, column=2, sticky="ew", pady=2)
        widgets["load_button"] = load_button
        self.sync_control_buttons.append(load_button)

        ttk.Label(parent, text="Schema").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(parent, textvariable=vars_by_name["schema"]).grid(row=4, column=1, columnspan=2, sticky="ew", pady=2)

        driver_label = ttk.Label(parent, text="Driver ODBC")
        driver_label.grid(row=5, column=0, sticky="w", padx=(0, 8), pady=2)
        driver_box = ttk.Combobox(parent, textvariable=vars_by_name["driver"], values=drivers, state="normal")
        driver_box.grid(row=5, column=1, columnspan=2, sticky="ew", pady=2)
        widgets["driver_box"] = driver_box

        ttk.Label(parent, text="Người dùng").grid(row=6, column=0, sticky="w", padx=(0, 8), pady=2)
        user_entry = ttk.Entry(parent, textvariable=vars_by_name["username"])
        user_entry.grid(row=6, column=1, columnspan=2, sticky="ew", pady=2)
        widgets["user_entry"] = user_entry

        ttk.Label(parent, text="Mật khẩu").grid(row=7, column=0, sticky="w", padx=(0, 8), pady=2)
        password_entry = ttk.Entry(parent, textvariable=vars_by_name["password"], show="*")
        password_entry.grid(row=7, column=1, columnspan=2, sticky="ew", pady=2)
        widgets["password_entry"] = password_entry

        trusted_check = ttk.Checkbutton(
            parent,
            text="Xác thực Windows",
            variable=vars_by_name["trusted"],
            command=lambda key=role: self._sync_sync_auth_fields(key),
        )
        trusted_check.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        widgets["trusted_check"] = trusted_check

        test_button = ttk.Button(parent, text="Test kết nối", command=lambda key=role: self._test_sync_db_login(key))
        test_button.grid(row=8, column=2, sticky="ew", pady=(6, 0))
        widgets["test_button"] = test_button
        self.sync_control_buttons.append(test_button)

        self._sync_sync_db_type_fields(role)

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.root_path.get() or str(Path.cwd()))
        if folder:
            self.root_path.set(folder)

    def _browse_db_csv_path(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.db_csv_path.get() or str(Path.cwd()))
        if folder:
            self.db_csv_path.set(folder)

    def _load_sync_databases(self, role: str) -> None:
        if self.worker and self.worker.is_alive():
            return

        settings = self._get_sync_raw_settings(role)
        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text=f"Đang tải danh sách CSDL {'nguồn' if role == 'source' else 'đích'}...")

        self.worker = threading.Thread(target=self._load_sync_databases_worker, args=(role, settings), daemon=True)
        self.worker.start()

    def _test_sync_db_login(self, role: str) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            settings = self._get_sync_settings(role)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text=f"Đang kiểm tra CSDL {'nguồn' if role == 'source' else 'đích'}...")

        self.worker = threading.Thread(target=self._test_sync_db_worker, args=(role, settings), daemon=True)
        self.worker.start()

    def _run_db_sync(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        if not self.sync_db_vars["source"]["verified"].get():
            messagebox.showerror(APP_TITLE, "Vui lòng test kết nối CSDL nguồn thành công trước.")
            return
        if not self.sync_db_vars["target"]["verified"].get():
            messagebox.showerror(APP_TITLE, "Vui lòng test kết nối CSDL đích thành công trước.")
            return

        selected_tables = self._selected_sync_tables()
        if not selected_tables:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn ít nhất một table hoặc chọn toàn bộ table.")
            return

        try:
            source_settings = self._get_sync_settings("source")
            target_settings = self._get_sync_settings("target")
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        table_message = "toàn bộ table nguồn" if self.sync_all_tables.get() else f"{len(selected_tables)} table đã chọn"
        truncate_message = (
            "\n\nCẢNH BÁO: Option truncate đang bật. Dữ liệu hiện có trong các table đích đã chọn sẽ bị xóa sạch trước khi insert dữ liệu nguồn. Nếu có foreign key/ràng buộc, database có thể không cho truncate."
            if self.sync_truncate_before_sync.get()
            else "\n\nOption truncate đang tắt. Công cụ sẽ insert thêm vào dữ liệu hiện có ở CSDL đích."
        )
        record_limit = self.sync_record_limit.get().strip()
        limit_message = (
            f"\n\nLưu ý: Bạn đang nhập số record đồng bộ = {record_limit}; "
            "nếu bật truncate thì table đích sẽ chỉ còn số record này sau khi đồng bộ."
            if record_limit
            else ""
        )
        confirm_message = (
            f"Bạn chắc chắn muốn đồng bộ {table_message} từ CSDL nguồn sang CSDL đích?\n\n"
            "Để 2 bên giống nhau, hãy bật option truncate trước khi đồng bộ nếu cần xóa dữ liệu cũ ở CSDL đích."
            f"{truncate_message}"
            f"{limit_message}"
        )
        if not messagebox.askyesno(APP_TITLE, confirm_message):
            return

        self._start_database_action(
            "Đang đồng bộ dữ liệu giữa 2 CSDL...",
            sync_database_tables,
            source_settings,
            target_settings,
            selected_tables,
            self.sync_record_limit.get(),
            self.sync_keep_identity.get(),
            self.sync_truncate_before_sync.get(),
        )

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

    def _browse_utility_root(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.utility_root_path.get() or str(Path.cwd()))
        if folder:
            self.utility_root_path.set(folder)

    def _browse_sheet_excel(self) -> None:
        file_name = filedialog.askopenfilename(
            initialdir=str(Path(self.sheet_excel_path.get()).parent)
            if self.sheet_excel_path.get().strip()
            else str(Path.cwd()),
            filetypes=(("File Excel", "*.xlsx *.xlsm"), ("Tất cả file", "*.*")),
        )
        if file_name:
            self.sheet_excel_path.set(file_name)

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

    def _run_rename_exact(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        self._start_file_utility(
            "Đang đổi tên chính xác...",
            rename_exact_name,
            root,
            self.rename_exact_old_name.get(),
            self.rename_exact_new_name.get(),
            self.rename_exact_include_files.get(),
            self.rename_exact_include_folders.get(),
        )

    def _run_rename_contains(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        self._start_file_utility(
            "Đang đổi tên chứa text...",
            rename_contains_text,
            root,
            self.rename_contains_text.get(),
            self.rename_contains_replacement.get(),
            self.rename_contains_include_files.get(),
            self.rename_contains_include_folders.get(),
        )

    def _run_delete_contains(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Bạn chắc chắn muốn xóa các file/folder có tên chứa text đã nhập?",
        ):
            return
        self._start_file_utility(
            "Đang xóa theo text...",
            delete_contains_text,
            root,
            self.delete_contains_text.get(),
            self.delete_contains_include_files.get(),
            self.delete_contains_include_folders.get(),
        )

    def _run_rename_sheets(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        excel_path = self.sheet_excel_path.get().strip()
        if not excel_path:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn file Excel.")
            return
        self._start_file_utility(
            "Đang đổi tên sheet Excel...",
            rename_excel_sheets_contains,
            excel_path,
            self.sheet_contains_text.get(),
            self.sheet_replacement_text.get(),
        )

    def _run_move_files(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        self._start_file_utility(
            "Đang di chuyển file...",
            move_files_contains_text,
            root,
            self.move_contains_text.get(),
            self.move_target_folder_name.get(),
        )

    def _run_find_empty_folders(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        self._start_file_utility("Đang kiểm tra folder trống...", find_empty_folders, root)

    def _run_delete_empty_folders(self) -> None:
        root = self._utility_root_value()
        if root is None:
            return
        if not messagebox.askyesno(APP_TITLE, "Bạn chắc chắn muốn xóa toàn bộ folder trống bên dưới folder thao tác?"):
            return
        self._start_file_utility("Đang xóa folder trống...", delete_empty_folders, root)

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
        self.status_label.configure(text="Đang kiểm tra kết nối CSDL...")

        self.worker = threading.Thread(target=self._test_db_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _run_db_roundtrip(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.db_csv_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder CSV.")
            return
        if not self.db_verified:
            messagebox.showerror(APP_TITLE, "Vui lòng kiểm tra kết nối CSDL thành công trước.")
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._start_database_action("Đang chuẩn hóa CSV...", normalize_csv_folder, root, settings)

    def _run_db_import(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.db_csv_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder CSV.")
            return
        if not self.db_verified:
            messagebox.showerror(APP_TITLE, "Vui lòng kiểm tra kết nối CSDL thành công trước.")
            return
        if not messagebox.askyesno(APP_TITLE, "Bạn chắc chắn muốn nhập toàn bộ CSV trong folder vào CSDL đã kết nối?"):
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._start_database_action(
            "Đang nhập CSV vào CSDL...",
            import_csv_folder,
            root,
            settings,
            self.db_keep_identity.get(),
        )

    def _run_db_export(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.db_csv_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder CSV.")
            return
        if not self.db_verified:
            messagebox.showerror(APP_TITLE, "Vui lòng kiểm tra kết nối CSDL thành công trước.")
            return
        if not messagebox.askyesno(APP_TITLE, "Bạn chắc chắn muốn xuất dữ liệu CSDL ra folder CSV đã chọn?"):
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return

        self._start_database_action(
            "Đang xuất CSDL ra CSV...",
            export_csv_folder,
            root,
            settings,
            self.db_export_tables.get(),
        )

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

    def _start_file_utility(self, status_text: str, operation, *args) -> None:
        if self.worker and self.worker.is_alive():
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text=status_text)

        self.worker = threading.Thread(target=self._file_utility_worker, args=(operation, args), daemon=True)
        self.worker.start()

    def _file_utility_worker(self, operation, args: tuple[object, ...]) -> None:
        try:
            summary: FileUtilitySummary = operation(*args, log=self._log_from_worker)
            if summary.error_count:
                self.log_queue.put("__STATUS__:Tiện ích file hoàn tất với lỗi")
                self.log_queue.put("__MESSAGE_ERROR__:Tiện ích file hoàn tất với lỗi. Vui lòng kiểm tra log.")
            else:
                self.log_queue.put("__STATUS__:Tiện ích file hoàn tất")
                self.log_queue.put(
                    "__MESSAGE_INFO__:"
                    f"{summary.action_name} hoàn tất. "
                    f"Tìm thấy {summary.found_count} mục, xử lý {summary.changed_count} mục."
                )
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:Tiện ích file thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _start_database_action(self, status_text: str, operation, *args) -> None:
        if self.worker and self.worker.is_alive():
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text=status_text)

        self.worker = threading.Thread(target=self._database_action_worker, args=(operation, args), daemon=True)
        self.worker.start()

    def _database_action_worker(self, operation, args: tuple[object, ...]) -> None:
        try:
            summary: DatabaseCsvSummary | DatabaseSyncSummary = operation(*args, log=self._log_from_worker)
            if summary.error_count:
                self.log_queue.put("__STATUS__:Thao tác CSDL hoàn tất với lỗi")
                self.log_queue.put("__MESSAGE_ERROR__:Thao tác CSDL hoàn tất với lỗi. Vui lòng kiểm tra log.")
            elif isinstance(summary, DatabaseSyncSummary):
                self.log_queue.put("__STATUS__:Đồng bộ dữ liệu CSDL hoàn tất")
                self.log_queue.put(
                    "__MESSAGE_INFO__:"
                    f"{summary.action_name} hoàn tất. "
                    f"Đã xử lý {summary.table_count} table, {summary.row_count} dòng."
                )
            else:
                self.log_queue.put("__STATUS__:Thao tác CSDL hoàn tất")
                self.log_queue.put(
                    "__MESSAGE_INFO__:"
                    f"{summary.action_name} hoàn tất. "
                    f"Đã xử lý {summary.csv_count} file CSV, {summary.row_count} dòng."
                )
        except Exception as exc:
            self._log_from_worker(f"LỖI: {exc}")
            self.log_queue.put("__STATUS__:Thao tác CSDL thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _test_db_worker(self, settings: DatabaseConnectionSettings) -> None:
        try:
            test_database_connection(settings)
            self._log_from_worker("Kết nối CSDL thành công.")
            self.log_queue.put("__DB_VERIFIED__:1")
            self.log_queue.put("__STATUS__:Kết nối CSDL thành công")
            self.log_queue.put("__MESSAGE_INFO__:Kết nối CSDL thành công.")
        except Exception as exc:
            self._log_from_worker(f"Kết nối CSDL thất bại: {exc}")
            self.log_queue.put("__DB_VERIFIED__:0")
            self.log_queue.put("__STATUS__:Kết nối CSDL thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:Kết nối CSDL thất bại: {exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _load_sync_databases_worker(self, role: str, settings: DatabaseConnectionSettings) -> None:
        role_label = "nguồn" if role == "source" else "đích"
        try:
            database_names = list_database_names(settings)
            self._log_from_worker(f"CSDL {role_label}: đã tải {len(database_names)} database.")
            self.log_queue.put(("__SYNC_DATABASES__", role, database_names))
            self.log_queue.put(f"__STATUS__:Đã tải danh sách CSDL {role_label}")
            self.log_queue.put(f"__MESSAGE_INFO__:Đã tải danh sách CSDL {role_label}.")
        except Exception as exc:
            self._log_from_worker(f"Tải danh sách CSDL {role_label} thất bại: {exc}")
            self.log_queue.put(f"__STATUS__:Tải danh sách CSDL {role_label} thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:Tải danh sách CSDL {role_label} thất bại: {exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _test_sync_db_worker(self, role: str, settings: DatabaseConnectionSettings) -> None:
        role_label = "nguồn" if role == "source" else "đích"
        try:
            test_database_connection(settings)
            tables = list_database_tables(settings)
            self._log_from_worker(f"Kết nối CSDL {role_label} thành công. Tải được {len(tables)} table.")
            self.log_queue.put(("__SYNC_VERIFIED__", role, True))
            if role == "source":
                self.log_queue.put(("__SYNC_SOURCE_TABLES__", tables))
            self.log_queue.put(f"__STATUS__:Kết nối CSDL {role_label} thành công")
            self.log_queue.put(f"__MESSAGE_INFO__:Kết nối CSDL {role_label} thành công.")
        except Exception as exc:
            self._log_from_worker(f"Kết nối CSDL {role_label} thất bại: {exc}")
            self.log_queue.put(("__SYNC_VERIFIED__", role, False))
            self.log_queue.put(f"__STATUS__:Kết nối CSDL {role_label} thất bại")
            self.log_queue.put(f"__MESSAGE_ERROR__:Kết nối CSDL {role_label} thất bại: {exc}")
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
                elif isinstance(message, tuple) and message and message[0] == "__SYNC_DATABASES__":
                    self._set_sync_database_names(str(message[1]), list(message[2]))
                elif isinstance(message, tuple) and message and message[0] == "__SYNC_VERIFIED__":
                    self._set_sync_verified(str(message[1]), bool(message[2]))
                elif isinstance(message, tuple) and message and message[0] == "__SYNC_SOURCE_TABLES__":
                    self._set_sync_source_tables(list(message[1]))
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

    def _get_db_settings(self) -> DatabaseConnectionSettings:
        return validate_connection_settings(
            DatabaseConnectionSettings(
                database_type=self.db_type.get(),
                host=self.db_server.get(),
                port=self.db_port.get(),
                database=self.db_database.get(),
                schema=self.db_schema.get(),
                trusted_connection=self.db_trusted.get(),
                username=self.db_username.get(),
                password=self.db_password.get(),
                driver=self.db_driver.get(),
            )
        )

    def _get_sync_raw_settings(self, role: str) -> DatabaseConnectionSettings:
        vars_by_name = self.sync_db_vars[role]
        return DatabaseConnectionSettings(
            database_type=vars_by_name["type"].get(),
            host=vars_by_name["server"].get(),
            port=vars_by_name["port"].get(),
            database=vars_by_name["database"].get(),
            schema=vars_by_name["schema"].get(),
            trusted_connection=vars_by_name["trusted"].get(),
            username=vars_by_name["username"].get(),
            password=vars_by_name["password"].get(),
            driver=vars_by_name["driver"].get(),
        )

    def _get_sync_settings(self, role: str) -> DatabaseConnectionSettings:
        return validate_connection_settings(self._get_sync_raw_settings(role))

    def _set_sync_database_names(self, role: str, database_names: list[str]) -> None:
        database_box = self.sync_db_widgets[role].get("database_box")
        if database_box is not None:
            database_box.configure(values=database_names)
        current_database = self.sync_db_vars[role]["database"].get().strip()
        if not current_database and len(database_names) == 1:
            self.sync_db_vars[role]["database"].set(database_names[0])

    def _set_sync_verified(self, role: str, verified: bool) -> None:
        self.sync_db_vars[role]["verified"].set(verified)
        if not verified and role == "source":
            self._set_sync_source_tables([])
        self._refresh_sync_button_state()

    def _set_sync_source_tables(self, tables: list[str]) -> None:
        self.sync_source_tables = sorted(dict.fromkeys(tables), key=str.casefold)
        self.sync_selected_tables = [table for table in self.sync_selected_tables if table in self.sync_source_tables]
        if not self.sync_source_tables:
            self.sync_all_tables.set(False)
        self._refresh_sync_selected_table_list()
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _refresh_sync_table_combo_values(self) -> None:
        if not hasattr(self, "sync_table_combo"):
            return
        filter_text = self.sync_table_filter.get().strip().casefold()
        selected = set(self.sync_selected_tables)
        values = [table for table in self.sync_source_tables if table not in selected]
        if filter_text:
            values = [table for table in values if filter_text in table.casefold()]
        self.sync_filtered_tables = values
        self.sync_table_combo.configure(values=values)

    def _add_sync_table_from_combo(self) -> None:
        if self.sync_all_tables.get():
            return
        raw_value = self.sync_table_filter.get().strip()
        table_name = self._resolve_sync_table_name(raw_value)
        if table_name is None:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn table có trong danh sách table nguồn.")
            return
        if table_name not in self.sync_selected_tables:
            self.sync_selected_tables.append(table_name)
        self.sync_table_filter.set("")
        self._refresh_sync_selected_table_list()
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _add_filtered_sync_tables(self) -> None:
        if self.sync_all_tables.get() or not self.sync_filtered_tables:
            return
        for table_name in self.sync_filtered_tables:
            if table_name not in self.sync_selected_tables:
                self.sync_selected_tables.append(table_name)
        self.sync_table_filter.set("")
        self._refresh_sync_selected_table_list()
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _resolve_sync_table_name(self, raw_value: str) -> str | None:
        if not raw_value:
            return self.sync_filtered_tables[0] if self.sync_filtered_tables else None

        for table_name in self.sync_source_tables:
            if table_name == raw_value:
                return table_name
        matches = [table_name for table_name in self.sync_source_tables if raw_value.casefold() in table_name.casefold()]
        if len(matches) == 1:
            return matches[0]
        return None

    def _remove_selected_sync_tables(self) -> None:
        selected_indexes = list(self.sync_selected_table_listbox.curselection())
        if not selected_indexes:
            return
        for index in reversed(selected_indexes):
            del self.sync_selected_tables[index]
        self._refresh_sync_selected_table_list()
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _clear_sync_tables(self) -> None:
        self.sync_selected_tables = []
        self._refresh_sync_selected_table_list()
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _refresh_sync_selected_table_list(self) -> None:
        if not hasattr(self, "sync_selected_table_listbox"):
            return
        self.sync_selected_table_listbox.delete(0, "end")
        for table_name in self.sync_selected_tables:
            self.sync_selected_table_listbox.insert("end", table_name)

    def _on_sync_all_tables_changed(self) -> None:
        self._refresh_sync_table_combo_values()
        self._refresh_sync_button_state()

    def _selected_sync_tables(self) -> list[str]:
        if self.sync_all_tables.get():
            return list(self.sync_source_tables)
        return list(self.sync_selected_tables)

    def _set_actions_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.compare_button.configure(state=state)
        self.folder_compare_button.configure(state=state)
        self.copy_button.configure(state=state)
        self.test_db_button.configure(state=state)
        for button in self.utility_buttons:
            button.configure(state=state)
        for button in self.sync_control_buttons:
            button.configure(state=state)
        if busy:
            for button in self.db_action_buttons:
                button.configure(state="disabled")
        else:
            self._refresh_db_button_state()
            self._refresh_sync_button_state()

    def _refresh_db_button_state(self) -> None:
        if not self.db_action_buttons:
            return
        state = "normal" if self.db_verified else "disabled"
        for button in self.db_action_buttons:
            button.configure(state=state)

    def _refresh_sync_button_state(self) -> None:
        if not hasattr(self, "sync_run_button"):
            return

        for role in ("source", "target"):
            for key in ("load_button", "test_button"):
                widget = self.sync_db_widgets[role].get(key)
                if widget is not None:
                    widget.configure(state="normal")

        has_source_tables = bool(self.sync_source_tables)
        use_all_tables = self.sync_all_tables.get()
        table_pick_state = "normal" if has_source_tables and not use_all_tables else "disabled"
        self.sync_table_combo.configure(state=table_pick_state)
        self.sync_add_table_button.configure(state=table_pick_state)
        filtered_state = "normal" if self.sync_filtered_tables and not use_all_tables else "disabled"
        self.sync_add_filtered_button.configure(state=filtered_state)
        list_state = "normal" if not use_all_tables else "disabled"
        self.sync_selected_table_listbox.configure(state=list_state)

        selected_state = "normal" if self.sync_selected_tables and not use_all_tables else "disabled"
        self.sync_remove_table_button.configure(state=selected_state)
        self.sync_clear_tables_button.configure(state=selected_state)

        can_sync = (
            self.sync_db_vars["source"]["verified"].get()
            and self.sync_db_vars["target"]["verified"].get()
            and bool(self._selected_sync_tables())
        )
        self.sync_run_button.configure(state="normal" if can_sync else "disabled")

    def _mark_db_unverified(self, *_args) -> None:
        self.db_verified = False
        self._refresh_db_button_state()

    def _bind_db_change_handlers(self) -> None:
        self.db_type.trace_add("write", self._on_db_type_changed)
        for variable in (
            self.db_driver,
            self.db_server,
            self.db_port,
            self.db_database,
            self.db_username,
            self.db_password,
            self.db_schema,
        ):
            variable.trace_add("write", self._mark_db_unverified)
        for role, vars_by_name in self.sync_db_vars.items():
            vars_by_name["type"].trace_add("write", lambda *_args, key=role: self._on_sync_db_type_changed(key))
            for variable_name in (
                "driver",
                "server",
                "port",
                "database",
                "username",
                "password",
                "schema",
            ):
                vars_by_name[variable_name].trace_add(
                    "write",
                    lambda *_args, key=role: self._mark_sync_db_unverified(key),
                )
        self.sync_table_filter.trace_add("write", lambda *_args: self._refresh_sync_table_combo_values())

    def _on_db_type_changed(self, *_args) -> None:
        try:
            port = default_port(self.db_type.get())
            schema = default_schema(self.db_type.get())
        except ValueError:
            port = ""
            schema = ""

        if port:
            self.db_port.set(port)
        if schema or self.db_schema.get().strip() in {"", "dbo", "public"}:
            self.db_schema.set(schema)
        self._sync_db_type_fields()
        self._mark_db_unverified()

    def _mark_sync_db_unverified(self, role: str) -> None:
        vars_by_name = self.sync_db_vars[role]
        if not vars_by_name["verified"].get() and (role != "source" or not self.sync_source_tables):
            self._refresh_sync_button_state()
            return
        vars_by_name["verified"].set(False)
        if role == "source":
            self._set_sync_source_tables([])
        self._refresh_sync_button_state()

    def _on_sync_db_type_changed(self, role: str) -> None:
        vars_by_name = self.sync_db_vars[role]
        try:
            port = default_port(vars_by_name["type"].get())
            schema = default_schema(vars_by_name["type"].get())
        except ValueError:
            port = ""
            schema = ""

        if port:
            vars_by_name["port"].set(port)
        if schema or vars_by_name["schema"].get().strip() in {"", "dbo", "public"}:
            vars_by_name["schema"].set(schema)
        self._sync_sync_db_type_fields(role)
        self._mark_sync_db_unverified(role)

    def _sync_db_type_fields(self) -> None:
        is_sql_server = self.db_type.get() == "SQL Server"
        driver_state = "normal" if is_sql_server else "disabled"
        trusted_state = "normal" if is_sql_server else "disabled"
        self.db_driver_box.configure(state=driver_state)
        self.trusted_check.configure(state=trusted_state)
        if not is_sql_server:
            self.db_trusted.set(False)
        self._sync_auth_fields()

    def _sync_auth_fields(self) -> None:
        auth_state = "disabled" if self.db_type.get() == "SQL Server" and self.db_trusted.get() else "normal"
        self.user_entry.configure(state=auth_state)
        self.password_entry.configure(state=auth_state)
        self._mark_db_unverified()

    def _sync_sync_db_type_fields(self, role: str) -> None:
        vars_by_name = self.sync_db_vars[role]
        widgets = self.sync_db_widgets[role]
        is_sql_server = vars_by_name["type"].get() == "SQL Server"
        driver_state = "normal" if is_sql_server else "disabled"
        trusted_state = "normal" if is_sql_server else "disabled"
        driver_box = widgets.get("driver_box")
        trusted_check = widgets.get("trusted_check")
        if driver_box is not None:
            driver_box.configure(state=driver_state)
        if trusted_check is not None:
            trusted_check.configure(state=trusted_state)
        if not is_sql_server:
            vars_by_name["trusted"].set(False)
        self._sync_sync_auth_fields(role)

    def _sync_sync_auth_fields(self, role: str) -> None:
        vars_by_name = self.sync_db_vars[role]
        widgets = self.sync_db_widgets[role]
        auth_state = "disabled" if vars_by_name["type"].get() == "SQL Server" and vars_by_name["trusted"].get() else "normal"
        user_entry = widgets.get("user_entry")
        password_entry = widgets.get("password_entry")
        if user_entry is not None:
            user_entry.configure(state=auth_state)
        if password_entry is not None:
            password_entry.configure(state=auth_state)
        self._mark_sync_db_unverified(role)

    def _refresh_folder_compare_default_output(self) -> None:
        if self.folder_compare_output_path.get().strip():
            return
        base_dir = self.folder_compare_right_path.get().strip() or self.folder_compare_left_path.get().strip()
        if not base_dir:
            return
        self.folder_compare_output_path.set(str(Path(base_dir) / self.app_config.workbooks.folder_compare_file))

    def _utility_root_value(self) -> str | None:
        root = self.utility_root_path.get().strip()
        if not root:
            messagebox.showerror(APP_TITLE, "Vui lòng chọn folder thao tác.")
            return None
        return root

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
            ("Tên folder/case", 18, 130),
            ("File Excel", 28, 200),
            ("Tên sheet", 18, 140),
            ("Tên cột", 22, 160),
            ("Giá trị bên trái", 32, 240),
            ("Giá trị bên phải", 32, 240),
            ("STT record", 12, 100),
            ("Ghi chú", 28, 240),
        ]
        for column_index, (title, width, min_width) in enumerate(columns):
            self.fixme_table_frame.columnconfigure(
                column_index,
                minsize=min_width,
                weight=1 if column_index in {4, 5, 7} else 0,
            )
            label = ttk.Label(
                self.fixme_table_frame,
                text=title,
                width=width,
                anchor="w",
                style="FixmeHeader.TLabel",
            )
            label.grid(row=0, column=column_index, sticky="ew", padx=1, pady=(0, 4))

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
