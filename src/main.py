import argparse
from pathlib import Path

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


def main() -> None:
    args = parse_args()
    config = AnalysisRunConfig(
        analysis_type=args.analysis_type,
        date=args.date,
        raw_input_path=Path(args.raw_input_path),
        output_dir=Path(args.output_dir),
        work_dir=Path(args.work_dir),
        cell_count=args.cell_count,
        temperature_cell_count=args.temperature_cell_count,
        temperature_mode=args.temperature_mode,
        soc_cell_type=args.soc_cell_type,
        soc_cal_type=args.soc_cal_type,
        rest_current_threshold=args.rest_current_threshold,
        rest_max_voltage=args.rest_max_voltage,
        rest_duration_hours=args.rest_duration_hours,
    )
    run_analysis(config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 RBMS 电压和温度分析图。")
    parser.add_argument(
        "--analysis-type",
        choices=["voltage", "temperature", "all"],
        default="voltage",
        help="分析类型。默认：voltage。",
    )
    parser.add_argument(
        "--date",
        required=False,
        default=None,
        help="分析日期，例如 20260105 或 2026-01-05。不填写则分析全部 RBMS 日期。",
    )
    parser.add_argument(
        "--raw-input-path",
        default=str(RAW_DATA_DIR),
        help="输入路径，可为包含 zip 的目录、已解压目录或单个 zip 文件。",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="输出目录。默认使用项目 output 目录。",
    )
    parser.add_argument(
        "--work-dir",
        default=str(PROCESSED_DATA_DIR),
        help="中间数据目录。默认使用 data/processed。",
    )
    parser.add_argument(
        "--cell-count",
        type=int,
        default=DEFAULT_CELL_VOLTAGE_COUNT,
        help=f"电压测点数量。默认：{DEFAULT_CELL_VOLTAGE_COUNT}。",
    )
    parser.add_argument(
        "--temperature-cell-count",
        type=int,
        default=DEFAULT_CELL_TEMPERATURE_COUNT,
        help=f"温度测点数量。默认：{DEFAULT_CELL_TEMPERATURE_COUNT}。",
    )
    parser.add_argument(
        "--temperature-mode",
        choices=["max", "diff"],
        default=DEFAULT_TEMPERATURE_MODE,
        help=f"温度代表时刻模式。默认：{DEFAULT_TEMPERATURE_MODE}。",
    )
    parser.add_argument(
        "--soc-cell-type",
        type=int,
        default=DEFAULT_SOC_CELL_TYPE,
        choices=[135, 280, 305, 315],
        help=f"OCV-SOC 查表电芯类型。默认：{DEFAULT_SOC_CELL_TYPE}。",
    )
    parser.add_argument(
        "--soc-cal-type",
        choices=["ch", "dch"],
        default=DEFAULT_SOC_CAL_TYPE,
        help=f"OCV 查表方向。默认：{DEFAULT_SOC_CAL_TYPE}。",
    )
    parser.add_argument(
        "--rest-current-threshold",
        type=float,
        default=DEFAULT_REST_CURRENT_THRESHOLD_A,
        help=f"静置点电流阈值，单位 A。默认：{DEFAULT_REST_CURRENT_THRESHOLD_A}。",
    )
    parser.add_argument(
        "--rest-max-voltage",
        type=float,
        default=DEFAULT_REST_MAX_VOLTAGE,
        help=f"静置点最高单体电压阈值。默认：{DEFAULT_REST_MAX_VOLTAGE}。",
    )
    parser.add_argument(
        "--rest-duration-hours",
        type=float,
        default=DEFAULT_REST_DURATION_HOURS,
        help=f"静置点连续持续时间，单位小时。默认：{DEFAULT_REST_DURATION_HOURS}。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
