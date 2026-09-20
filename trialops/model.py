"""Early-warning model: which subjects are at risk of discontinuing the study?

Design choices worth spelling out:

* Landmark at day 14 (the Week 2 visit). We only use information a trial team
  would actually have on day 14: baseline characteristics plus adverse events
  that started on or before day 14. Subjects who had already left the study
  by day 14 are excluded - predicting something that has already happened is
  not useful.
* No leakage. Treatment duration, cumulative dose, completion flags and any
  post-day-14 data are all excluded from the features, because they are only
  known after the outcome.
* Small data (~250 subjects), so we use repeated stratified cross-validation
  instead of a single train/test split, and compare a simple, interpretable
  logistic regression against a random forest.
"""

import sqlite3

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

LANDMARK_DAY = 14

NUMERIC = ["AGE", "BMIBL", "EDUCLVL", "DURDIS", "MMSETOT", "early_ae_count", "early_ae_mod_sev"]
CATEGORICAL = ["SEX", "TRT01P"]

FEATURE_LABELS = {
    "AGE": "Age (years)",
    "BMIBL": "Baseline BMI",
    "EDUCLVL": "Years of education",
    "DURDIS": "Disease duration (months)",
    "MMSETOT": "Baseline MMSE score",
    "early_ae_count": "AEs in first 14 days",
    "early_ae_mod_sev": "Moderate/severe AEs in first 14 days",
}

FEATURE_SQL = f"""
WITH early_ae AS (
    SELECT
        USUBJID,
        COUNT(*)                                                    AS early_ae_count,
        SUM(CASE WHEN AESEV IN ('MODERATE', 'SEVERE') THEN 1 ELSE 0 END) AS early_ae_mod_sev
    FROM ae
    WHERE AESTDY BETWEEN 1 AND {LANDMARK_DAY}
    GROUP BY USUBJID
)
SELECT
    a.USUBJID, a.SITEID, a.AGE, a.SEX, a.BMIBL, a.EDUCLVL, a.DURDIS, a.MMSETOT, a.TRT01P,
    COALESCE(e.early_ae_count, 0)   AS early_ae_count,
    COALESCE(e.early_ae_mod_sev, 0) AS early_ae_mod_sev,
    CASE WHEN a.DISCONFL = 'Y' THEN 1 ELSE 0 END AS discontinued
FROM adsl a
LEFT JOIN early_ae e ON e.USUBJID = a.USUBJID
-- landmark: subject still on study at day 14
WHERE julianday(a.RFENDTC) - julianday(a.RFSTDTC) + 1 > {LANDMARK_DAY}
"""


def load_features(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql(FEATURE_SQL, con)


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")),
                             ("scale", StandardScaler())]), NUMERIC),
            ("cat", OneHotEncoder(drop="first", handle_unknown="ignore"), CATEGORICAL),
        ]
    )


def make_models() -> dict[str, Pipeline]:
    return {
        "Logistic regression": Pipeline(
            [("prep", _preprocessor()),
             ("clf", LogisticRegression(max_iter=1000, class_weight="balanced"))]
        ),
        "Random forest": Pipeline(
            [("prep", _preprocessor()),
             ("clf", RandomForestClassifier(n_estimators=300, min_samples_leaf=5,
                                            class_weight="balanced", random_state=42))]
        ),
    }


def evaluate(df: pd.DataFrame, n_repeats: int = 10, seed: int = 42) -> pd.DataFrame:
    """Repeated 5-fold stratified CV. Returns mean and SD for each metric."""
    X, y = df[NUMERIC + CATEGORICAL], df["discontinued"]
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=n_repeats, random_state=seed)
    rows = []
    for name, model in make_models().items():
        res = cross_validate(model, X, y, cv=cv,
                             scoring={"ROC-AUC": "roc_auc", "Balanced accuracy": "balanced_accuracy"})
        for metric in ["ROC-AUC", "Balanced accuracy"]:
            scores = res[f"test_{metric}"]
            rows.append({"model": name, "metric": metric,
                         "mean": scores.mean(), "sd": scores.std()})
    return pd.DataFrame(rows)


def fit_final(df: pd.DataFrame) -> Pipeline:
    """Fit the interpretable model on all data for use in the dashboard."""
    model = make_models()["Logistic regression"]
    model.fit(df[NUMERIC + CATEGORICAL], df["discontinued"])
    return model


def odds_ratios(model: Pipeline) -> pd.DataFrame:
    """Odds ratio per 1 SD (numeric) or vs reference level (categorical)."""
    names = model.named_steps["prep"].get_feature_names_out()
    coefs = model.named_steps["clf"].coef_[0]
    out = pd.DataFrame({"feature": names, "coef": coefs})
    out["odds_ratio"] = np.exp(out["coef"])
    out["feature"] = (
        out["feature"].str.replace("num__", "", regex=False)
        .str.replace("cat__TRT01P_", "Arm: ", regex=False)
        .str.replace("cat__SEX_", "Sex: ", regex=False)
        .map(lambda f: FEATURE_LABELS.get(f, f))
    )
    return out.sort_values("odds_ratio", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    from trialops.build_db import DB_PATH

    with sqlite3.connect(DB_PATH) as con:
        data = load_features(con)
    print(f"{len(data)} subjects on study at day {LANDMARK_DAY}; "
          f"{data.discontinued.mean():.0%} later discontinued\n")
    print(evaluate(data).round(3).to_string(index=False))
    print()
    print(odds_ratios(fit_final(data)).round(2).to_string(index=False))
