from pathlib import Path

import builtins
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from soc_calculation import soc_ocv_method


TIME_COLUMN_ALIASES = ["occur_time", "occur_time_utc"]
BASE_VOLTAGE_COLUMNS = TIME_COLUMN_ALIASES + ["RB.A", "RB.SoC"]
TOP_BOTTOM_CELL_COUNT = 10
PLOT_ALPHA = 0.8


@dataclass(frozen=True)
class RestingVoltagePoint:
    timestamp: pd.Timestamp
    row_index: int
    max_voltage: float
    voltage_series: pd.Series


def build_voltage_columns(cell_count: int) -> list[str]:
    """Build required voltage analysis columns."""
    cell_columns = [f"RB.CelVolt{index:03d}" for index in range(1, cell_count + 1)]
    return BASE_VOLTAGE_COLUMNS + cell_columns


def find_cell_voltage_columns(df: pd.DataFrame, cell_count: int) -> list[str]:
    """Find configured cell voltage columns that exist in the DataFrame."""
    expected = [f"RB.CelVolt{index:03d}" for index in range(1, cell_count + 1)]
    return [column for column in expected if column in df.columns]


def prepare_voltage_dataframe(df: pd.DataFrame, cell_count: int) -> tuple[pd.DataFrame, list[str]]:
    """Prepare time and numeric voltage columns for plotting."""
    prepared = df.copy()
    time_column = _find_time_column(prepared)
    if time_column is None:
        raise ValueError(f"Missing required time column. Expected one of: {TIME_COLUMN_ALIASES}")

    if time_column != "occur_time":
        prepared = prepared.rename(columns={time_column: "occur_time"})

    prepared["occur_time"] = pd.to_datetime(prepared["occur_time"], errors="coerce")
    prepared = prepared.dropna(subset=["occur_time"]).sort_values("occur_time")

    numeric_columns = [column for column in ["RB.A", "RB.SoC"] if column in prepared.columns]
    cell_columns = find_cell_voltage_columns(prepared, cell_count)
    numeric_columns.extend(cell_columns)

    for column in numeric_columns:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    return prepared, cell_columns


def generate_voltage_charts(
    df: pd.DataFrame,
    output_dir: Path,
    cluster_name: str,
    date: str,
    cell_count: int,
    soc_cell_type: int,
    soc_cal_type: str,
    rest_current_threshold: float,
    rest_max_voltage: float,
    rest_duration_hours: float,
) -> list[Path]:
    """Generate voltage charts for one RBMS cluster."""
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared, cell_columns = prepare_voltage_dataframe(df, cell_count)
    if not cell_columns:
        print(f"No cell voltage columns found for {cluster_name}.")
        return []

    resting_point = find_resting_voltage_point(
        prepared,
        cell_columns,
        current_threshold=rest_current_threshold,
        max_voltage_threshold=rest_max_voltage,
        min_duration_hours=rest_duration_hours,
    )
    generated_paths = [
        _plot_selected_cell_voltage_soc(
            full_df=prepared,
            plot_df=prepared,
            cell_columns=cell_columns,
            output_dir=output_dir,
            cluster_name=cluster_name,
            date=date,
            resting_point=resting_point,
            soc_cell_type=soc_cell_type,
            soc_cal_type=soc_cal_type,
        ),
    ]

    return generated_paths


def find_resting_voltage_point(
    df: pd.DataFrame,
    cell_columns: list[str],
    current_threshold: float,
    max_voltage_threshold: float,
    min_duration_hours: float,
) -> RestingVoltagePoint | None:
    """Find the last frame of the first continuous resting segment."""
    if "RB.A" not in df.columns or not cell_columns:
        return None

    work = df[["occur_time", "RB.A", *cell_columns]].copy()
    work["_max_voltage"] = work[cell_columns].max(axis=1)
    work["_is_rest"] = (
        work["RB.A"].abs().lt(current_threshold)
        & work["_max_voltage"].le(max_voltage_threshold)
    )

    time_diffs = work["occur_time"].diff().dt.total_seconds().dropna()
    expected_interval_seconds = float(time_diffs[time_diffs > 0].median()) if not time_diffs.empty else 1.0
    if not np.isfinite(expected_interval_seconds) or expected_interval_seconds <= 0:
        expected_interval_seconds = 1.0

    gap_break = work["occur_time"].diff().dt.total_seconds().gt(expected_interval_seconds * 3)
    segment_id = (work["_is_rest"].ne(work["_is_rest"].shift()) | gap_break).cumsum()
    min_duration_seconds = min_duration_hours * 3600

    for _, segment in work[work["_is_rest"]].groupby(segment_id):
        first_time = segment["occur_time"].iloc[0]
        last_time = segment["occur_time"].iloc[-1]
        duration_seconds = (last_time - first_time).total_seconds() + expected_interval_seconds
        if duration_seconds >= min_duration_seconds:
            row = segment.iloc[-1]
            row_index = int(segment.index[-1])
            return RestingVoltagePoint(
                timestamp=row["occur_time"],
                row_index=row_index,
                max_voltage=float(row["_max_voltage"]),
                voltage_series=df.loc[row_index, cell_columns],
            )

    return None


