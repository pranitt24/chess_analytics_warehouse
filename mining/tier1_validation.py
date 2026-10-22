"""Phase I: does the Tier 1 timing flag mean anything?

For each flagged player-side, draw one random UNFLAGGED side from the same
(time-control category, rating band), analyse both games with Stockfish, and
compare that side's ACPL and engine-match rate. If uniform timing signals
engine-like play, flagged sides should show LOWER ACPL and HIGHER match than
their controls. A null or opposite result is a valid finding: it means the
timing flag mostly picks up benign behaviour (steady pace, premoves, etc.).

Run after:  python mining\\cheat_tier1.py   (creates tier1_scores.csv)
Usage:      python mining\\tier1_validation.py
            python mining\\tier1_validation.py --max-flagged 800
Needs: chess, scipy (installed with scikit-learn)
"""
import argparse
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from stockfish_benchmark import DEFAULT_ENGINE, OUT_DIR, connect, get_url, work


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--engine", default=os.getenv("STOCKFISH_PATH", DEFAULT_ENGINE))
    ap.add_argument("--scores", default=str(OUT_DIR / "tier1_scores.csv"))
    ap.add_argument("--max-flagged", type=int, default=1500)
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    scores = pd.read_csv(a.scores)
    scores["flag"] = scores["flag"].astype(bool)
    fl = scores[scores["flag"]]
    if len(fl) > a.max_flagged:
        fl = fl.sample(a.max_flagged, random_state=a.seed)
    pools = {k: g[~g["flag"]] for k, g in scores.groupby(["category", "rating_band"])}

    rng = np.random.default_rng(a.seed)
    pairs = []
    for r in fl.itertuples():
        cand = pools.get((r.category, r.rating_band))
        if cand is None or len(cand) == 0:
            continue
        c = cand.iloc[int(rng.integers(len(cand)))]
        pairs.append({"category": r.category, "band": r.rating_band,
                      "f_id": r.game_id, "f_side": r.side, "f_elo": r.elo,
                      "c_id": c["game_id"], "c_side": c["side"], "c_elo": c["elo"]})
    print(f"{len(pairs)} flagged/control pairs")

    ids = sorted({p["f_id"] for p in pairs} | {p["c_id"] for p in pairs})
    with connect(get_url(a.database_url)) as con, con.cursor() as cur:
        cur.execute("SELECT f.game_id, m.moves_san FROM game_fact f "
                    "JOIN game_moves m ON m.game_key = f.game_key "
                    "WHERE f.game_id = ANY(%s)", (ids,))
        moves = cur.fetchall()
    print(f"Analysing {len(moves)} games at depth {a.depth} with {a.workers} workers")

    tasks = [(moves[i:i + 5], a.engine, a.depth, 64, 10) for i in range(0, len(moves), 5)]
    res, t0 = {}, time.time()
    with mp.Pool(a.workers) as pool:
        for batch in pool.imap_unordered(work, tasks):
            for g, r in batch:
                if r is not None and "error" not in r:
                    res[g] = r
            print(f"  {len(res)}/{len(moves)} games, {time.time() - t0:.0f}s", end="\r")
    print()

    def val(gid, side, key):
        r = res.get(gid)
        if r is None:
            return None
        return r[("w_" if side == "white" else "b_") + key]

    rows = []
    for p in pairs:
        fa, ca = val(p["f_id"], p["f_side"], "acpl"), val(p["c_id"], p["c_side"], "acpl")
        fm, cm = val(p["f_id"], p["f_side"], "match"), val(p["c_id"], p["c_side"], "match")
        if None in (fa, ca, fm, cm):
            continue
        rows.append({**p, "f_acpl": fa, "c_acpl": ca, "f_match": fm, "c_match": cm})
    df = pd.DataFrame(rows)
    df["d_acpl"] = df["f_acpl"] - df["c_acpl"]
    df["d_match"] = df["f_match"] - df["c_match"]

    print(f"\nUsable pairs: {len(df)} of {len(pairs)}")
    print(f"Mean Elo  flagged {df['f_elo'].mean():.0f} vs control {df['c_elo'].mean():.0f} (matching check)")
    print(f"Mean ACPL flagged {df['f_acpl'].mean():.1f} vs control {df['c_acpl'].mean():.1f} "
          f"(diff {df['d_acpl'].mean():+.1f}; negative = flagged more engine-like)")
    print(f"Mean match flagged {df['f_match'].mean():.3f} vs control {df['c_match'].mean():.3f} "
          f"(diff {df['d_match'].mean():+.3f}; positive = flagged more engine-like)")
    print(f"Flagged side has lower ACPL than its control in {100 * (df['d_acpl'] < 0).mean():.1f}% of pairs")
    for name, col in [("ACPL", "d_acpl"), ("match", "d_match")]:
        try:
            p = wilcoxon(df[col]).pvalue
            print(f"Wilcoxon signed-rank p-value ({name}): {p:.3g}")
        except ValueError as e:
            print(f"Wilcoxon ({name}) not computable: {e}")

    print("\nBy time-control category (mean paired differences):")
    print(df.groupby("category").agg(pairs=("d_acpl", "size"),
                                      d_acpl=("d_acpl", "mean"),
                                      d_match=("d_match", "mean")).round(3).to_string())

    path = OUT_DIR / "tier1_validation_pairs.csv"
    df.to_csv(path, index=False)
    print(f"\nPair-level results written to {path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
