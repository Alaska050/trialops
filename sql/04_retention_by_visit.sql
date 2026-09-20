-- Retention funnel: % of each arm's randomised subjects attending each scheduled visit.
WITH arm_size AS (
    SELECT TRT01P, COUNT(*) AS n FROM adsl GROUP BY TRT01P
)
SELECT
    a.TRT01P                                   AS arm,
    sv.VISITNUM                                AS visitnum,
    sv.VISIT                                   AS visit,
    sv.VISITDY                                 AS planned_day,
    COUNT(DISTINCT sv.USUBJID)                 AS attended,
    ROUND(100.0 * COUNT(DISTINCT sv.USUBJID) / s.n, 1) AS pct_retained
FROM sv
JOIN adsl a     ON a.USUBJID = sv.USUBJID
JOIN arm_size s ON s.TRT01P  = a.TRT01P
WHERE sv.VISIT = 'BASELINE' OR sv.VISIT LIKE 'WEEK%'
GROUP BY a.TRT01P, sv.VISITNUM, sv.VISIT, sv.VISITDY
ORDER BY arm, visitnum;
