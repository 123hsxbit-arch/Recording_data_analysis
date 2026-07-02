import pandas as pd


def clean_recording_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardize raw recording data."""
    cleaned = df.copy()
    cleaned.columns = [str(column).strip() for column in cleaned.columns]
    return cleaned

