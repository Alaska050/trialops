"""Automated data-quality checks, modelled on the edit checks a clinical data
management team runs before database lock.

Each check is a SQL query that returns one row per issue found (a "data query"
to send to the site). Checks are declared as data, so adding a new one means
adding one entry to CHECKS - no new code.
"""

from dataclasses import dataclass
import sqlite3

import pandas as pd


@dataclass(frozen=True)
class Check:
    check_id: str
    domain: str
    severity: str        # "High" = could affect safety/primary analysis; "Medium"/"Low" otherwise
    description: str
    sql: str             # must return columns: USUBJID, SITEID, detail


CHECKS: list[Check] = [
    Check(
        "DM01", "DM", "High",
        "Informed consent date missing for a screened subject",
        """
        SELECT USUBJID, SITEID, 'RFICDTC is blank' AS detail
        FROM dm
        WHERE RFICDTC IS NULL
        """,
    ),
    Check(
        "AE01", "AE", "Medium",
        "Adverse event start date is partial (day and/or month missing)",
        """
        SELECT ae.USUBJID, dm.SITEID,
               ae.AETERM || ': start date recorded as ' || ae.AESTDTC AS detail
        FROM ae JOIN dm ON dm.USUBJID = ae.USUBJID
        WHERE length(ae.AESTDTC) < 10
        """,
    ),
    Check(
        "AE02", "AE", "High",
        "Adverse event end date is before its start date",
        """
        SELECT ae.USUBJID, dm.SITEID,
               ae.AETERM || ': ' || ae.AESTDTC || ' -> ' || ae.AEENDTC AS detail
        FROM ae JOIN dm ON dm.USUBJID = ae.USUBJID
        WHERE length(ae.AESTDTC) = 10 AND length(ae.AEENDTC) = 10
          AND ae.AEENDTC < ae.AESTDTC
        """,
    ),
    Check(
        "AE03", "AE", "Medium",
        "Adverse event started before first dose - confirm it is not medical history",
        """
        SELECT ae.USUBJID, dm.SITEID,
               ae.AETERM || ': study day ' || CAST(ae.AESTDY AS INT) AS detail
        FROM ae JOIN dm ON dm.USUBJID = ae.USUBJID
        WHERE ae.AESTDY < 1
        """,
    ),
    Check(
        "AE04", "AE", "Medium",
        "Adverse event recorded as ongoing (no end date) but outcome says recovered",
        """
        SELECT ae.USUBJID, dm.SITEID,
               ae.AETERM || ' (outcome: ' || ae.AEOUT || ')' AS detail
        FROM ae JOIN dm ON dm.USUBJID = ae.USUBJID
        WHERE ae.AEENDTC IS NULL AND ae.AEOUT LIKE 'RECOVERED%'
        """,
    ),
    Check(
        "AE05", "AE", "Medium",
        "Adverse event has an end date but outcome says not recovered/not resolved",
        """
        SELECT ae.USUBJID, dm.SITEID,
               ae.AETERM || ' ended ' || ae.AEENDTC || ' but outcome: ' || ae.AEOUT AS detail
        FROM ae JOIN dm ON dm.USUBJID = ae.USUBJID
        WHERE ae.AEENDTC IS NOT NULL AND ae.AEOUT = 'NOT RECOVERED/NOT RESOLVED'
        """,
    ),
    Check(
        "SV01", "SV", "Medium",
        "Scheduled visit dated after the subject's end of study",
        """
        SELECT sv.USUBJID, dm.SITEID,
               sv.VISIT || ' on ' || sv.SVSTDTC || ', study end ' || dm.RFPENDTC AS detail
        FROM sv JOIN dm ON dm.USUBJID = sv.USUBJID
        WHERE sv.SVSTDTC > dm.RFPENDTC
        """,
    ),
    Check(
        "SV02", "SV", "Low",
        "Visit dates out of sequence (later visit number with an earlier date)",
        """
        WITH ordered AS (
            SELECT USUBJID, VISIT, VISITNUM, SVSTDTC,
                   LAG(SVSTDTC) OVER (PARTITION BY USUBJID ORDER BY VISITNUM) AS prev_date,
                   LAG(VISIT)   OVER (PARTITION BY USUBJID ORDER BY VISITNUM) AS prev_visit
            FROM sv
        )
        SELECT o.USUBJID, dm.SITEID,
               o.VISIT || ' (' || o.SVSTDTC || ') is before ' || o.prev_visit
               || ' (' || o.prev_date || ')' AS detail
        FROM ordered o JOIN dm ON dm.USUBJID = o.USUBJID
        WHERE o.prev_date IS NOT NULL AND o.SVSTDTC < o.prev_date
        """,
    ),
    Check(
        "DS01", "DS", "High",
        "Randomised subject with no end-of-study disposition record",
        """
        SELECT a.USUBJID, a.SITEID, 'no DSCAT = DISPOSITION EVENT row' AS detail
        FROM adsl a
        WHERE NOT EXISTS (
            SELECT 1 FROM ds
            WHERE ds.USUBJID = a.USUBJID AND ds.DSCAT = 'DISPOSITION EVENT'
        )
        """,
    ),
    Check(
        "EX01", "EX", "High",
        "Randomised subject with no dosing record",
        """
        SELECT a.USUBJID, a.SITEID, 'no rows in EX' AS detail
        FROM adsl a
        WHERE NOT EXISTS (SELECT 1 FROM ex WHERE ex.USUBJID = a.USUBJID)
        """,
    ),
]


def run_checks(con: sqlite3.Connection, checks: list[Check] = CHECKS) -> pd.DataFrame:
    """Run every check and return one tidy table of open data queries."""
    frames = []
    for chk in checks:
        hits = pd.read_sql(chk.sql, con)
        if hits.empty:
            continue
        hits.insert(0, "check_id", chk.check_id)
        hits.insert(1, "severity", chk.severity)
        hits.insert(2, "domain", chk.domain)
        hits.insert(3, "description", chk.description)
        frames.append(hits)
    cols = ["check_id", "severity", "domain", "description", "USUBJID", "SITEID", "detail"]
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)[cols]


def summarise(queries: pd.DataFrame, checks: list[Check] = CHECKS) -> pd.DataFrame:
    """One row per check, including checks that passed (0 issues)."""
    counts = queries.groupby("check_id").size()
    return pd.DataFrame(
        {
            "check_id": [c.check_id for c in checks],
            "severity": [c.severity for c in checks],
            "description": [c.description for c in checks],
            "issues": [int(counts.get(c.check_id, 0)) for c in checks],
        }
    )


if __name__ == "__main__":
    from trialops.build_db import DB_PATH

    with sqlite3.connect(DB_PATH) as con:
        q = run_checks(con)
    print(summarise(q).to_string(index=False))
