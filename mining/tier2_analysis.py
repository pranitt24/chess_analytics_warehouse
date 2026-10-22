"""Phase I, Tier 2: Stockfish analysis of clock-bearing games into the warehouse.

Creates table game_analysis (one row per analysed game: ACPL and engine-match rate
for each side) and sets game_fact.analysis_tier = 2 for successfully analysed games.

Target set = every game flagged by Tier 1 (tier1_flags.csv) + the first --limit games
of a seeded random ordering of all clock-bearing games. The set is stable across runs,
and games already in game_analysis are skipped, so the script is RESUMABLE:
stop with Ctrl+C any time and re-run the same command to continue.
Games that fail to replay are stored with NULL metrics (so they are not retried).

Run on its own (uses most CPU cores; about 850 games/min measured at depth 12):
    python mining\\tier2_analysis.py
    python mining\\tier2_analysis.py --limit 20000 --depth 12
Needs: chess, pandas
"""
import argparse
import multiprocessing as mp
import os
import time
from pathlib import Path

import pandas as pd

from stockfish_benchmark import DEFAULT_ENGINE, OUT_DIR, connect, get_url, work

DDL = """
CREATE TABLE IF NOT EXISTS game_analysis (
    game_key    BIGINT PRIMARY KEY,
    depth       SMALLINT NOT NULL,
    w_acpl      REAL,
    b_acpl      REAL,
    w_match     REAL,
    b_match     REAL,
    w_moves     SMALLINT,
    b_moves     SMALLINT,
    analysed_at TIMESTAMPTZ DEFAULT now()
)
"""

ALTER = ("ALTER TABLE game_analysis "
         "ADD COLUMN IF NOT EXISTS w_losses INTEGER[], "
         "ADD COLUMN IF NOT EXISTS b_losses INTEGER[], "
         "ADD COLUMN IF NOT EXISTS w_hits TEXT, "
         "ADD COLUMN IF NOT EXISTS b_hits TEXT")

# w_losses / b_losses: per-move centipawn loss (plies >= 10) for each side;
# w_hits / b_hits: per-move engine-match flags as a string of 0/1.
# Upsert: rows analysed by an older version of this script (no per-move data) are redone.
INSERT = ("INSERT INTO game_analysis "
          "(game_key, depth, w_acpl, b_acpl, w_match, b_match, w_moves, b_moves, "
          "w_losses, b_losses, w_hits, b_hits) "
          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
          "ON CONFLICT (game_key) DO UPDATE SET depth=EXCLUDED.depth, "
          "w_acpl=EXCLUDED.w_acpl, b_acpl=EXCLUDED.b_acpl, w_match=EXCLUDED.w_match, "
          "b_match=EXCLUDED.b_match, w_moves=EXCLUDED.w_moves, b_moves=EXCLUDED.b_moves, "
          "w_losses=EXCLUDED.w_losses, b_losses=EXCLUDED.b_losses, "
          "w_hits=EXCLUDED.w_hits, b_hits=EXCLUDED.b_hits")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--engine", default=os.getenv("STOCKFISH_PATH", DEFAULT_ENGINE))
    ap.add_argument("--flags", default=str(OUT_DIR / "tier1_flags.csv"))
    ap.add_argument("--limit", type=int, default=50_000,
                    help="random clock-bearing games to analyse (flagged games are added on top)")
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--batch", type=int, default=2000)
    ap.add_argument("--seed", default="42")
    a = ap.parse_args()

    if not Path(a.engine).exists():
        raise SystemExit(f"Stockfish not found at {a.engine}. Pass --engine <path>.")

    con = connect(get_url(a.database_url))
    cur = con.cursor()
    cur.execute(DDL)
    cur.execute(ALTER)
    con.commit()

    cur.execute("SELECT game_key FROM game_fact WHERE has_clk ORDER BY md5(game_id || %s)",
                (a.seed,))
    keys = [r[0] for r in cur.fetchall()]
    flagged = []
    if Path(a.flags).exists():
        flagged = pd.read_csv(a.flags, usecols=["game_key"])["game_key"].astype(int).unique().tolist()
    cur.execute("SELECT game_key FROM game_analysis "
                "WHERE w_losses IS NOT NULL OR w_acpl IS NULL")
    done = {r[0] for r in cur.fetchall()}

    order, seen = [], set(done)
    for k in flagged + keys[:a.limit]:
        if k not in seen:
            seen.add(k)
            order.append(k)
    print(f"Clock-bearing games: {len(keys):,}; flagged: {len(flagged):,}; "
          f"already analysed: {len(done):,}; to do now: {len(order):,}")
    if not order:
        print("Nothing to do.")
        return

    t0, n_ok, n_fail, errors = time.time(), 0, 0, []
    with mp.Pool(a.workers) as pool:
        for start in range(0, len(order), a.batch):
            batch = order[start:start + a.batch]
            cur.execute("SELECT f.game_key, f.game_id, m.moves_san FROM game_fact f "
                        "JOIN game_moves m ON m.game_key = f.game_key "
                        "WHERE f.game_key = ANY(%s)", (batch,))
            rows = cur.fetchall()
            key_of = {gid: k for k, gid, _ in rows}
            tasks = [([(gid, san) for _, gid, san in rows[i:i + 5]],
                      a.engine, a.depth, 64, 10) for i in range(0, len(rows), 5)]

            ins, ok_keys = [], []
            for res in pool.imap_unordered(work, tasks):
                for gid, r in res:
                    k = key_of[gid]
                    if r is None or "error" in r:
                        n_fail += 1
                        if r is not None and len(errors) < 10:
                            errors.append((gid, r["error"]))
                        ins.append((k, a.depth, None, None, None, None, None, None,
                                    None, None, None, None))
                    else:
                        n_ok += 1
                        ok_keys.append(k)
                        ins.append((k, a.depth, r["w_acpl"], r["b_acpl"], r["w_match"],
                                    r["b_match"], r["w_moves"], r["b_moves"],
                                    r["w_losses"], r["b_losses"], r["w_hits"], r["b_hits"]))
            cur.executemany(INSERT, ins)
            if ok_keys:
                cur.execute("UPDATE game_fact SET analysis_tier = 2 WHERE game_key = ANY(%s)",
                            (ok_keys,))
            con.commit()

            done_n = start + len(batch)
            el = time.time() - t0
            eta = el / done_n * (len(order) - done_n) / 60
            print(f"  {done_n:,}/{len(order):,} games ({n_ok:,} ok, {n_fail:,} failed), "
                  f"{el / 60:.1f} min elapsed, ~{eta:.0f} min left")

    print(f"\nDone: {n_ok:,} analysed, {n_fail:,} failed in {(time.time() - t0) / 60:.1f} min")
    for gid, e in errors:
        print(f"  failed {gid}: {e}")
    cur.execute("SELECT count(*), round(avg(w_acpl)::numeric,1), round(avg(w_match)::numeric,3) "
                "FROM game_analysis WHERE w_acpl IS NOT NULL")
    print("game_analysis rows with metrics, mean white ACPL, mean white match:", cur.fetchone())
    con.close()


if __name__ == "__main__":
    mp.freeze_support()
    main()
