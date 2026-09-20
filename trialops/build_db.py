"""Load CDISC SDTM/ADaM transport files (.xpt) into a relational SQLite database.

Source data: the CDISC Pilot 01 study (CDISCPILOT01), a public, anonymised
Phase 2 trial of xanomeline vs placebo in mild-to-moderate Alzheimer's disease,
published by PHUSE for testing clinical data tools.

SDTM domains used:
    DM   - demographics (one row per subject, incl. screen failures)
    DS   - disposition (completed / discontinued and why)
    SV   - subject visits (actual visit dates)
    AE   - adverse events
    EX   - exposure (dosing)
ADaM dataset used:
    ADSL - subject-level analysis dataset (baseline characteristics, flags)

Usage:
    python -m trialops.build_db
"""

from pathlib import Path
import sqlite3

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "trialops.db"

DOMAINS = ["dm", "ds", "sv", "ae", "ex", "adsl"]

# ADaM stores dates as SAS numeric dates (days since 1960-01-01)
SAS_DATE_COLS = {"adsl": ["TRTSDT", "TRTEDT", "VISIT1DT", "DISONSDT", "RFENDT"]}


def read_xpt(path: Path) -> pd.DataFrame:
    """Read a SAS transport file and tidy it for SQL."""
    df = pd.read_sas(path, format="xport", encoding="latin1")
    # SAS stores missing character values as empty strings -> make them real NULLs
    obj_cols = df.select_dtypes(include=["object", "string"]).columns
    df[obj_cols] = df[obj_cols].apply(lambda s: s.str.strip()).replace("", None)
    return df


def convert_sas_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = (
                pd.to_datetime(df[col], unit="D", origin="1960-01-01")
                .dt.strftime("%Y-%m-%d")
            )
    return df


def build(db_path: Path = DB_PATH, raw_dir: Path = RAW_DIR) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        for name in DOMAINS:
            df = read_xpt(raw_dir / f"{name}.xpt")
            df = convert_sas_dates(df, SAS_DATE_COLS.get(name, []))
            df.to_sql(name, con, if_exists="replace", index=False)
            print(f"  loaded {name:<5} {len(df):>6,} rows x {df.shape[1]} cols")

        # Indexes on the join keys used throughout the analysis
        for name in DOMAINS:
            con.execute(f"CREATE INDEX IF NOT EXISTS ix_{name}_usubjid ON {name}(USUBJID)")
        con.commit()
    return db_path


if __name__ == "__main__":
    print(f"Building {DB_PATH.relative_to(ROOT)} ...")
    build()
    print("Done.")
