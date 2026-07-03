from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from archive_utils import discover_recording_dates
from analysis_runner import AnalysisRunConfig, run_analysis
from config import (
    DEFAULT_CELL_TEMPERATURE_COUNT,
    DEFAULT_CELL_VOLTAGE_COUNT,
    DEFAULT_REST_CURRENT_THRESHOLD_A,
    DEFAULT_REST_DURATION_HOURS,
    DEFAULT_REST_MAX_VOLTAGE,
    DEFAULT_SOC_CAL_TYPE,
    DEFAULT_SOC_CELL_TYPE,
    DEFAULT_TEMPERATURE_MODE,
    OUTPUT_DIR,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False


class DesktopAnalysisApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        self.analysis_type = tk.StringVar(value="voltage")
        self.available_dates: list[str] = []
        self.select_all_dates = tk.BooleanVar(value=True)
        self.date_status = tk.StringVar(value="选择数据文件夹后读取日期")
        self.raw_input_path = tk.StringVar(value=str(RAW_DATA_DIR))
        self.output_dir = tk.StringVar(value=str(OUTPUT_DIR))
        self.cell_count = tk.StringVar(value=str(DEFAULT_CELL_VOLTAGE_COUNT))
        self.temperature_cell_count = tk.StringVar(value=str(DEFAULT_CELL_TEMPERATURE_COUNT))
        self.temperature_mode = tk.StringVar(value=DEFAULT_TEMPERATURE_MODE)
        self.soc_cell_type = tk.StringVar(value=str(DEFAULT_SOC_CELL_TYPE))
        self.soc_cal_type = tk.StringVar(value=DEFAULT_SOC_CAL_TYPE)
        self.rest_current_threshold = tk.StringVar(value=str(DEFAULT_REST_CURRENT_THRESHOLD_A))
        self.rest_max_voltage = tk.StringVar(value=str(DEFAULT_REST_MAX_VOLTAGE))
        self.rest_duration_hours = tk.StringVar(value=str(DEFAULT_REST_DURATION_HOURS))
        self.status = tk.StringVar(value="空闲")
        self.date_listbox: tk.Listbox | None = None

        self._configure_root()
        self._build_widgets()
        self._setup_drag_drop()
        self._poll_log_queue()

    def _configure_root(self) -> None:
        self.root.title("电芯电压/温度分析工具")
        self.root.geometry("1180x820")
        self.root.minsize(980, 720)

        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei", 14, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Microsoft YaHei", 10, "bold"))
        style.configure("Run.TButton", font=("Microsoft YaHei", 10, "bold"))

    def _build_widgets(self) -> None:
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        self.root.rowconfigure(1, weight=1)

        title = ttk.Label(self.root, text="电芯电压/温度分析工具", style="Title.TLabel")
        title.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(12, 6))

        left = ttk.Frame(self.root)
        left.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=(0, 14))
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(self.root)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 14), pady=(0, 14))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._build_path_section(left)
        self._build_parameter_section(left)
        self._build_action_section(left)
        self._build_log_section(right)

    def _build_path_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="输入与输出", style="Section.TLabelframe")
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="输入路径").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        ttk.Entry(frame, textvariable=self.raw_input_path).grid(row=0, column=1, sticky="ew", padx=8, pady=(10, 4))
        ttk.Button(frame, text="选择文件夹", command=self._choose_input_folder).grid(
            row=0, column=2, columnspan=2, sticky="ew", padx=(0, 10), pady=(10, 4)
        )

        ttk.Label(frame, text="输出位置").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        ttk.Entry(frame, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(frame, text="选择输出", command=self._choose_output_dir).grid(
            row=1, column=2, columnspan=2, sticky="ew", padx=(0, 10), pady=4
        )

        self.drop_label = tk.Label(
            frame,
            text="可将已解压数据文件夹拖到这里\n也可以使用上方按钮选择路径",
            height=4,
            bg="#f8fafc",
            fg="#475569",
            relief="ridge",
            bd=1,
            font=("Microsoft YaHei", 9),
        )
        self.drop_label.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(8, 10))

    def _build_parameter_section(self, parent: ttk.Frame) -> None:
        self._build_common_parameter_section(parent)
        self._build_voltage_parameter_section(parent)
        self._build_temperature_parameter_section(parent)

    def _build_common_parameter_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="分析类型", style="Section.TLabelframe")
        frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            frame.columnconfigure(column, weight=1)

        self._add_combo(
            frame,
            row=0,
            column=0,
            label="分析类型",
            variable=self.analysis_type,
            values=[("电压", "voltage"), ("温度", "temperature"), ("电压 + 温度", "all")],
        )

        ttk.Checkbutton(
            frame,
            text="全选日期",
            variable=self.select_all_dates,
            command=self._toggle_all_dates,
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(8, 2))
        ttk.Label(frame, textvariable=self.date_status).grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=(8, 2))

        self.date_listbox = tk.Listbox(
            frame,
            selectmode=tk.EXTENDED,
            height=5,
            exportselection=False,
            font=("Consolas", 9),
        )
        self.date_listbox.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(4, 10))
        self.date_listbox.bind("<<ListboxSelect>>", self._on_date_select)

    def _build_voltage_parameter_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="电压参数", style="Section.TLabelframe")
        frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            frame.columnconfigure(column, weight=1)

        self._add_entry(frame, 0, 0, "电压测点数量", self.cell_count)
        self._add_combo(
            frame,
            row=0,
            column=2,
            label="SOC电芯类型",
            variable=self.soc_cell_type,
            values=[("305", "305"), ("315", "315"), ("280", "280"), ("135", "135")],
        )
        self._add_combo(
            frame,
            row=1,
            column=0,
            label="OCV表方向",
            variable=self.soc_cal_type,
            values=[("dch", "dch"), ("ch", "ch")],
        )
        self._add_entry(frame, 1, 2, "静置电流阈值A", self.rest_current_threshold)
        self._add_entry(frame, 2, 0, "静置最高电压", self.rest_max_voltage)
        self._add_entry(frame, 2, 2, "静置持续时间h", self.rest_duration_hours)

    def _build_temperature_parameter_section(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="温度参数", style="Section.TLabelframe")
        frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            frame.columnconfigure(column, weight=1)

        self._add_entry(frame, 0, 0, "温度测点数量", self.temperature_cell_count)
        self._add_combo(
            frame,
            row=0,
            column=2,
            label="温度代表时刻",
            variable=self.temperature_mode,
            values=[("温差最大", "diff"), ("最高温", "max")],
        )

    def _build_action_section(self, parent: ttk.Frame) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=4, column=0, sticky="ew")
        frame.columnconfigure(2, weight=1)

        self.run_button = ttk.Button(frame, text="开始分析", style="Run.TButton", command=self._start_run)
        self.run_button.grid(row=0, column=0, sticky="w", padx=(0, 8))

        ttk.Button(frame, text="清空日志", command=self._clear_log).grid(row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(frame, textvariable=self.status).grid(row=0, column=2, sticky="e")

    def _build_log_section(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="运行日志", style="Title.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap=tk.WORD,
            height=28,
            font=("Consolas", 9),
            bg="#0f172a",
            fg="#d1fae5",
            insertbackground="#d1fae5",
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")

    def _add_entry(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=10, pady=(8, 2))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=(8, 2))

    def _add_combo(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        values: list[tuple[str, str]],
    ) -> None:
        labels = [display for display, _value in values]
        mapping = {display: value for display, value in values}
        reverse_mapping = {value: display for display, value in values}
        display_var = tk.StringVar(value=reverse_mapping.get(variable.get(), labels[0]))

        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=10, pady=(8, 2))
        combo = ttk.Combobox(parent, textvariable=display_var, values=labels, state="readonly")
        combo.grid(row=row, column=column + 1, sticky="ew", padx=(0, 10), pady=(8, 2))

        def update_value(_event: tk.Event | None = None) -> None:
            variable.set(mapping[display_var.get()])

        combo.bind("<<ComboboxSelected>>", update_value)
        update_value()

    def _setup_drag_drop(self) -> None:
        if not DND_AVAILABLE or DND_FILES is None:
            self.drop_label.configure(text="拖拽依赖 tkinterdnd2 未安装；仍可使用按钮选择文件夹")
            return

        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self._handle_drop)
        self.drop_label.configure(text="将已解压数据文件夹拖到这里")

    def _handle_drop(self, event: tk.Event) -> None:
        paths = self.root.tk.splitlist(event.data)
        if not paths:
            return
        self._set_input_path(paths[0])
        self._append_log(f"已选择输入路径：{self.raw_input_path.get()}")

    def _choose_input_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择已解压数据文件夹")
        if selected:
            self._set_input_path(selected)

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="选择输出位置")
        if selected:
            self.output_dir.set(selected)

    def _start_run(self) -> None:
        if self.running:
            return

        try:
            config = self._build_config()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.running = True
        self.run_button.configure(state=tk.DISABLED)
        self.status.set("运行中...")
        self._append_log("开始分析任务。")

        thread = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        thread.start()

    def _build_config(self) -> AnalysisRunConfig:
        raw_path = Path(self.raw_input_path.get().strip())
        output_path = Path(self.output_dir.get().strip())
        if not raw_path.exists():
            raise ValueError(f"输入路径不存在：{raw_path}")
        if not output_path:
            raise ValueError("输出位置不能为空。")

        selected_dates = self._get_selected_dates()
        try:
            return AnalysisRunConfig(
                analysis_type=self.analysis_type.get(),
                dates=selected_dates,
                raw_input_path=raw_path,
                output_dir=output_path,
                work_dir=PROCESSED_DATA_DIR,
                cell_count=int(self.cell_count.get()),
                temperature_cell_count=int(self.temperature_cell_count.get()),
                temperature_mode=self.temperature_mode.get(),
                soc_cell_type=int(self.soc_cell_type.get()),
                soc_cal_type=self.soc_cal_type.get(),
                rest_current_threshold=float(self.rest_current_threshold.get()),
                rest_max_voltage=float(self.rest_max_voltage.get()),
                rest_duration_hours=float(self.rest_duration_hours.get()),
            )
        except ValueError as exc:
            raise ValueError("数字参数格式不正确，请检查测点数量和静置阈值。") from exc

    def _set_input_path(self, selected_path: str) -> None:
        new_path = Path(selected_path).resolve()
        self.raw_input_path.set(str(new_path))
        self._load_available_dates(new_path)

    def _load_available_dates(self, input_path: Path) -> None:
        try:
            dates = discover_recording_dates(input_path)
        except Exception as exc:
            self._update_date_options([])
            self._append_log(f"读取日期失败：{exc}")
            return

        self._update_date_options(dates)
        if dates:
            self._append_log(f"已读取日期：{'、'.join(dates)}")
        else:
            self._append_log("未从输入路径中读取到 RBMS 日期目录。")

    def _update_date_options(self, dates: list[str]) -> None:
        self.available_dates = dates
        if self.date_listbox is None:
            return

        self.date_listbox.delete(0, tk.END)
        for date in dates:
            self.date_listbox.insert(tk.END, date)

        self.select_all_dates.set(True)
        self._select_all_date_items()
        if dates:
            self.date_status.set(f"已读取 {len(dates)} 个日期")
        else:
            self.date_status.set("未读取到日期，将按全部日期尝试分析")

    def _toggle_all_dates(self) -> None:
        if self.select_all_dates.get():
            self._select_all_date_items()
        elif self.date_listbox is not None:
            self.date_listbox.selection_clear(0, tk.END)

    def _select_all_date_items(self) -> None:
        if self.date_listbox is None:
            return

        self.date_listbox.selection_clear(0, tk.END)
        if self.available_dates:
            self.date_listbox.selection_set(0, tk.END)

    def _on_date_select(self, _event: tk.Event | None = None) -> None:
        if self.date_listbox is None or not self.available_dates:
            self.select_all_dates.set(True)
            return

        selected_count = len(self.date_listbox.curselection())
        self.select_all_dates.set(selected_count == len(self.available_dates))

    def _get_selected_dates(self) -> list[str] | None:
        if self.select_all_dates.get() or not self.available_dates:
            return None

        if self.date_listbox is None:
            return None

        selected_dates = [self.available_dates[index] for index in self.date_listbox.curselection()]
        if not selected_dates:
            raise ValueError("请至少选择一个日期，或勾选全选日期。")
        return selected_dates

    def _run_worker(self, config: AnalysisRunConfig) -> None:
        try:
            outputs = run_analysis(config, log=self.log_queue.put)
            self.log_queue.put("任务完成。")
            for key, value in outputs.items():
                self.log_queue.put(f"{key}: {value}")
            self.log_queue.put("__STATUS_COMPLETE__")
        except Exception as exc:
            self.log_queue.put(f"任务失败：{exc}")
            self.log_queue.put(traceback.format_exc())
            self.log_queue.put("__STATUS_ERROR__")

    def _poll_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break

            if message == "__STATUS_COMPLETE__":
                self.running = False
                self.run_button.configure(state=tk.NORMAL)
                self.status.set("完成")
            elif message == "__STATUS_ERROR__":
                self.running = False
                self.run_button.configure(state=tk.NORMAL)
                self.status.set("失败")
            else:
                self._append_log(message)

        self.root.after(150, self._poll_log_queue)

    def _append_log(self, message: str) -> None:
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)

    def _clear_log(self) -> None:
        self.log_text.delete("1.0", tk.END)


def create_root() -> tk.Tk:
    if DND_AVAILABLE and TkinterDnD is not None:
        return TkinterDnD.Tk()
    return tk.Tk()


def main() -> None:
    root = create_root()
    DesktopAnalysisApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
