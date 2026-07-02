from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MultipleLocator


TIME_COLUMN_ALIASES = ["occur_time", "occur_time_utc"]
BASE_TEMPERATURE_COLUMNS = TIME_COLUMN_ALIASES + [
    "RB.A",
    "RB.TCellDiff",
    "RB.TCellMax",
    "RB.TCellMin",
]
TMS_COLUMNS = [
    "occur_time",
    "occur_time_utc",
    "TMS.InTemp",
    "TMS.OutTemp",
    "TMS.InPress",
    "TMS.OutPress",
]
TOP_BOTTOM_TEMPERATURE_COUNT = 5


def build_temperature_columns(cell_count: int) -> list[str]:
    cell_columns = [f"RB.CelTmp{index:03d}" for index in range(1, cell_count + 1)]
    return BASE_TEMPERATURE_COLUMNS + cell_columns


def build_tms_columns() -> list[str]:
    return TMS_COLUMNS


def generate_temperature_charts(
    rbms_df: pd.DataFrame,
    tms_df: pd.DataFrame | None,
    output_dir: Path,
    cluster_name: str,
    tms_name: str | None,
    date: str,
    cell_count: int,
    mode: str,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared, cell_columns = prepare_temperature_dataframe(rbms_df, cell_count)
    if not cell_columns:
        print(f"No cell temperature columns found for {cluster_name}.")
        return []

    prepared_tms = prepare_tms_dataframe(tms_df) if tms_df is not None else None
    merged = merge_tms_data(prepared, prepared_tms)
    image_path = _plot_temperature_chart(
        df=merged,
        cell_columns=cell_columns,
        output_dir=output_dir,
        cluster_name=cluster_name,
        tms_name=tms_name,
        date=date,
        mode=mode,
    )
    return [image_path]


def prepare_temperature_dataframe(df: pd.DataFrame, cell_count: int) -> tuple[pd.DataFrame, list[str]]:
    prepared = df.copy()
    time_column = _find_time_column(prepared)
    if time_column is None:
        raise ValueError(f"Missing required time column. Expected one of: {TIME_COLUMN_ALIASES}")

    if time_column != "occur_time":
        prepared = prepared.rename(columns={time_column: "occur_time"})

    prepared["occur_time"] = pd.to_datetime(prepared["occur_time"], errors="coerce")
    prepared = prepared.dropna(subset=["occur_time"]).sort_values("occur_time").reset_index(drop=True)

    cell_columns = [f"RB.CelTmp{index:03d}" for index in range(1, cell_count + 1)]
    cell_columns = [column for column in cell_columns if column in prepared.columns]
    numeric_columns = [column for column in ["RB.A", "RB.TCellDiff", "RB.TCellMax", "RB.TCellMin"] if column in prepared.columns]
    numeric_columns.extend(cell_columns)

    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    return prepared, cell_columns


def prepare_tms_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    time_column = _find_time_column(prepared)
    if time_column is None:
        raise ValueError(f"Missing required TMS time column. Expected one of: {TIME_COLUMN_ALIASES}")

    if time_column != "occur_time":
        prepared = prepared.rename(columns={time_column: "occur_time"})

    prepared["occur_time"] = pd.to_datetime(prepared["occur_time"], errors="coerce")
    prepared = prepared.dropna(subset=["occur_time"]).sort_values("occur_time").reset_index(drop=True)

    for column in ["TMS.InTemp", "TMS.OutTemp", "TMS.InPress", "TMS.OutPress"]:
        if column in prepared.columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    return prepared


def merge_tms_data(rbms_df: pd.DataFrame, tms_df: pd.DataFrame | None) -> pd.DataFrame:
    if tms_df is None or tms_df.empty:
        return rbms_df.copy()

    tms_columns = [
        column
        for column in ["occur_time", "TMS.InTemp", "TMS.OutTemp", "TMS.InPress", "TMS.OutPress"]
        if column in tms_df.columns
    ]
    if len(tms_columns) <= 1:
        return rbms_df.copy()

    return pd.merge_asof(
        rbms_df.sort_values("occur_time"),
        tms_df[tms_columns].sort_values("occur_time"),
        on="occur_time",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=2),
    )


