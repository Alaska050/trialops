-- Cumulative randomisation by month (running total with a window function).
WITH monthly AS (
    SELECT
        substr(RFSTDTC, 1, 7) AS month,
        COUNT(*)              AS randomised
    FROM dm
    WHERE RFSTDTC IS NOT NULL          -- screen failures have no reference start date
    GROUP BY month
)
SELECT
    month,
    randomised,
    SUM(randomised) OVER (ORDER BY month) AS cumulative_randomised
FROM monthly
ORDER BY month;
