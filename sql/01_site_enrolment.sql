-- Site performance: screening, randomisation and screen-failure rate per site,
-- ranked by number of randomised subjects (window function).
WITH site_counts AS (
    SELECT
        SITEID,
        COUNT(*)                                           AS screened,
        SUM(CASE WHEN ARMCD <> 'Scrnfail' THEN 1 ELSE 0 END) AS randomised,
        SUM(CASE WHEN ARMCD =  'Scrnfail' THEN 1 ELSE 0 END) AS screen_failures
    FROM dm
    GROUP BY SITEID
)
SELECT
    SITEID                                              AS site,
    screened,
    randomised,
    screen_failures,
    ROUND(100.0 * screen_failures / screened, 1)        AS screen_fail_pct,
    RANK() OVER (ORDER BY randomised DESC)              AS enrolment_rank
FROM site_counts
ORDER BY enrolment_rank, site;