def _plot_temperature_chart(
    df: pd.DataFrame,
    cell_columns: list[str],
    output_dir: Path,
    cluster_name: str,
    tms_name: str | None,
    date: str,
    mode: str,
) -> Path:
    if mode not in {"max", "diff"}:
        raise ValueError("Temperature mode must be 'max' or 'diff'.")

    rep_index = _find_representative_index(df, cell_columns, mode)
    selected_cells = _select_temperature_cells(df, cell_columns, rep_index, mode)
    temp_map = build_temperature_map(df.loc[rep_index, cell_columns])
    rep_title = "Max temperature timestamp" if mode == "max" else "Max temperature-diff timestamp"

    output_path = output_dir / f"{date}_{cluster_name}_temperature_{mode}.png"

    fig = plt.figure(figsize=(16, 9), dpi=180, tight_layout=True)
    ax_temp = plt.subplot2grid((2, 3), (0, 0), colspan=2)
    ax_current = ax_temp.twinx()
    ax_tms_temp = plt.subplot2grid((2, 3), (1, 0), colspan=2, sharex=ax_temp)
    ax_tms_press = ax_tms_temp.twinx()
    ax_map = plt.subplot2grid((2, 3), (0, 2), rowspan=2)

    for column in selected_cells:
        ax_temp.plot(df["occur_time"], df[column], linewidth=0.9, label=_cell_label(column))

    if "RB.A" in df.columns:
        ax_current.plot(df["occur_time"], df["RB.A"], color="tab:green", linestyle="--", linewidth=0.8, label="RB.A")
        ax_current.set_ylabel("RB.A (A)")

    rep_time = df.loc[rep_index, "occur_time"]
    ax_temp.axvline(rep_time, color="red", linestyle="-.", linewidth=1.0)
    ax_tms_temp.axvline(rep_time, color="red", linestyle="-.", linewidth=1.0)

    ax_temp.set_title(f"{rep_title} Top5 & Bottom5 Cell Temperature", fontsize=11, fontweight="bold")
    ax_temp.set_ylabel("Cell temperature (C)")
    ax_temp.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    ax_temp.legend(loc="upper left", fontsize=7, ncol=2, title="Cells")
    if "RB.A" in df.columns:
        ax_current.legend(loc="upper right", fontsize=7)

    _plot_tms_series(ax_tms_temp, ax_tms_press, df)
    ax_tms_temp.set_title(f"TMS water temperature and pressure ({tms_name or 'TMS not found'})", fontsize=11, fontweight="bold")
    ax_tms_temp.set_xlabel("Time")
    ax_tms_temp.grid(True, linestyle="--", linewidth=0.5, alpha=0.6)
    plt.setp(ax_tms_temp.get_xticklabels(), rotation=35, ha="right")
    plt.setp(ax_temp.get_xticklabels(), visible=False)

    mesh = ax_map.pcolormesh(temp_map, cmap="hot_r", rasterized=True)
    fig.colorbar(mesh, ax=ax_map, label="Cell temperature (C)")
    ax_map.set_title(f"{rep_title} Cell Temperature Map", fontsize=11, fontweight="bold")
    ax_map.yaxis.set_major_locator(MultipleLocator(8))
    ax_map.yaxis.set_minor_locator(MultipleLocator(1))
    ax_map.grid(which="major", linewidth=1.0, color="black", alpha=0.5)
    ax_map.grid(which="minor", linewidth=0.4, color="black", alpha=0.35)
    ax_map.set_xticks(np.arange(0.5, 4.5, 1), ["Module4", "Module3", "Module2", "Module1"], rotation=0)
    ax_map.set_yticks(np.arange(4, 64, 8), [f"Pack{i}" for i in range(1, 9)], rotation=0)

    fig.suptitle(f"{cluster_name} Temperature Analysis - {date}", fontsize=13, fontweight="bold")
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _find_representative_index(df: pd.DataFrame, cell_columns: list[str], mode: str) -> int:
    if mode == "max" and "RB.TCellMax" in df.columns:
        return int(df["RB.TCellMax"].idxmax())

    if {"RB.TCellMax", "RB.TCellMin"}.issubset(df.columns):
        return int((df["RB.TCellMax"] - df["RB.TCellMin"]).idxmax())

    if mode == "max":
        return int(df[cell_columns].max(axis=1).idxmax())

    return int((df[cell_columns].max(axis=1) - df[cell_columns].min(axis=1)).idxmax())


