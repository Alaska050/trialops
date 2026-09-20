import sqlite3

import pandas as pd
import pytest

from trialops.build_db import build
from trialops.checks import CHECKS, Check, run_checks, summarise
from trialops.model import CATEGORICAL, NUMERIC, fit_final, load_features


@pytest.fixture(scope="session")
def con(tmp_path_factory):
    db = build(tmp_path_factory.mktemp("db") / "test.db")
    with sqlite3.connect(db) as connection:
        yield connection


def test_all_domains_loaded(con):
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["dm", "ds", "sv", "ae", "ex", "adsl"]}
    assert counts["dm"] == 306          # everyone screened
    assert counts["adsl"] == 254        # randomised subjects only


def test_blank_strings_become_null(con):
    blanks = con.execute("SELECT COUNT(*) FROM ae WHERE AEENDTC = ''").fetchone()[0]
    assert blanks == 0


def test_screened_equals_randomised_plus_screen_failures(con):
    from pathlib import Path
    sql = (Path(__file__).parents[1] / "sql" / "01_site_enrolment.sql").read_text()
    sites = pd.read_sql(sql, con)
    assert (sites.screened == sites.randomised + sites.screen_failures).all()
    assert sites.randomised.sum() == 254


def test_every_check_returns_expected_columns(con):
    queries = run_checks(con)
    assert list(queries.columns) == ["check_id", "severity", "domain", "description",
                                     "USUBJID", "SITEID", "detail"]
    assert len(summarise(queries)) == len(CHECKS)


def test_check_catches_planted_error():
    """A check must flag a deliberately bad record in a tiny in-memory database."""
    mem = sqlite3.connect(":memory:")
    mem.execute("CREATE TABLE dm (USUBJID TEXT, SITEID TEXT)")
    mem.execute("CREATE TABLE ae (USUBJID TEXT, AETERM TEXT, AESTDTC TEXT, AEENDTC TEXT)")
    mem.execute("INSERT INTO dm VALUES ('S1', '701')")
    mem.execute("INSERT INTO ae VALUES ('S1', 'HEADACHE', '2014-03-10', '2014-03-01')")
    ae02 = next(c for c in CHECKS if c.check_id == "AE02")
    result = run_checks(mem, [ae02])
    assert len(result) == 1 and result.loc[0, "USUBJID"] == "S1"


def test_model_uses_no_leaky_features():
    leaky = {"TRTDUR", "CUMDOSE", "AVGDD", "DISCONFL", "COMP24FL", "DCREASCD", "RFENDTC"}
    assert leaky.isdisjoint(NUMERIC + CATEGORICAL)


def test_model_predicts_probabilities(con):
    df = load_features(con)
    model = fit_final(df)
    p = model.predict_proba(df[NUMERIC + CATEGORICAL])[:, 1]
    assert ((p >= 0) & (p <= 1)).all()
