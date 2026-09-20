-- Protocol compliance: scheduled visits held outside a +/- :window_days window
-- around the planned study day. The app defaults to 7 days; the real protocol
-- window may differ, so it is passed in as a parameter.
WITH visits AS (
    SELECT
        sv.USUBJID,
        dm.SITEID,
        sv.VISIT,
        sv.VISITDY                                                    AS planned_day,
        CAST(julianday(sv.SVSTDTC) - julianday(dm.RFSTDTC) + 1 AS INT) AS actual_day
    FROM sv
    JOIN dm ON dm.USUBJID = sv.USUBJID
    WHERE sv.VISIT LIKE 'WEEK%'
)
SELECT
    SITEID                                                              AS site,
    COUNT(*)                                                            AS scheduled_visits,
    SUM(CASE WHEN ABS(actual_day - planned_day) > :window_days THEN 1 ELSE 0 END) AS out_of_window,
    ROUND(100.0 * SUM(CASE WHEN ABS(actual_day - planned_day) > :window_days THEN 1 ELSE 0 END)
          / COUNT(*), 1)                                                AS out_of_window_pct,
    ROUND(AVG(actual_day - planned_day), 1)                             AS mean_deviation_days
FROM visits
GROUP BY SITEID
ORDER BY out_of_window_pct DESC;