def _select_temperature_cells(
    df: pd.DataFrame,
    cell_columns: list[str],
    rep_index: int,
    mode: str,
) -> list[str]:
    if mode == "max":
        rep_values = df.loc[rep_index, cell_columns]
        top_cells = rep_values.nlargest(TOP_BOTTOM_TEMPERATURE_COUNT).index.tolist()
        bottom_cells = rep_values.nsmallest(TOP_BOTTOM_TEMPERATURE_COUNT).index.tolist()
        return list(dict.fromkeys(top_cells + bottom_cells))

    top_cells = df[cell_columns].max(axis=0).sort_values(ascending=False).head(TOP_BOTTOM_TEMPERATURE_COUNT).index.tolist()
    remaining = [column for column in cell_columns if column not in top_cells]
    bottom_cells = df[remaining].min(axis=0).sort_values(ascending=True).head(TOP_BOTTOM_TEMPERATURE_COUNT).index.tolist()
    return list(dict.fromkeys(top_cells + bottom_cells))


def build_temperature_map(temperature_series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(temperature_series, errors="coerce").to_numpy()
    if len(values) < 256:
        values = np.pad(values, (0, 256 - len(values)), constant_values=np.nan)

    temp_map = np.full((64, 4), np.nan)
    for pack in range(8):
        for module_num in range(1, 9):
            base = pack * 32
            temp_map[pack * 8 + module_num - 1, 3] = values[base + module_num - 1]
            temp_map[pack * 8 + 8 - module_num, 2] = values[base + 8 + module_num - 1]
            temp_map[pack * 8 + module_num - 1, 1] = values[base + 16 + module_num - 1]
            temp_map[pack * 8 + 8 - module_num, 0] = values[base + 24 + module_num - 1]

    return np.around(temp_map, 0)


def _plot_tms_series(ax_temp: plt.Axes, ax_press: plt.Axes, df: pd.DataFrame) -> None:
    temp_lines = []
    press_lines = []

    if "TMS.InTemp" in df.columns:
        temp_lines.append(ax_temp.plot(df["occur_time"], df["TMS.InTemp"], color="tab:red", linewidth=0.9, label="TMS.InTemp")[0])
    if "TMS.OutTemp" in df.columns:
        temp_lines.append(ax_temp.plot(df["occur_time"], df["TMS.OutTemp"], color="tab:blue", linewidth=0.9, label="TMS.OutTemp")[0])

    if "TMS.InPress" in df.columns:
        press_lines.append(ax_press.plot(df["occur_time"], df["TMS.InPress"], color="purple", linestyle="--", linewidth=0.9, label="TMS.InPress")[0])
    if "TMS.OutPress" in df.columns:
        press_lines.append(ax_press.plot(df["occur_time"], df["TMS.OutPress"], color="black", linestyle="--", linewidth=0.9, label="TMS.OutPress")[0])

    ax_temp.set_ylabel("In/Out water temp (C)")
    ax_press.set_ylabel("In/Out water pressure")
    if temp_lines:
        ax_temp.legend(handles=temp_lines, loc="upper left", fontsize=7)
    if press_lines:
        ax_press.legend(handles=press_lines, loc="upper right", fontsize=7)

    if not temp_lines and not press_lines:
        ax_temp.text(0.5, 0.5, "No mapped TMS data", transform=ax_temp.transAxes, ha="center", va="center")


def _find_time_column(df: pd.DataFrame) -> str | None:
    for column in TIME_COLUMN_ALIASES:
        if column in df.columns:
            return column
    return None


def _cell_label(column: str) -> str:
    return column.replace("RB.CelTmp", "Cell")
