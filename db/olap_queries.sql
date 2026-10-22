-- Phase G: OLAP queries on the chess warehouse (star schema)
-- Run:  psql -d chess_warehouse -f db\olap_queries.sql
-- All counts are WEIGHTED: est_games = SUM(sample_weight) estimates real Lichess games.
-- Weighted white score = SUM(white_score * sample_weight) / SUM(sample_weight).

\timing on
\pset pager off

\echo ''
\echo '=== G1. ROLL-UP: year -> quarter -> month (est. games, weighted white score) ==='
SELECT t.year, t.quarter, t.month,
       ROUND(SUM(f.sample_weight))                                  AS est_games,
       ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score
FROM game_fact f
JOIN dim_time t ON t.date_key = f.date_key
GROUP BY ROLLUP (t.year, t.quarter, t.month)
ORDER BY t.year, t.quarter, t.month;

\echo ''
\echo '=== G2. DRILL-DOWN: year -> time-control category -> opening family (top 3 families per year/category) ==='
WITH agg AS (
  SELECT t.year, tc.category, o.opening_family,
         ROUND(SUM(f.sample_weight)) AS est_games,
         ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score
  FROM game_fact f
  JOIN dim_time t         ON t.date_key = f.date_key
  JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key
  JOIN dim_opening o      ON o.opening_key = f.opening_key
  GROUP BY t.year, tc.category, o.opening_family
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY year, category ORDER BY est_games DESC) AS rn
  FROM agg
)
SELECT year, category, opening_family, est_games, white_score
FROM ranked WHERE rn <= 3
ORDER BY year, category, rn;

\echo ''
\echo '=== G3. SLICE: Blitz only, by year ==='
SELECT t.year,
       ROUND(SUM(f.sample_weight)) AS est_games,
       ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score,
       ROUND((SUM(f.plies * f.sample_weight) / SUM(f.sample_weight))::numeric, 1)       AS avg_plies
FROM game_fact f
JOIN dim_time t         ON t.date_key = f.date_key
JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key
WHERE tc.category = 'Blitz'
GROUP BY t.year
ORDER BY t.year;

\echo ''
\echo '=== G4. DICE: Blitz or Rapid, 2016-2017, avg Elo >= 2100, by opening family and category ==='
SELECT tc.category, o.opening_family,
       ROUND(SUM(f.sample_weight)) AS est_games,
       ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score
FROM game_fact f
JOIN dim_time t         ON t.date_key = f.date_key
JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key
JOIN dim_opening o      ON o.opening_key = f.opening_key
WHERE tc.category IN ('Blitz', 'Rapid')
  AND t.year BETWEEN 2016 AND 2017
  AND f.avg_elo >= 2100
GROUP BY tc.category, o.opening_family
HAVING SUM(f.sample_weight) > 1000
ORDER BY est_games DESC
LIMIT 15;

\echo ''
\echo '=== G5. PIVOT: est. games, rows = year, columns = time-control category ==='
SELECT t.year,
       ROUND(SUM(f.sample_weight) FILTER (WHERE tc.category = 'Bullet'))    AS bullet,
       ROUND(SUM(f.sample_weight) FILTER (WHERE tc.category = 'Blitz'))     AS blitz,
       ROUND(SUM(f.sample_weight) FILTER (WHERE tc.category = 'Rapid'))     AS rapid,
       ROUND(SUM(f.sample_weight) FILTER (WHERE tc.category = 'Classical')) AS classical,
       ROUND(SUM(f.sample_weight))                                          AS total
FROM game_fact f
JOIN dim_time t         ON t.date_key = f.date_key
JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key
GROUP BY t.year
ORDER BY t.year;

\echo ''
\echo '=== G6. CUBE: all combinations of year x category x rating_band (subtotals + grand total) ==='
SELECT t.year, tc.category, f.rating_band,
       ROUND(SUM(f.sample_weight)) AS est_games,
       ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score
FROM game_fact f
JOIN dim_time t         ON t.date_key = f.date_key
JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key
GROUP BY CUBE (t.year, tc.category, f.rating_band)
ORDER BY t.year, tc.category, f.rating_band
LIMIT 60;

\echo ''
\echo '=== G7. Weekend vs weekday (slice on a time attribute) ==='
SELECT t.is_weekend,
       ROUND(SUM(f.sample_weight)) AS est_games,
       ROUND((SUM(f.white_score * f.sample_weight) / SUM(f.sample_weight))::numeric, 3) AS white_score
FROM game_fact f
JOIN dim_time t ON t.date_key = f.date_key
GROUP BY t.is_weekend;

\echo ''
\echo '=== G8. Termination mix by time-control category (weighted %) ==='
SELECT tc.category, f.termination,
       ROUND((100 * SUM(f.sample_weight)
              / SUM(SUM(f.sample_weight)) OVER (PARTITION BY tc.category))::numeric, 1) AS pct
FROM game_fact f
JOIN dim_timecontrol tc ON tc.tc_key = f.tc_key
GROUP BY tc.category, f.termination
ORDER BY tc.category, pct DESC;
