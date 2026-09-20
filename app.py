"""TrialOps - clinical trial operations dashboard (Streamlit).

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from trialops.build_db import DB_PATH, build
from trialops.checks import run_checks, summarise
from trialops.model import (CATEGORICAL, LANDMARK_DAY, NUMERIC, evaluate, fit_final,
                            load_features, odds_ratios)

SQL_DIR = Path(__file__).parent / "sql"
ARM_COLOURS = {
    "Placebo": "#8a94a6",
    "Xanomeline Low Dose": "#3b82c4",
    "Xanomeline High Dose": "#d9713c",
}

st.set_page_config(page_title="TrialOps", page_icon="📊", layout="wide")


# ---------- data access ----------

@st.cache_resource
def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        build()
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data
def sql(name: str, **params) -> pd.DataFrame:
    query = (SQL_DIR / name).read_text()
    return pd.read_sql(query, get_connection(), params=params or None)


@st.cache_data
def data_queries() -> pd.DataFrame:
    return run_checks(get_connection())


@st.cache_data
def model_results():
    df = load_features(get_connection())
    return df, evaluate(df, n_repeats=5)


@st.cache_resource
def final_model():
    df = load_features(get_connection())
    return fit_final(df)


# ---------- header ----------

st.title("TrialOps: Clinical Trial Operations Dashboard")
st.caption(
    "CDISC Pilot 01 study (CDISCPILOT01): a public, anonymised Phase 2 trial of "
    "xanomeline vs placebo in Alzheimer's disease, in CDISC SDTM/ADaM format. "
    "Built with SQLite, pandas, scikit-learn and Streamlit."
)

tabs = st.tabs(["Overview", "Sites & enrolment", "Retention", "Safety",
                "Data quality", "Dropout risk"])

# ---------- 1. overview ----------

with tabs[0]:
    sites = sql("01_site_enrolment.sql")
    disp = sql("03_disposition.sql")
    screened, randomised = sites.screened.sum(), sites.randomised.sum()
    completed = disp.loc[disp.disposition == "COMPLETED", "subjects"].sum()
    queries = data_queries()

    c = st.columns(5)
    c[0].metric("Subjects screened", f"{screened}")
    c[1].metric("Randomised", f"{randomised}")
    c[2].metric("Screen-failure rate", f"{100 * (1 - randomised / screened):.1f}%")
    c[3].metric("Completed study", f"{100 * completed / randomised:.1f}%")
    c[4].metric("Open data queries", f"{len(queries)}")

    left, right = st.columns(2)
    with left:
        st.subheader("Cumulative randomisation")
        enr = sql("02_enrolment_over_time.sql")
        fig = px.area(enr, x="month", y="cumulative_randomised",
                      labels={"month": "", "cumulative_randomised": "Subjects randomised"})
        fig.update_traces(line_color="#3b82c4")
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Completion by arm")
        comp = disp.assign(status=disp.disposition.where(disp.disposition == "COMPLETED",
                                                         "DISCONTINUED"))
        comp = comp.groupby(["arm", "status"], as_index=False).subjects.sum()
        fig = px.bar(comp, x="arm", y="subjects", color="status", barmode="stack",
                     color_discrete_map={"COMPLETED": "#3b82c4", "DISCONTINUED": "#d9713c"},
                     labels={"arm": "", "subjects": "Subjects", "status": ""})
        st.plotly_chart(fig, width="stretch")

    st.info(
        "**Key operational finding:** only ~30% of subjects on xanomeline completed the study, "
        "vs 67% on placebo - around half of each xanomeline arm left because of adverse events. "
        "At a CRO this would prompt a conversation about tolerability, dose titration and whether sample size assumptions for dropout still hold."
    )

# ---------- 2. sites ----------

with tabs[1]:
    st.subheader("Site performance")
    sites = sql("01_site_enrolment.sql")
    window = st.slider("Visit window (± days from planned study day)", 3, 14, 7)
    windows = sql("05_visit_windows.sql", window_days=window)
    site_view = sites.merge(windows[["site", "scheduled_visits", "out_of_window_pct"]],
                            on="site", how="left")

    left, right = st.columns([3, 2])
    with left:
        bars = (site_view.rename(columns={"randomised": "Randomised",
                                          "screen_failures": "Screen failures"})
                .sort_values("Randomised"))
        fig = px.bar(bars, y="site", x=["Randomised", "Screen failures"],
                     orientation="h", barmode="stack",
                     color_discrete_sequence=["#3b82c4", "#c9ced8"],
                     labels={"value": "Subjects screened", "site": "Site", "variable": ""})
        fig.update_yaxes(type="category")
        st.plotly_chart(fig, width="stretch")
    with right:
        fig = px.scatter(site_view, x="randomised", y="out_of_window_pct", text="site",
                         size="scheduled_visits", size_max=30,
                         labels={"randomised": "Subjects randomised",
                                 "out_of_window_pct": "% visits out of window"})
        fig.update_traces(textposition="top center", marker_color="#d9713c")
        st.plotly_chart(fig, width="stretch")
        st.caption("Small sites with high out-of-window rates are candidates for "
                   "retraining or a monitoring visit.")

    st.dataframe(site_view, hide_index=True, width="stretch")
    with st.expander("SQL behind this view"):
        st.code((SQL_DIR / "01_site_enrolment.sql").read_text(), language="sql")
        st.code((SQL_DIR / "05_visit_windows.sql").read_text(), language="sql")

# ---------- 3. retention ----------

with tabs[2]:
    st.subheader("Retention across scheduled visits")
    ret = sql("04_retention_by_visit.sql")
    fig = px.line(ret, x="planned_day", y="pct_retained", color="arm", markers=True,
                  hover_data=["visit", "attended"], color_discrete_map=ARM_COLOURS,
                 category_orders={"arm": list(ARM_COLOURS)},
                  labels={"planned_day": "Planned study day", "pct_retained": "% of arm attending",
                          "arm": ""})
    fig.update_yaxes(range=[0, 105])
    st.plotly_chart(fig, width="stretch")

    st.subheader("Why subjects left the study")
    disp = sql("03_disposition.sql")
    reasons = disp[disp.disposition != "COMPLETED"]
    fig = px.bar(reasons, x="pct_of_arm", y="disposition", color="arm", barmode="group",
                 orientation="h", color_discrete_map=ARM_COLOURS,
                 category_orders={"arm": list(ARM_COLOURS)},
                 labels={"pct_of_arm": "% of arm", "disposition": "", "arm": ""})
    fig.update_yaxes(categoryorder="total ascending")
    st.plotly_chart(fig, width="stretch")
    with st.expander("SQL behind this view"):
        st.code((SQL_DIR / "04_retention_by_visit.sql").read_text(), language="sql")

# ---------- 4. safety ----------

with tabs[3]:
    left, right = st.columns(2)
    with left:
        st.subheader("Top body systems with adverse events")
        soc = sql("07_ae_by_body_system.sql")
        top = soc.groupby("body_system").subjects_with_ae.sum().nlargest(8).index
        soc = soc[soc.body_system.isin(top)].copy()
        soc["body_system"] = soc.body_system.str.title().str.slice(0, 40)
        fig = px.bar(soc, x="subjects_with_ae", y="body_system", color="arm", barmode="group",
                     orientation="h", color_discrete_map=ARM_COLOURS,
                 category_orders={"arm": list(ARM_COLOURS)},
                     labels={"subjects_with_ae": "Subjects with ≥1 AE", "body_system": "", "arm": ""})
        fig.update_yaxes(categoryorder="total ascending")
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader("Adverse events by site")
        aes = sql("06_ae_by_site.sql")
        fig = px.scatter(aes, x="aes_per_subject", y="pct_severe_or_serious", size="n_subjects",
                         text="site", size_max=30,
                         labels={"aes_per_subject": "AEs per subject",
                                 "pct_severe_or_serious": "% subjects with severe/serious AE"})
        fig.update_traces(textposition="top center", marker_color="#3b82c4")
        st.plotly_chart(fig, width="stretch")
        st.caption("Sites far from the cluster may be over- or under-reporting AEs - "
                   "a common trigger for source data verification.")

# ---------- 5. data quality ----------

with tabs[4]:
    st.subheader("Automated data-quality checks")
    st.write("Edit checks of the kind a data management team runs before database lock. "
             "Each row below is a query that would be raised with the site.")
    queries = data_queries()
    summary = summarise(queries)
    st.dataframe(summary, hide_index=True, width="stretch")

    by_site = queries.groupby(["SITEID", "severity"], as_index=False).size()
    fig = px.bar(by_site, x="SITEID", y="size", color="severity",
                 color_discrete_map={"High": "#c0392b", "Medium": "#d9713c", "Low": "#c9ced8"},
                 category_orders={"severity": ["High", "Medium", "Low"]},
                 labels={"SITEID": "Site", "size": "Open queries", "severity": ""})
    fig.update_xaxes(type="category")
    st.plotly_chart(fig, width="stretch")
    st.caption("DM01 fires for every subject: the consent date was never populated in this "
               "dataset. That is a systemic data-management issue to raise once, not 306 site queries - "
               "part of data management is telling those two situations apart.")

    chosen = st.multiselect("Filter by check", summary.check_id[summary.issues > 0].tolist())
    listing = queries[queries.check_id.isin(chosen)] if chosen else queries
    st.dataframe(listing, hide_index=True, width="stretch")
    st.download_button("Download query listing (CSV)", listing.to_csv(index=False),
                       file_name="data_queries.csv", mime="text/csv")

# ---------- 6. dropout risk ----------

with tabs[5]:
    st.subheader(f"Early-warning model: risk of discontinuing, assessed at day {LANDMARK_DAY}")
    st.write(
        f"Uses only what the study team knows by the Week 2 visit: baseline characteristics "
        f"plus adverse events in the first {LANDMARK_DAY} days. Subjects who had already left "
        f"by day {LANDMARK_DAY} are excluded, and nothing measured later (treatment duration, "
        f"dose, completion flags) is used, to avoid data leakage."
    )
    with st.spinner("Cross-validating models..."):
        features, results = model_results()
    model = final_model()

    c = st.columns(3)
    c[0].metric("Subjects in model", len(features))
    c[1].metric("Later discontinued", f"{features.discontinued.mean():.0%}")
    lr_auc = results.query("model == 'Logistic regression' and metric == 'ROC-AUC'").iloc[0]
    c[2].metric("Logistic regression ROC-AUC", f"{lr_auc['mean']:.2f} ± {lr_auc['sd']:.2f}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Cross-validated performance** (5-fold, repeated 5×)")
        st.dataframe(results.round(3), hide_index=True, width="stretch")
        st.caption("The simple logistic regression does at least as well as the random forest - "
                   "with ~240 subjects, the interpretable model is the better choice.")
    with right:
        st.markdown("**What drives risk** (odds ratios)")
        ors = odds_ratios(model)
        ors["direction"] = ors.odds_ratio.gt(1).map({True: "Raises risk", False: "Lowers risk"})
        fig = px.scatter(ors, x="odds_ratio", y="feature", color="direction", log_x=True,
                         color_discrete_map={"Raises risk": "#d9713c", "Lowers risk": "#3b82c4"},
                         labels={"odds_ratio": "Odds ratio (log scale; numeric = per 1 SD)",
                                 "feature": "", "direction": ""})
        fig.add_vline(x=1, line_dash="dash", line_color="#8a94a6")
        fig.update_traces(marker_size=12)
        fig.update_yaxes(categoryorder="array", categoryarray=ors.feature[::-1].tolist())
        st.plotly_chart(fig, width="stretch")

    st.markdown("**Try it: score a subject at their Week 2 visit**")
    f = st.columns(4)
    subject = pd.DataFrame([{
        "AGE": f[0].number_input("Age", 50, 95, 75),
        "SEX": f[1].selectbox("Sex", ["F", "M"]),
        "TRT01P": f[2].selectbox("Arm", list(ARM_COLOURS)),
        "MMSETOT": f[3].number_input("Baseline MMSE", 10, 30, 18),
        "BMIBL": f[0].number_input("Baseline BMI", 15.0, 45.0, 24.0),
        "EDUCLVL": f[1].number_input("Years of education", 0, 25, 12),
        "DURDIS": f[2].number_input("Disease duration (months)", 0.0, 200.0, 40.0),
        "early_ae_count": f[3].number_input("AEs in first 14 days", 0, 20, 1),
        "early_ae_mod_sev": f[0].number_input("…of which moderate/severe", 0, 20, 0),
    }])
    risk = model.predict_proba(subject[NUMERIC + CATEGORICAL])[0, 1]
    st.metric("Predicted probability of discontinuing", f"{risk:.0%}")
    st.caption("A demonstration on a small pilot dataset, not a validated clinical tool. "
               "In practice this would flag subjects for a retention call, not make decisions.")
