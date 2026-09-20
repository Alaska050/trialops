-- End-of-study disposition by treatment arm (randomised subjects only).
SELECT
    a.TRT01P                                            AS arm,
    ds.DSDECOD                                          AS disposition,
    COUNT(*)                                            AS subjects,
    ROUND(100.0 * COUNT(*) /
          SUM(COUNT(*)) OVER (PARTITION BY a.TRT01P), 1) AS pct_of_arm
FROM ds
JOIN adsl a ON a.USUBJID = ds.USUBJID
WHERE ds.DSCAT = 'DISPOSITION EVENT'
GROUP BY a.TRT01P, ds.DSDECOD
ORDER BY arm, subjects DESC;
