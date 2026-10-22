# Pipeline runbook (Phases A to F)

Run everything from the repo root in PowerShell with the venv active (`.\.venv\Scripts\Activate.ps1`).

## What goes where

| File | Phase | What it does |
|---|---|---|
| `etl/config.py` | all | Paths, `.env` loading, seed, study window |
| `etl/pgn_stream.py` | all | Streaming `.pgn.zst` reader + parsing helpers (bytes-level, nothing decompressed to disk) |
| `etl/inventory.py` | A | File list, missing months, SHA256 check, writes `docs/data_manifest.md/.csv` |
| `etl/profile.py` | B | Streams first N games of sample months, writes `docs/data_profile.md` |
| `etl/extract.py` | C + E1/E2 | Filters + stratified reservoir sampling, one CSV per month in `data/processed/staging/` |
| `db/schema.sql` | D | Staging table, 4 dimensions, `game_fact`, `game_moves` (replaces your old draft) |
| `db/transform.sql` | E2/E3 | Staging to dimensions to fact, idempotent (`ON CONFLICT DO NOTHING`) |
| `db/indexes.sql` | E3 | OLAP indexes, created after the bulk load |
| `etl/load_warehouse.py` | D + E3 | Applies schema, COPYs the CSVs, runs transform and indexes, prints reconciliation |
| `etl/validate.py` | F | 10 reconciliation and sanity checks, writes `docs/etl_validation.md` |
| `tests/make_synthetic.py` | test | Fake Lichess-format files for dry runs without the real data |

## Order of commands

```powershell
# 0. one-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# A. inventory (seconds), then checksums (5-20 min)
python etl\inventory.py
Invoke-WebRequest https://database.lichess.org/standard/sha256sums.txt -OutFile data\sha256sums.txt
python etl\inventory.py --hash --checksums data\sha256sums.txt

# B. profiling (about a minute)
python etl\profile.py

# C/E1 smoke test: 5,000 games from one month you have (change 2013-01 if it is the missing one)
python etl\extract.py --months 2013-01 --max-games 5000 --per-cell 50 --out data\processed\staging_test

# D/E3 smoke test into a throwaway database
psql -U postgres -c "CREATE DATABASE chess_dw_test;"
python etl\load_warehouse.py --staging-dir data\processed\staging_test --database-url postgresql://postgres:YOURPASSWORD@localhost:5432/chess_dw_test
python etl\validate.py --database-url postgresql://postgres:YOURPASSWORD@localhost:5432/chess_dw_test

# FULL RUN (resumable: re-run the same command after a crash and finished months are skipped)
python etl\extract.py --per-cell 800 --workers 12

# real database
psql -U postgres -c "CREATE DATABASE chess_dw;"
python etl\load_warehouse.py
python etl\validate.py
```

`.env` needs one line: `DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/chess_dw`

## Design decisions (for the viva)

- **Stream, never decompress to disk.** 64.7 GB compressed is hundreds of GB of text.
- **Bytes-level parsing, no python-chess in the ETL.** About 99% of games are discarded by the sampler, so decoding and validating them would be wasted work. python-chess comes back for Tier 2 (Stockfish).
- **Stratified sampling with reservoir sampling.** Strata are month x time-control category x rating band (24 cells per month). Algorithm R gives a uniform random sample of each cell in one pass with bounded memory.
- **Equal allocation per cell plus weights.** Every cell keeps up to `--per-cell` games, so rare cells (Classical, 2400+, early months) are not drowned out by Blitz and late 2017. Each row stores `sample_weight = population / sample` for its cell, so population totals can be recovered (validate.py check 7 shows the sample mix versus the weighted mix). Change `--per-cell` to change the total size. This is a default pending the Phase B/C evidence, not a final decision.
- **Reproducible.** The RNG is seeded from `<seed>:<month>`. Same files and same seed give byte-identical CSVs (tested).
- **Idempotent load.** `game_id` from the Site header is the natural unique key; re-running the load adds 0 rows (tested).
- **Time-control buckets** use the Lichess convention: base + 40 x increment seconds. Up to 179 Bullet, 480 Blitz, 1500 Rapid, above that Classical. UltraBullet is folded into Bullet. Correspondence (`-`) is excluded.
- **Filters:** rated, standard variant, both Elo present, valid result, termination not Abandoned / Rules infraction / Unterminated, at least `--min-plies` half-moves (default 10), real time control. Missing optional headers (Termination, rating diffs, UTCDate) are allowed and stored as NULL, since early years may not have them.
- **Weak points to state honestly:** the profile only looks at the start of each month; Tier 2 (engine) and Tier 3 (synthetic cheat set) are not built yet; clock features exist only where `%clk` annotations exist.

## Tested vs not tested

Tested end to end on synthetic Lichess-format data (4 months, 80k games): inventory with checksums and missing months, profile, extract, resume, byte-identical reproducibility, COPY load, idempotent re-load, validation checks, NULL handling for early-year files without Termination / rating diffs / clocks.

Not yet run on the real files. Real-data quirks (header differences in 2013, the exact zstd window size) show up in the first Phase B profile and the smoke test, which is why they come before the full run.
