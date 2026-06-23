from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .db_roundtrip import (
    DatabaseSettings,
    get_available_sql_drivers,
    process_sqlserver_roundtrip,
    test_sqlserver_connection,
)
from .processor import process_root


class AutoCompareApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AutoCompare Tool")
        self.geometry("920x680")
        self.minsize(840, 620)

        self.root_path = tk.StringVar(value=str(Path.cwd()))
        self.db_driver = tk.StringVar(value="ODBC Driver 18 for SQL Server")
        self.db_server = tk.StringVar()
        self.db_database = tk.StringVar()
        self.db_trusted = tk.BooleanVar(value=True)
        self.db_username = tk.StringVar()
        self.db_password = tk.StringVar()
        self.db_schema = tk.StringVar(value="dbo")
        self.db_verified = False

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_ui()
        self._bind_db_change_handlers()
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        path_frame = ttk.Frame(self, padding=(12, 12, 12, 6))
        path_frame.grid(row=0, column=0, sticky="ew")
        path_frame.columnconfigure(1, weight=1)

        ttk.Label(path_frame, text="Root folder").grid(row=0, column=0, sticky="w", padx=(0, 8))
        path_entry = ttk.Entry(path_frame, textvariable=self.root_path)
        path_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(path_frame, text="Browse", command=self._browse).grid(row=0, column=2)

        db_frame = ttk.LabelFrame(self, text="SQL Server", padding=(12, 8, 12, 8))
        self._build_db_ui(db_frame)
        db_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        action_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        action_frame.grid(row=2, column=0, sticky="ew")
        self.compare_button = ttk.Button(action_frame, text="Run Compare", command=self._run_compare)
        self.compare_button.pack(side="left")
        self.test_db_button = ttk.Button(action_frame, text="Test DB Login", command=self._test_db_login)
        self.test_db_button.pack(side="left", padx=(8, 0))
        self.db_roundtrip_button = ttk.Button(
            action_frame,
            text="Normalize after新 CSV",
            command=self._run_db_roundtrip,
            state="disabled",
        )
        self.db_roundtrip_button.pack(side="left", padx=(8, 0))
        self.status_label = ttk.Label(action_frame, text="Ready")
        self.status_label.pack(side="left", padx=(12, 0))

        self.log_text = scrolledtext.ScrolledText(self, wrap="word", state="disabled")
        self.log_text.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _build_db_ui(self, db_frame: ttk.LabelFrame) -> None:
        for column in (1, 3):
            db_frame.columnconfigure(column, weight=1)

        drivers = get_available_sql_drivers()
        if drivers and self.db_driver.get() not in drivers:
            self.db_driver.set(drivers[-1])

        ttk.Label(db_frame, text="Driver").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        driver_box = ttk.Combobox(db_frame, textvariable=self.db_driver, values=drivers, state="normal")
        driver_box.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Server").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_server).grid(row=0, column=3, sticky="ew", pady=2)

        ttk.Label(db_frame, text="Database").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(db_frame, textvariable=self.db_database).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Checkbutton(
            db_frame,
            text="Windows Authentication",
            variable=self.db_trusted,
            command=self._sync_auth_fields,
        ).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=2)

        schema_frame = ttk.Frame(db_frame)
        schema_frame.grid(row=1, column=3, sticky="e", pady=2)
        ttk.Label(schema_frame, text="Schema").pack(side="left", padx=(0, 8))
        ttk.Entry(schema_frame, textvariable=self.db_schema, width=16).pack(side="left")

        ttk.Label(db_frame, text="User").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        self.user_entry = ttk.Entry(db_frame, textvariable=self.db_username)
        self.user_entry.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=2)

        ttk.Label(db_frame, text="Password").grid(row=2, column=2, sticky="w", padx=(0, 8), pady=2)
        self.password_entry = ttk.Entry(db_frame, textvariable=self.db_password, show="*")
        self.password_entry.grid(row=2, column=3, sticky="ew", pady=2)

        self._sync_auth_fields()

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.root_path.get() or str(Path.cwd()))
        if folder:
            self.root_path.set(folder)

    def _run_compare(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.root_path.get().strip()
        if not root:
            messagebox.showerror("AutoCompare Tool", "Please select a root folder.")
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Running...")

        self.worker = threading.Thread(target=self._run_compare_worker, args=(root,), daemon=True)
        self.worker.start()

    def _test_db_login(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror("AutoCompare Tool", str(exc))
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Testing DB login...")

        self.worker = threading.Thread(target=self._test_db_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _run_db_roundtrip(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        root = self.root_path.get().strip()
        if not root:
            messagebox.showerror("AutoCompare Tool", "Please select a root folder.")
            return
        if not self.db_verified:
            messagebox.showerror("AutoCompare Tool", "Please test DB login successfully first.")
            return

        try:
            settings = self._get_db_settings()
        except ValueError as exc:
            messagebox.showerror("AutoCompare Tool", str(exc))
            return

        self._clear_log()
        self._set_actions_busy(True)
        self.status_label.configure(text="Normalizing CSV...")

        self.worker = threading.Thread(target=self._db_roundtrip_worker, args=(root, settings), daemon=True)
        self.worker.start()

    def _run_compare_worker(self, root: str) -> None:
        try:
            summary = process_root(root, log=self._log_from_worker)
            if summary.errors:
                self._log_from_worker("")
                self._log_from_worker("Finished with errors.")
                self.log_queue.put("__STATUS__:Finished with errors")
                self.log_queue.put("__MESSAGE_ERROR__:Finished with errors. Please check the log.")
            else:
                self._log_from_worker("")
                self._log_from_worker(f"Finished successfully. Processed {summary.processed_count} test case(s).")
                self.log_queue.put("__STATUS__:Completed")
                self.log_queue.put("__MESSAGE_INFO__:Completed successfully.")
        except Exception as exc:
            self._log_from_worker(f"ERROR: {exc}")
            self.log_queue.put("__STATUS__:Failed")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _test_db_worker(self, settings: DatabaseSettings) -> None:
        try:
            test_sqlserver_connection(settings)
            self._log_from_worker("DB login succeeded.")
            self.log_queue.put("__DB_VERIFIED__:1")
            self.log_queue.put("__STATUS__:DB login OK")
            self.log_queue.put("__MESSAGE_INFO__:DB login succeeded.")
        except Exception as exc:
            self._log_from_worker(f"DB login failed: {exc}")
            self.log_queue.put("__DB_VERIFIED__:0")
            self.log_queue.put("__STATUS__:DB login failed")
            self.log_queue.put(f"__MESSAGE_ERROR__:DB login failed: {exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _db_roundtrip_worker(self, root: str, settings: DatabaseSettings) -> None:
        try:
            summary = process_sqlserver_roundtrip(root, settings, log=self._log_from_worker)
            if summary.errors:
                self._log_from_worker("")
                self._log_from_worker("DB column-order normalization finished with errors.")
                self.log_queue.put("__STATUS__:Finished with errors")
                self.log_queue.put(
                    "__MESSAGE_ERROR__:DB column-order normalization finished with errors. Please check the log."
                )
            else:
                self._log_from_worker("")
                self._log_from_worker(f"CSV normalization completed. Processed {summary.csv_count} CSV file(s).")
                self.log_queue.put("__STATUS__:CSV normalization completed")
                self.log_queue.put("__MESSAGE_INFO__:CSV normalization completed successfully.")
        except Exception as exc:
            self._log_from_worker(f"ERROR: {exc}")
            self.log_queue.put("__STATUS__:Failed")
            self.log_queue.put(f"__MESSAGE_ERROR__:{exc}")
        finally:
            self.log_queue.put("__ENABLE_ACTIONS__")

    def _log_from_worker(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__ENABLE_ACTIONS__":
                    self._set_actions_busy(False)
                elif message.startswith("__DB_VERIFIED__:"):
                    self.db_verified = message.split(":", 1)[1] == "1"
                    self._refresh_db_button_state()
                elif message.startswith("__STATUS__:"):
                    self.status_label.configure(text=message.split(":", 1)[1])
                elif message.startswith("__MESSAGE_ERROR__:"):
                    messagebox.showerror("AutoCompare Tool", message.split(":", 1)[1])
                elif message.startswith("__MESSAGE_INFO__:"):
                    messagebox.showinfo("AutoCompare Tool", message.split(":", 1)[1])
                else:
                    self._append_log(message)
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
            raise ValueError("Please enter an ODBC driver.")
        if not server:
            raise ValueError("Please enter SQL Server name.")
        if not database:
            raise ValueError("Please enter database name.")
        if not self.db_trusted.get() and not self.db_username.get().strip():
            raise ValueError("Please enter username or use Windows Authentication.")

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


def main() -> None:
    app = AutoCompareApp()
    app.mainloop()