def _find_time_column(df: pd.DataFrame) -> str | None:
    for column in TIME_COLUMN_ALIASES:
        if column in df.columns:
            return column
    return None


def _plot_selected_cell_voltage_soc(
    full_df: pd.DataFrame,
    plot_df: pd.DataFrame,
    cell_columns: list[str],
    output_dir: Path,
    cluster_name: str,
    date: str,
    resting_point: RestingVoltagePoint | None,
    soc_cell_type: int,
    soc_cal_type: str,
) -> Path:
    output_path = output_dir / f"{date}_{cluster_name}_selected_cell_voltage_soc.png"
    cell_volts = full_df[cell_columns]
    max_volt_time_index = cell_volts.max(axis=1).idxmax()
    min_volt_time_index = cell_volts.min(axis=1).idxmin()
    max_volt_series = _as_series(cell_volts.loc[max_volt_time_index])
    min_volt_series = _as_series(cell_volts.loc[min_volt_time_index])

    top_cells = max_volt_series.nlargest(TOP_BOTTOM_CELL_COUNT).index.tolist()
    bottom_cells = min_volt_series.nsmallest(TOP_BOTTOM_CELL_COUNT).index.tolist()
    selected_cells = top_cells + [cell for cell in bottom_cells if cell not in top_cells]

    top_sorted_cells = max_volt_series.loc[top_cells].sort_values(ascending=True).index.tolist()
    bottom_sorted_cells = min_volt_series.loc[bottom_cells].sort_values(ascending=False).index.tolist()
    top_colors = _ranked_colors(top_sorted_cells, top_cells, 0.0, 0.5)
    bottom_colors = _ranked_colors(bottom_sorted_cells, bottom_cells, 1.0, 0.5)

    cell_to_x_position = {cell: index + 1 for index, cell in enumerate(cell_columns)}
    x_positions = range(1, len(cell_columns) + 1)

    fig = plt.figure(figsize=(22, 13), dpi=180)
    gs = fig.add_gridspec(4, 2, width_ratios=[3, 2], height_ratios=[1, 1, 0.8, 1.2])
    left_gs = gs[:, 0].subgridspec(2, 1, height_ratios=[4, 1], hspace=0.04)
    ax_left = fig.add_subplot(left_gs[0, 0])
    ax_aux = fig.add_subplot(left_gs[1, 0], sharex=ax_left)

    for cell in top_sorted_cells:
        ax_left.plot(
            plot_df["occur_time"],
            plot_df[cell],
            color=top_colors[cell],
            linewidth=2,
            alpha=1,
            linestyle="-",
        )

    for cell in bottom_sorted_cells:
        ax_left.plot(
            plot_df["occur_time"],
            plot_df[cell],
            color=bottom_colors[cell],
            linewidth=2,
            alpha=0.8,
            linestyle="--",
        )

    max_time = full_df.loc[max_volt_time_index, "occur_time"]
    min_time = full_df.loc[min_volt_time_index, "occur_time"]
    ax_left.axvline(x=max_time, color="red", linestyle="--", alpha=PLOT_ALPHA)
    ax_left.axvline(x=min_time, color="blue", linestyle="--", alpha=PLOT_ALPHA)

    max_cell = max_volt_series.loc[top_cells].idxmax()
    min_cell = min_volt_series.loc[bottom_cells].idxmin()
    ax_left.scatter([max_time], [max_volt_series[max_cell]], color="red", s=120, zorder=10, alpha=0.8)
    ax_left.scatter([min_time], [min_volt_series[min_cell]], color="blue", s=120, zorder=10, alpha=0.8)

    soc_result = None
    if resting_point is not None:
        ax_left.axvline(x=resting_point.timestamp, color="orange", linestyle="-.", alpha=PLOT_ALPHA)
        resting_voltages = resting_point.voltage_series.loc[selected_cells].astype(float)
        soc_result = soc_ocv_method(
            cell_type=soc_cell_type,
            voltage=resting_voltages.tolist(),
            cal_type=soc_cal_type,
        )

    ax_left.set_title(
        f"{cluster_name} Top/Bottom Cell Voltage Trend - {date}",
        fontsize=14,
        fontweight="bold",
    )
    ax_left.set_xlabel("")
    ax_left.set_ylabel("Volt (V)", fontsize=12)
    ax_left.grid(True, alpha=PLOT_ALPHA, linestyle="--")
    ax_left.tick_params(axis="x", labelbottom=False)
    _plot_current_soc_subplot(ax_aux, plot_df)

    ax_right_top = fig.add_subplot(gs[0, 1:])
    max_colors = _ordered_voltage_colors(max_volt_series, cell_columns)
    ax_right_top.scatter(
        x_positions,
        max_volt_series.loc[cell_columns].values,
        c=max_colors,
        s=30,
        marker="^",
        edgecolors="none",
        zorder=5,
    )
    top_x_positions = [cell_to_x_position[cell] for cell in top_cells]
    bottom_x_positions = [cell_to_x_position[cell] for cell in bottom_cells]
    ax_right_top.scatter(
        top_x_positions,
        max_volt_series.loc[top_cells].values,
        marker="s",
        s=60,
        facecolors="none",
        edgecolors=[top_colors[cell] for cell in top_cells],
        linewidth=1.5,
        zorder=10,
    )
    ax_right_top.scatter(
        bottom_x_positions,
        max_volt_series.loc[bottom_cells].values,
        marker="o",
        s=60,
        facecolors="none",
        edgecolors=[bottom_colors[cell] for cell in bottom_cells],
        linewidth=1.5,
        zorder=10,
    )
    ax_right_top.set_ylabel("Volt (V)", fontsize=12)
    ax_right_top.set_title(
        "Highest voltage timestamp distribution",
        fontsize=12,
        fontweight="bold",
    )
    ax_right_top.grid(True, alpha=0.3, linestyle="--", zorder=0)
    _set_cell_axis_ticks(ax_right_top, x_positions, cell_columns)

    ax_right_bottom = fig.add_subplot(gs[1, 1:])
    min_colors = _ordered_voltage_colors(min_volt_series, cell_columns)
    ax_right_bottom.scatter(
        x_positions,
        min_volt_series.loc[cell_columns].values,
        c=min_colors,
        s=30,
        marker="v",
        edgecolors="none",
        zorder=5,
    )
    ax_right_bottom.scatter(
        bottom_x_positions,
        min_volt_series.loc[bottom_cells].values,
        marker="o",
        s=60,
        facecolors="none",
        edgecolors=[bottom_colors[cell] for cell in bottom_cells],
        linewidth=1.5,
        zorder=10,
    )
    ax_right_bottom.scatter(
        top_x_positions,
        min_volt_series.loc[top_cells].values,
        marker="s",
        s=60,
        facecolors="none",
        edgecolors=[top_colors[cell] for cell in top_cells],
        linewidth=1.5,
        zorder=10,
    )
    ax_right_bottom.set_xlabel("Cell no.", fontsize=12)
    ax_right_bottom.set_ylabel("Volt (V)", fontsize=12)
    ax_right_bottom.set_title(
        "Lowest voltage timestamp distribution",
        fontsize=12,
        fontweight="bold",
    )
    ax_right_bottom.grid(True, alpha=0.3, linestyle="--", zorder=0)
    _set_cell_axis_ticks(ax_right_bottom, x_positions, cell_columns)

    legend_elements = [
        Line2D([0], [0], color="gray", lw=2, linestyle="-", label="Highest 10 cells"),
        Line2D([0], [0], color="gray", lw=2, linestyle="--", label="Lowest 10 cells"),
        Line2D([0], [0], color="red", lw=2, linestyle="--", label=f"Highest voltage: {max_time}"),
        Line2D([0], [0], color="blue", lw=2, linestyle="--", label=f"Lowest voltage: {min_time}"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="red", markersize=10, label=f"Max cell: {max_cell}"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="blue", markersize=10, label=f"Min cell: {min_cell}"),
    ]
    if resting_point is not None:
        legend_elements.append(
            Line2D(
                [0],
                [0],
                color="orange",
                lw=2,
                linestyle="-.",
                label=f"Resting OCV point: {resting_point.timestamp}",
            )
        )
    ax_left.legend(handles=legend_elements, loc="lower left", fontsize=8)

    ax_voltage_table = fig.add_subplot(gs[2, 1:])
    ax_voltage_table.axis("off")
    _draw_voltage_extreme_table(
        ax_table=ax_voltage_table,
        top_cells=top_cells,
        bottom_cells=bottom_cells,
        cell_to_x_position=cell_to_x_position,
        max_volt_series=max_volt_series,
        min_volt_series=min_volt_series,
    )

    ax_soc_table = fig.add_subplot(gs[3, 1:])
    ax_soc_table.axis("off")
    _draw_soc_table(
        ax_table=ax_soc_table,
        top_cells=top_cells,
        bottom_cells=bottom_cells,
        cell_to_x_position=cell_to_x_position,
        resting_point=resting_point,
        selected_cells=selected_cells,
        soc_result=soc_result,
        soc_cell_type=soc_cell_type,
        soc_cal_type=soc_cal_type,
    )

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _plot_current_soc_subplot(ax_aux: plt.Axes, plot_df: pd.DataFrame) -> None:
    lines = []

    if "RB.A" in plot_df.columns:
        current_line = ax_aux.plot(
            plot_df["occur_time"],
            plot_df["RB.A"],
            color="tab:blue",
            linewidth=1.0,
            alpha=0.75,
            label="RB.A",
        )[0]
        ax_aux.set_ylabel("RB.A", color="tab:blue", fontsize=11)
        ax_aux.tick_params(axis="y", colors="tab:blue", labelsize=9)
        ax_aux.spines["left"].set_color("tab:blue")
        lines.append(current_line)

    if "RB.SoC" in plot_df.columns:
        ax_soc = ax_aux.twinx()
        soc_line = ax_soc.plot(
            plot_df["occur_time"],
            plot_df["RB.SoC"],
            color="tab:green",
            linewidth=1.0,
            alpha=0.75,
            label="RB.SoC",
        )[0]
        ax_soc.set_ylabel("RB.SoC", color="tab:green", fontsize=11)
        ax_soc.tick_params(axis="y", colors="tab:green", labelsize=9)
        ax_soc.spines["right"].set_color("tab:green")
        lines.append(soc_line)

    ax_aux.set_xlabel("Timestamp", fontsize=12)
    ax_aux.grid(True, alpha=0.3, linestyle="--")
    ax_aux.set_title("Current And SoC", fontsize=11, fontweight="bold", pad=2)
    plt.setp(ax_aux.get_xticklabels(), rotation=45)

    if lines:
        ax_aux.legend(
            handles=lines,
            labels=[line.get_label() for line in lines],
            loc="upper left",
            fontsize=8,
        )
    else:
        ax_aux.text(
            0.5,
            0.5,
            "RB.A / RB.SoC not found",
            transform=ax_aux.transAxes,
            ha="center",
            va="center",
            fontsize=10,
        )


