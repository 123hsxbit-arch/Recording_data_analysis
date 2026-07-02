from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from archive_utils import (
    RBMS_FOLDER_PATTERN,
    extract_zip_archives,
    find_temperature_recordings,
    find_voltage_recordings,
    normalize_date,
)
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
from loader import read_csv_columns
from ppt_report import create_image_report
from preprocess import clean_recording_data
from temperature_analysis import build_temperature_columns, build_tms_columns, generate_temperature_charts
from voltage_analysis import build_voltage_columns, generate_voltage_charts


LogFn = Callable[[str], None]


@dataclass
class AnalysisRunConfig:
    analysis_type: str = "voltage"
    date: str | None = None
    raw_input_path: Path = RAW_DATA_DIR
    output_dir: Path = OUTPUT_DIR
    work_dir: Path = PROCESSED_DATA_DIR
    cell_count: int = DEFAULT_CELL_VOLTAGE_COUNT
    temperature_cell_count: int = DEFAULT_CELL_TEMPERATURE_COUNT
    temperature_mode: str = DEFAULT_TEMPERATURE_MODE
    soc_cell_type: int = DEFAULT_SOC_CELL_TYPE
    soc_cal_type: str = DEFAULT_SOC_CAL_TYPE
    rest_current_threshold: float = DEFAULT_REST_CURRENT_THRESHOLD_A
    rest_max_voltage: float = DEFAULT_REST_MAX_VOLTAGE
    rest_duration_hours: float = DEFAULT_REST_DURATION_HOURS


def run_analysis(config: AnalysisRunConfig, log: LogFn = print) -> dict[str, list[Path] | Path | None]:
    date = normalize_date(config.date)
    extracted_data_dir = prepare_input_data(config.raw_input_path, config.work_dir, log)
    result: dict[str, list[Path] | Path | None] = {
        "voltage_images": [],
        "temperature_images": [],
        "voltage_ppt": None,
        "temperature_ppt": None,
    }

    if config.analysis_type in {"voltage", "all"}:
        voltage_images, voltage_ppt = run_voltage_analysis(config, date, extracted_data_dir, log)
        result["voltage_images"] = voltage_images
        result["voltage_ppt"] = voltage_ppt

    if config.analysis_type in {"temperature", "all"}:
        temperature_images, temperature_ppt = run_temperature_analysis(config, date, extracted_data_dir, log)
        result["temperature_images"] = temperature_images
        result["temperature_ppt"] = temperature_ppt

    return result


def prepare_input_data(raw_input_path: Path, work_dir: Path, log: LogFn) -> Path:
    raw_input_path = raw_input_path.resolve()
    work_dir = work_dir.resolve()
    extracted_data_dir = work_dir / "extracted"

    if raw_input_path.is_dir() and _contains_rbms_dirs(raw_input_path):
        log(f"检测到已解压目录，直接读取：{raw_input_path}")
        return raw_input_path

    if raw_input_path.is_file() and raw_input_path.suffix.lower() == ".zip":
        upload_raw_dir = work_dir / "gui_raw_input"
        upload_raw_dir.mkdir(parents=True, exist_ok=True)
        target_zip = upload_raw_dir / raw_input_path.name
        if not target_zip.exists() or target_zip.stat().st_mtime < raw_input_path.stat().st_mtime:
            shutil.copy2(raw_input_path, target_zip)
        raw_input_path = upload_raw_dir

    if not raw_input_path.is_dir():
        raise FileNotFoundError(f"输入路径不存在或不是有效目录/zip 文件：{raw_input_path}")

    log(f"解压 zip 压缩包：{raw_input_path}")
    extract_zip_archives(raw_input_path, extracted_data_dir)
    return extracted_data_dir


def run_voltage_analysis(
    config: AnalysisRunConfig,
    date: str | None,
    extracted_data_dir: Path,
    log: LogFn,
) -> tuple[list[Path], Path | None]:
    recordings = find_voltage_recordings(extracted_data_dir, date)
    if not recordings:
        date_message = date if date is not None else "全部日期"
        log(f"未找到 {date_message} 的 RBMS 电压录播文件：{extracted_data_dir}")
        return [], None

    output_label = date if date is not None else "all_dates"
    voltage_output_dir = config.output_dir / "voltage_images" / output_label
    ppt_path = config.output_dir / f"voltage_report_{output_label}.pptx"
    selected_columns = build_voltage_columns(config.cell_count)
    voltage_images: list[Path] = []

    for recording in recordings:
        log(f"读取电压 CSV：{recording.csv_path}")
        raw_df = read_csv_columns(recording.csv_path, selected_columns)
        df = clean_recording_data(raw_df)
        voltage_images.extend(
            generate_voltage_charts(
                df=df,
                output_dir=voltage_output_dir,
                cluster_name=recording.cluster_name,
                date=recording.date,
                cell_count=config.cell_count,
                soc_cell_type=config.soc_cell_type,
                soc_cal_type=config.soc_cal_type,
                rest_current_threshold=config.rest_current_threshold,
                rest_max_voltage=config.rest_max_voltage,
                rest_duration_hours=config.rest_duration_hours,
            )
        )

    create_image_report(voltage_images, ppt_path, f"Voltage Analysis Report - {output_label}")
    log(f"电压 PPT：{ppt_path}")
    return voltage_images, ppt_path


def run_temperature_analysis(
    config: AnalysisRunConfig,
    date: str | None,
    extracted_data_dir: Path,
    log: LogFn,
) -> tuple[list[Path], Path | None]:
    recordings = find_temperature_recordings(extracted_data_dir, date)
    if not recordings:
        date_message = date if date is not None else "全部日期"
        log(f"未找到 {date_message} 的 RBMS 温度录播文件：{extracted_data_dir}")
        return [], None

    output_label = date if date is not None else "all_dates"
    temperature_output_dir = config.output_dir / "temperature_images" / output_label
    ppt_path = config.output_dir / f"temperature_report_{output_label}_{config.temperature_mode}.pptx"
    selected_columns = build_temperature_columns(config.temperature_cell_count)
    tms_columns = build_tms_columns()
    temperature_images: list[Path] = []

    for recording in recordings:
        log(f"读取温度 CSV：{recording.rbms_csv_path}")
        rbms_df = clean_recording_data(read_csv_columns(recording.rbms_csv_path, selected_columns))

        tms_df = None
        if recording.tms_csv_path is not None:
            log(f"读取映射 TMS CSV：{recording.tms_csv_path}")
            tms_df = clean_recording_data(read_csv_columns(recording.tms_csv_path, tms_columns))
        else:
            log(f"未找到映射 TMS CSV：{recording.cluster_name}，{recording.date}")

        temperature_images.extend(
            generate_temperature_charts(
                rbms_df=rbms_df,
                tms_df=tms_df,
                output_dir=temperature_output_dir,
                cluster_name=recording.cluster_name,
                tms_name=recording.tms_name,
                date=recording.date,
                cell_count=config.temperature_cell_count,
                mode=config.temperature_mode,
            )
        )

    create_image_report(
        temperature_images,
        ppt_path,
        f"Temperature Analysis Report - {output_label} - {config.temperature_mode}",
    )
    log(f"温度 PPT：{ppt_path}")
    return temperature_images, ppt_path


def _contains_rbms_dirs(path: Path) -> bool:
    return any(child.is_dir() and RBMS_FOLDER_PATTERN.match(child.name) for child in path.rglob("*"))
