# ETL validation report (Phase F)

## 1. Row reconciliation

| staging_rows | staging_distinct_ids | fact_rows | moves_rows | players | openings | time_controls |
|---|---|---|---|---|---|---|
| 954538 | 954538 | 954527 | 954527 | 345775 | 3078 | 1193 |

## 2. Staging rows that did NOT reach the fact table (expect 0; duplicates across months are the only valid reason)

| missing_from_fact |
|---|
| 11 |

## 3. Orphan foreign keys (expect all 0)

| orphan_white | orphan_black | orphan_date | orphan_tc | orphan_opening | duplicate_game_ids |
|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | 0 |

## 4. Time-control bucket consistency: Python stratum vs SQL dimension (expect 0 mismatches)

| mismatches |
|---|
| 0 |

## 5. Rows per year and tier

| year | tier | games | est_population_games |
|---|---|---|---|
| 2013 | 1 | 144087 | 3319430 |
| 2014 | 1 | 185034 | 11288900 |
| 2015 | 1 | 197458 | 29243800 |
| 2016 | 1 | 196416 | 70717700 |
| 2017 | 1 | 196050 | 133501000 |
| 2018 | 1 | 35482 | 34747300 |

## 6. Null / availability rates by year (matches Phase B expectations?)

| year | games | pct_with_clock | pct_with_eval | pct_termination | pct_rating_diff |
|---|---|---|---|---|---|
| 2013 | 144087 | 0.0 | 1.8 | 100.0 | 100.0 |
| 2014 | 185034 | 0.0 | 16.5 | 100.0 | 99.6 |
| 2015 | 197458 | 0.0 | 23.5 | 100.0 | 99.8 |
| 2016 | 196416 | 0.0 | 20.7 | 100.0 | 99.8 |
| 2017 | 196050 | 73.7 | 18.0 | 100.0 | 99.8 |
| 2018 | 35482 | 100.0 | 18.2 | 100.0 | 99.9 |

## 7. Time-control mix: sample vs weighted estimate of the population

| category | sample_games | sample_pct | weighted_pct |
|---|---|---|---|
| Bullet | 266855 | 28.0 | 29.5 |
| Blitz | 260229 | 27.3 | 46.1 |
| Rapid | 233330 | 24.4 | 22.5 |
| Classical | 194113 | 20.3 | 1.9 |

## 8. Sanity: White score by time control (expect roughly 0.50 to 0.55; weighted removes sampling skew)

| category | games | white_score_unweighted | white_score_weighted |
|---|---|---|---|
| Blitz | 260229 | 0.520 | 0.517 |
| Bullet | 266855 | 0.517 | 0.512 |
| Classical | 194113 | 0.516 | 0.518 |
| Rapid | 233330 | 0.521 | 0.524 |

## 9. Sanity: plies and Elo ranges (no impossible values)

| min_plies | avg_plies | max_plies | min_elo | max_elo |
|---|---|---|---|---|
| 10 | 67.5 | 430 | 712 | 3074 |

## 10. Months with the fewest sampled games (coverage check)

| source_month | games |
|---|---|
| 2013-01 | 10017 |
| 2013-02 | 10436 |
| 2013-03 | 11088 |
| 2013-05 | 11235 |
| 2013-04 | 11304 |

