# Sampling Plan

Numbers below come from the real extraction and load runs (see `docs/etl_validation.md`). Items marked **TO CONFIRM** were not available when this draft was written and must be checked against `etl/extract.py` before the report is submitted.

## 1. Source data

- Lichess standard rated games, monthly `.pgn.zst` files, January 2013 to February 2018 (62 months in the window).
- 60 files downloaded (about 64.7 GB). **2016-05 and 2017-07 were not available in the downloaded set and are excluded.** The warehouse covers 60 of the 62 months in the window.
- File checksums were not verified.
- Files are streamed and decompressed in memory; nothing is decompressed to disk.

## 2. Volume

| Stage | Count |
|---|---|
| Games read from all files | 288,688,572 |
| Games kept by the sampler (staging) | 954,538 |
| Rows loaded into `game_fact` | 954,527 |
| Staging rows not loaded | 11 (0.001%), cause not investigated |

The kept sample is about 0.33% of the games read.

## 3. Filters

**TO CONFIRM against `etl/extract.py`:** the exact list of games dropped before sampling. Known from the data: every kept game has at least 10 plies (observed range 10 to 430), and Elo values range from 712 to 3074.

## 4. Stratified reservoir sampling

- **Strata:** month x time-control category (Bullet, Blitz, Rapid, Classical) x rating band (`<1200`, `1200-1499`, `1500-1799`, `1800-2099`, `2100-2399`, `2400+`).
- **Allocation:** equal allocation, up to 800 games per cell (`--per-cell 800`). Cells with fewer than 800 games keep all of them.
- **Method:** reservoir sampling, so a single streaming pass is enough and memory stays bounded.
- **Reproducibility:** seeded, resumable and idempotent. Output is one CSV per month in `data/processed/staging/`.
- **Time-control buckets:** estimated duration = base + 40 x increment seconds. Bullet up to 179 s, Blitz up to 479 s, Rapid up to 1499 s, otherwise Classical.

### Why equal allocation

Proportional sampling would be almost entirely Blitz and Bullet, leaving Classical and the 2400+ band with too few games to analyse. Equal allocation guarantees every cell enough games for OLAP and mining. **TO CONFIRM with the project lead** that this is the decision to defend in the viva.

## 5. Weights

Equal allocation distorts the population mix, so each row carries `sample_weight = stratum_seen / stratum_kept`.

- Raw sample is about 20% Classical; the weighted estimate is 1.9% Classical (Blitz about 46%).
- All population claims (OLAP totals, shares, white score) use `SUM(sample_weight)` or weighted averages.
- Sum of `sample_weight` is about 282.4M against 288.7M games read. The 2.2% gap is consistent with games removed by the filters before stratification (not separately verified).
- Mining tools without row-weight support use a weighted resample (probability proportional to `sample_weight`, seed 42).
- Very thin cells are never interpreted.

## 6. Clock and evaluation availability

| Field | Availability |
|---|---|
| `%clk` (move clocks) | 0% for 2013 to 2016, 73.7% of 2017, 100% of 2018 |
| Embedded `%eval` | 1.8% in 2013, 16 to 23% afterwards |
| Clock-bearing games in sample | 179,959 |
| With eval | 161,894 |
| With both | 30,989 |

Embedded evals exist only where a player requested engine analysis, so they are a biased subset and are not used as a general quality measure. Timing-based cheat screening (Tier 1) is limited to clock-bearing games.

## 7. Known limitations

- 2016-05 and 2017-07 are absent. Stray counts in those months (about 11.8k and 39.6k estimated games) look like a boundary artefact, possibly games whose UTCDate falls in that month but sit in neighbouring files (not verified). Exclude them from time-series charts or draw them as gaps, and compare monthly averages rather than yearly totals for 2016 and 2017.
- 11 staging rows were not loaded.
- Sampling is within strata; within a cell the sample is uniform random, so intra-cell structure (for example particular players) is not preserved.
