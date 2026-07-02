from pathlib import Path

import pandas as pd


def read_csv_columns(file_path: Path, columns: list[str]) -> pd.DataFrame:
    """Read selected CSV columns that are present in the file."""
    wanted_columns = set(columns)
    return pd.read_csv(file_path, usecols=lambda column: column in wanted_columns)
