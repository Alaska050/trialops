-- Safety signal by site: adverse events per randomised subject and
-- share of subjects with a severe or serious AE.
WITH subj AS (
    SELECT SITEID, COUNT(*) AS n_subjects FROM adsl GROUP BY SITEID
),
ae_subj AS (
    SELECT
        a.SITEID,
        ae.USUBJID,
        COUNT(*)                                                   AS n_ae,
        MAX(CASE WHEN ae.AESEV = 'SEVERE' OR ae.AESER = 'Y' THEN 1 ELSE 0 END) AS severe_or_serious
    FROM ae
    JOIN adsl a ON a.USUBJID = ae.USUBJID
    GROUP BY a.SITEID, ae.USUBJID
)
SELECT
    s.SITEID                                                  AS site,
    s.n_subjects,
    COALESCE(SUM(x.n_ae), 0)                                  AS total_aes,
    ROUND(1.0 * COALESCE(SUM(x.n_ae), 0) / s.n_subjects, 2)  AS aes_per_subject,
    ROUND(100.0 * COALESCE(SUM(x.severe_or_serious), 0) / s.n_subjects, 1) AS pct_severe_or_serious
FROM subj s
LEFT JOIN ae_subj x ON x.SITEID = s.SITEID
GROUP BY s.SITEID, s.n_subjects
ORDER BY aes_per_subject DESC;
