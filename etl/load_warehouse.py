"""PHASE D + E3: create schema, bulk-load staging, transform into dimensions + fact. Idempotent.

Steps (each safe to re-run):
  1. Run db/schema.sql                (CREATE ... IF NOT EXISTS, calendar dim pre-generated 2013-2018)
  2. TRUNCATE staging_raw_games, then COPY every CSV from the staging folder (bulk load, not row-by-row)
  3. Run db/transform.sql in one transaction (dimensions first, then fact, then moves; ON CONFLICT DO NOTHING)
  4. Run db/indexes.sql and ANALYZE
  5. Print row-count reconciliation

Usage:
    python etl/load_warehouse.py
    python etl/load_warehouse.py --staging-dir data\\processed\\staging_test --database-url postgresql://postgres:PW@localhost:5432/chess_dw_test
"""
import argparse
import sys
import time
from pathlib import Path

import psycopg2

from config import DATABASE_URL, DB_DIR, STAGING_DIR
from pgn_stream import STAGING_COLS


def connect(url):
    if not url:
        sys.exit("DATABASE_URL is empty. Put it in .env or pass --database-url.")
    return psycopg2.connect(url.replace("postgresql+psycopg2://", "postgresql://"))


def count(cur, table):
    cur.execute(f"SELECT count(*) FROM {table}")
    return cur.fetchone()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging-dir", default=str(STAGING_DIR))
    ap.add_argument("--database-url", default=DATABASE_URL)
    args = ap.parse_args()

    csvs = sorted(Path(args.staging_dir).glob("*.csv"))
    if not csvs:
        sys.exit(f"No CSV files in {args.staging_dir}. Run etl/extract.py first.")

    conn = connect(args.database_url)
    cur = conn.cursor()
    t0 = time.time()

    print("1/4 applying schema ...")
    cur.execute((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()

    print(f"2/4 bulk loading {len(csvs)} CSV files into staging_raw_games ...")
    cur.execute("TRUNCATE staging_raw_games")
    cols = ", ".join(STAGING_COLS)
    for i, p in enumerate(csvs, 1):
        with open(p, "r", encoding="utf-8", newline="") as fh:
            cur.copy_expert(f"COPY staging_raw_games ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')", fh)
        if i % 10 == 0 or i == len(csvs):
            print(f"    {i}/{len(csvs)} files")
    conn.commit()
    staged = count(cur, "staging_raw_games")

    print("3/4 transforming into dimensions and fact (one transaction) ...")
    before = count(cur, "game_fact")
    cur.execute((DB_DIR / "transform.sql").read_text(encoding="utf-8"))
    conn.commit()

    print("4/4 indexes + ANALYZE ...")
    cur.execute((DB_DIR / "indexes.sql").read_text(encoding="utf-8"))
    conn.commit()
    cur.execute("ANALYZE")
    conn.commit()

    after = count(cur, "game_fact")
    print("\n===== RECONCILIATION =====")
    print(f"staging rows            : {staged:,}")
    cur.execute("SELECT count(DISTINCT game_id) FROM staging_raw_games")
    print(f"distinct game_ids       : {cur.fetchone()[0]:,}")
    print(f"game_fact rows before   : {before:,}")
    print(f"game_fact rows after    : {after:,}   (+{after - before:,} new)")
    for t in ("game_moves", "dim_player", "dim_opening", "dim_timecontrol", "dim_time"):
        print(f"{t:<24}: {count(cur, t):,}")
    print(f"\nDone in {time.time() - t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
