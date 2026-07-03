# 电芯电压与温度分析项目

本项目用于分析已解压的录播数据文件夹，生成电压/温度分析图片，并分别汇总为 PPT 报告。

## 目录说明

- `data/raw/`：默认输入目录，可放置已解压后的录播数据文件夹。
- `data/processed/`：保留中间数据目录。
- `output/voltage_images/`：存放生成的电压分析图片。
- `output/temperature_images/`：存放生成的温度分析图片。
- `src/`：存放 Python 源代码。

## 整体流程

1. 读取用户选择的已解压录播数据文件夹。
2. 按 RBMS/TMS 目录结构查找指定日期、所选日期或全部日期的数据。
3. 读取并清洗需要的字段。
4. 按配置生成电压分析图或温度分析图。
5. 将生成的图片汇总为对应的 PPT 报告。

输入路径必须是已解压后的文件夹，程序不再负责解压压缩文件。文件夹内需要包含类似 `*.RBMS101`、`*.RBMS301` 的 RBMS 数据目录。

## 环境准备

建议使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

如果在 VS Code 中运行，请选择解释器：

```text
.\.venv\Scripts\python.exe
```

## 电压分析

运行指定日期的电压分析：

```powershell
python src/main.py --analysis-type voltage --date 20260105 --raw-input-path "C:\path\to\extracted_recording"
```

`--date` 支持 `YYYYMMDD` 或 `YYYY-MM-DD` 格式。如果不填写 `--date`，会自动分析所有 RBMS 日期文件夹：

```powershell
python src/main.py --analysis-type voltage --raw-input-path "C:\path\to\extracted_recording"
```

默认电芯电压测点数量为 `416`。如需调整：

```powershell
python src/main.py --analysis-type voltage --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --cell-count 416
```

电压分析当前只生成 `selected_cell_voltage_soc` 图。该图包含：

- 最高电压时刻的 Top 10 电芯趋势。
- 最低电压时刻的 Bottom 10 电芯趋势。
- 电压图下方的 `RB.A` 和 `RB.SoC` 子图，时间轴与电压图对齐。
- 右侧最高/最低电压时刻的全电芯散点图。
- 右侧最高/最低电芯编号与电压表。
- 右侧静置点 OCV-SOC 表。

静置 OCV 点默认判定条件：

- `abs(RB.A) < 5A`
- 连续持续时间 `>= 1h`
- 最高单体电压 `<= 3.3V`

如需调整静置点判定条件：

```powershell
python src/main.py --analysis-type voltage --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --rest-current-threshold 5 --rest-max-voltage 3.3 --rest-duration-hours 1
```

OCV-SOC 查表目前支持电芯类型 `135`、`280`、`305`、`315`。默认使用 `dch` 的 OCV 表：

```powershell
python src/main.py --analysis-type voltage --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --soc-cell-type 305 --soc-cal-type dch
```

## 温度分析

运行指定日期的温度分析：

```powershell
python src/main.py --analysis-type temperature --date 20260105 --raw-input-path "C:\path\to\extracted_recording"
```

温度分析会额外使用 TMS 文件。RBMS 与 TMS 的映射规则为：

- `RBMS301` 到 `RBMS306` 映射到 `TMS301`
- `RBMS401` 到 `RBMS406` 映射到 `TMS401`

默认温度模式为 `diff`，即选择温差最大的时刻作为代表时刻。温度图包含：

- Top 5 和 Bottom 5 电芯温度趋势。
- TMS 进/出水温度趋势。
- TMS 进/出水压力趋势。
- 代表时刻的电芯温度热力图。

如需使用最高温时刻作为代表时刻：

```powershell
python src/main.py --analysis-type temperature --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --temperature-mode max
```

默认电芯温度测点数量为 `256`。如需调整：

```powershell
python src/main.py --analysis-type temperature --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --temperature-cell-count 256
```

## 同时运行电压和温度分析

```powershell
python src/main.py --analysis-type all --date 20260105 --raw-input-path "C:\path\to\extracted_recording"
```

## 图形化界面

项目默认提供独立桌面图形界面，不需要通过浏览器打开。

启动桌面界面：

```powershell
python src/gui_desktop.py
```

桌面图形界面支持：

- 选择分析类型：电压、温度、电压 + 温度。
- 选择已解压录播数据文件夹后自动读取可用日期。
- 支持日期多选和全选日期。
- 设置电压测点数量、温度测点数量、温度代表时刻模式。
- 设置 OCV-SOC 电芯类型、OCV 表方向。
- 设置静置点判断阈值。
- 填写或选择输入路径：必须是已解压后的数据文件夹。
- 拖拽已解压数据文件夹到输入区域。
- 指定输出目录。
- 在右侧查看运行日志和输出文件路径。

`src/main.py` 是命令行入口，不会打开图形界面。命令行同样支持自定义输入与输出路径：

```powershell
python src/main.py --analysis-type all --date 20260105 --raw-input-path "C:\path\to\extracted_recording" --output-dir "C:\path\to\output"
```

## 输出结果

电压分析输出：

- 图片目录：`output/voltage_images/`
- PPT 示例：`output/voltage_report_20260105.pptx`

温度分析输出：

- 图片目录：`output/temperature_images/`
- PPT 示例：`output/temperature_report_20260105_diff.pptx`
