-- Most common adverse events by body system and arm (subject counts, not event counts).
SELECT
    a.TRT01P                     AS arm,
    ae.AEBODSYS                  AS body_system,
    COUNT(DISTINCT ae.USUBJID)   AS subjects_with_ae
FROM ae
JOIN adsl a ON a.USUBJID = ae.USUBJID
GROUP BY a.TRT01P, ae.AEBODSYS
ORDER BY subjects_with_ae DESC;