def _as_series(data: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(data, pd.DataFrame):
        return data.iloc[0]
    return data


def _ranked_colors(
    sorted_cells: list[str],
    original_cells: list[str],
    start: float,
    end: float,
) -> dict[str, tuple[float, float, float, float]]:
    position_map = {cell: index for index, cell in enumerate(sorted_cells)}
    cmap_values = plt.colormaps["Spectral"](np.linspace(start, end, len(original_cells)))
    return {cell: cmap_values[position_map[cell]] for cell in original_cells}


def _ordered_voltage_colors(
    voltage_series: pd.Series,
    cell_columns: list[str],
) -> list[tuple[float, float, float, float]]:
    sorted_cells = voltage_series.loc[cell_columns].sort_values(ascending=False).index.tolist()
    position_map = {cell: index for index, cell in enumerate(sorted_cells)}
    cmap_values = plt.colormaps["Spectral"](np.linspace(0, 1, len(cell_columns)))
    return [cmap_values[position_map[cell]] for cell in cell_columns]


def _set_cell_axis_ticks(ax: plt.Axes, x_positions: range, cell_columns: list[str]) -> None:
    ax.set_xticks(list(x_positions))
    if len(cell_columns) > 20:
        step = builtins.max(1, len(cell_columns) // 16)
        ax.set_xticks(list(x_positions)[::step])


def _draw_voltage_extreme_table(
    ax_table: plt.Axes,
    top_cells: list[str],
    bottom_cells: list[str],
    cell_to_x_position: dict[str, int],
    max_volt_series: pd.Series,
    min_volt_series: pd.Series,
) -> None:
    top_positions = [cell_to_x_position[cell] for cell in top_cells]
    bottom_positions = [cell_to_x_position[cell] for cell in bottom_cells]

    table_data = [
        ["Top 10 Index"] + [str(position) for position in top_positions],
        ["Max-Time Volt (V)"] + [f"{max_volt_series[cell]:.3f}" for cell in top_cells],
        [""] * (len(top_cells) + 1),
        ["Bottom 10 Index"] + [str(position) for position in bottom_positions],
        ["Min-Time Volt (V)"] + [f"{min_volt_series[cell]:.3f}" for cell in bottom_cells],
    ]

    table = ax_table.table(
        cellText=table_data,
        cellLoc="center",
        loc="center",
        colWidths=[0.16] + [0.075] * len(top_cells),
        bbox=[0.0, 0.05, 1.0, 0.86],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.35)

    for row in (0, 3):
        for column in range(len(table_data[row])):
            table[(row, column)].set_facecolor("#f0f0f0")

    for column in range(1, len(table_data[0])):
        table[(1, column)].set_facecolor("#ffdddd")
        table[(4, column)].set_facecolor("#ddeeff")

    ax_table.set_title("Cell voltage extreme value statistics", fontsize=11, fontweight="bold", pad=1)


def _draw_soc_table(
    ax_table: plt.Axes,
    top_cells: list[str],
    bottom_cells: list[str],
    cell_to_x_position: dict[str, int],
    resting_point: RestingVoltagePoint | None,
    selected_cells: list[str],
    soc_result: dict[str, list[float]] | None,
    soc_cell_type: int,
    soc_cal_type: str,
) -> None:
    top_positions = [cell_to_x_position[cell] for cell in top_cells]
    bottom_positions = [cell_to_x_position[cell] for cell in bottom_cells]

    if resting_point is None or soc_result is None:
        table_data = [["Resting point", "Not found: abs(RB.A) < threshold for 1h and max voltage <= threshold"]]
        table = ax_table.table(
            cellText=table_data,
            cellLoc="center",
            loc="center",
            colWidths=[0.25, 0.75],
            bbox=[0.0, 0.28, 1.0, 0.45],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1.0, 2.0)
        ax_table.set_title("OCV SOC table", fontsize=11, fontweight="bold", pad=1)
        return

    soc_map = dict(zip(selected_cells, soc_result["soc_lst"]))
    cap_map = dict(zip(selected_cells, soc_result["cap_lst"]))
    rest_voltage = resting_point.voltage_series.astype(float)

    table_data = [
        ["Top 10 Index"] + [str(position) for position in top_positions],
        ["Rest Volt (V)"] + [f"{rest_voltage[cell]:.3f}" for cell in top_cells],
        ["OCV SOC (%)"] + [_format_value(soc_map[cell], 0) for cell in top_cells],
        ["OCV Ah"] + [_format_value(cap_map[cell], 1) for cell in top_cells],
        [""] * (len(top_cells) + 1),
        ["Bottom 10 Index"] + [str(position) for position in bottom_positions],
        ["Rest Volt (V)"] + [f"{rest_voltage[cell]:.3f}" for cell in bottom_cells],
        ["OCV SOC (%)"] + [_format_value(soc_map[cell], 0) for cell in bottom_cells],
        ["OCV Ah"] + [_format_value(cap_map[cell], 1) for cell in bottom_cells],
    ]

    table = ax_table.table(
        cellText=table_data,
        cellLoc="center",
        loc="center",
        colWidths=[0.16] + [0.075] * len(top_cells),
        bbox=[0.0, 0.02, 1.0, 0.9],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.45)

    for row in (0, 5):
        for column in range(len(table_data[row])):
            table[(row, column)].set_facecolor("#f0f0f0")

    for column in range(1, len(table_data[0])):
        for row in (1, 2, 3):
            table[(row, column)].set_facecolor("#ffdddd")
        for row in (6, 7, 8):
            table[(row, column)].set_facecolor("#ddeeff")

    ax_table.set_title(
        f"Resting OCV SOC at {resting_point.timestamp} | cell_type={soc_cell_type}, cal_type={soc_cal_type}",
        fontsize=11,
        fontweight="bold",
        pad=1,
    )


def _format_value(value: float, digits: int) -> str:
    if pd.isna(value):
        return "NA"
    return f"{value:.{digits}f}"
