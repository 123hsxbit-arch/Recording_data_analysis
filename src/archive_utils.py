from __future__ import annotations

import gzip
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


RBMS_FOLDER_PATTERN = re.compile(r"^[^.]+\.[^.]+\.RBMS\d{3}$", re.IGNORECASE)
TMS_FOLDER_PATTERN = re.compile(r"^[^.]+\.[^.]+\.TMS\d{3}$", re.IGNORECASE)


@dataclass(frozen=True)
class VoltageRecording:
    cluster_name: str
    date: str
    gz_path: Path
    csv_path: Path


@dataclass(frozen=True)
class TemperatureRecording:
    cluster_name: str
    tms_name: str | None
    date: str
    rbms_csv_path: Path
    tms_csv_path: Path | None


def normalize_date(date_text: str | None) -> str | None:
    """Normalize date input to YYYYMMDD."""
    if date_text is None or str(date_text).strip() == "":
        return None

    normalized = re.sub(r"\D", "", date_text)
    if len(normalized) != 8:
        raise ValueError("Date must be YYYYMMDD or YYYY-MM-DD.")
    return normalized


def extract_zip_archives(raw_data_dir: Path, extracted_data_dir: Path) -> list[Path]:
    """Extract all zip archives under raw data directory."""
    extracted_data_dir.mkdir(parents=True, exist_ok=True)
    zip_paths = sorted(raw_data_dir.glob("*.zip"))

    for zip_path in zip_paths:
        marker_path = extracted_data_dir / f".{zip_path.stem}.extracted"
        if marker_path.exists():
            continue

        _safe_extract_zip(zip_path, extracted_data_dir)
        marker_path.touch()

    return sorted(path for path in extracted_data_dir.iterdir() if path.is_dir())


def find_voltage_recordings(extracted_data_dir: Path, date: str | None) -> list[VoltageRecording]:
    """Find RBMS gz files for the selected date, or all dates when date is None."""
    recordings: list[VoltageRecording] = []

    for cluster_dir in extracted_data_dir.rglob("*"):
        if not cluster_dir.is_dir() or not RBMS_FOLDER_PATTERN.match(cluster_dir.name):
            continue

        date_dirs = _find_date_dirs(cluster_dir, date)
        for date_dir in date_dirs:
            for gz_path in sorted(date_dir.glob("*.csv.gz")):
                csv_path = extract_gz_csv(gz_path)
                recordings.append(
                    VoltageRecording(
                        cluster_name=cluster_dir.name,
                        date=date_dir.name,
                        gz_path=gz_path,
                        csv_path=csv_path,
                    )
                )

    return recordings


def find_temperature_recordings(extracted_data_dir: Path, date: str | None) -> list[TemperatureRecording]:
    """Find RBMS recordings and their mapped TMS recordings for temperature analysis."""
    tms_index = _build_tms_index(extracted_data_dir, date)
    recordings: list[TemperatureRecording] = []

    for cluster_dir in extracted_data_dir.rglob("*"):
        if not cluster_dir.is_dir() or not RBMS_FOLDER_PATTERN.match(cluster_dir.name):
            continue

        date_dirs = _find_date_dirs(cluster_dir, date)
        for date_dir in date_dirs:
            tms_name = map_rbms_to_tms_name(cluster_dir.name)
            tms_csv_path = tms_index.get((tms_name, date_dir.name))
            for gz_path in sorted(date_dir.glob("*.csv.gz")):
                rbms_csv_path = extract_gz_csv(gz_path)
                recordings.append(
                    TemperatureRecording(
                        cluster_name=cluster_dir.name,
                        tms_name=tms_name,
                        date=date_dir.name,
                        rbms_csv_path=rbms_csv_path,
                        tms_csv_path=tms_csv_path,
                    )
                )

    return recordings


def map_rbms_to_tms_name(rbms_folder_name: str) -> str | None:
    """Map K0339.ESS85.RBMS301 to K0339.ESS85.TMS301."""
    match = re.match(r"^(?P<prefix>.+)\.RBMS(?P<number>\d{3})$", rbms_folder_name, re.IGNORECASE)
    if match is None:
        return None

    rbms_number = match.group("number")
    tms_number = f"{rbms_number[0]}01"
    return f"{match.group('prefix')}.TMS{tms_number}"


def _build_tms_index(extracted_data_dir: Path, date: str | None) -> dict[tuple[str | None, str], Path]:
    tms_index: dict[tuple[str | None, str], Path] = {}

    for tms_dir in extracted_data_dir.rglob("*"):
        if not tms_dir.is_dir() or not TMS_FOLDER_PATTERN.match(tms_dir.name):
            continue

        date_dirs = _find_date_dirs(tms_dir, date)
        for date_dir in date_dirs:
            for gz_path in sorted(date_dir.glob("*.csv.gz")):
                tms_index[(tms_dir.name, date_dir.name)] = extract_gz_csv(gz_path)
                break

    return tms_index


def _find_date_dirs(cluster_dir: Path, date: str | None) -> list[Path]:
    if date is not None:
        date_dir = cluster_dir / date
        return [date_dir] if date_dir.is_dir() else []

    return sorted(
        path
        for path in cluster_dir.iterdir()
        if path.is_dir() and re.fullmatch(r"\d{8}", path.name)
    )


def extract_gz_csv(gz_path: Path) -> Path:
    """Extract one .csv.gz file next to the gz archive."""
    csv_path = gz_path.with_suffix("")
    if csv_path.exists() and csv_path.stat().st_mtime >= gz_path.stat().st_mtime:
        return csv_path

    with gzip.open(gz_path, "rb") as source:
        with csv_path.open("wb") as target:
            shutil.copyfileobj(source, target)

    return csv_path


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    try:
        archive = zipfile.ZipFile(zip_path, metadata_encoding="gbk")
    except TypeError:
        archive = zipfile.ZipFile(zip_path)

    with archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not _is_relative_to(destination, target_dir.resolve()):
                raise ValueError(f"Unsafe path in zip archive: {member.filename}")
            archive.extract(member, target_dir)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
