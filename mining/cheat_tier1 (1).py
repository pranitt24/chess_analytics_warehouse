"""Phase I, Tier 1: clock-timing outlier screening (no Stockfish needed).

For each side of every game that has clock data, compute the coefficient of
variation of move times (sd / mean). Engine-assisted play tends to be unusually
UNIFORM, so a very low CV is suspicious. Raw CV differs a lot by time control
and strength, so we compare each side only with games of the same
(time-control category, rating band) using a robust z-score on log(CV)
(median and MAD, which outliers cannot distort).

This is a screening heuristic with NO ground truth: a flag means "unusual
timing", not "cheated". Premoving, forced moves and increments also reduce
variance. Rates are weighted by sample_weight so they describe real Lichess.

Usage (from repo root):
    python mining\\cheat_tier1.py
    python mining\\cheat_tier1.py --z 2.5
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed" / "cheat"


def get_url(cli_url):
    if cli_url:
        return cli_url
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No DATABASE_URL. Fix .env at the repo root or pass --database-url.")


def connect(url):
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError:
        import psycopg2
        return psycopg2.connect(url)


def robust_z(x):
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    return (x - med) / mad if mad > 0 else x * 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--z", type=float, default=3.0, help="flag if z(log CV) <= -z")
    ap.add_argument("--min-group", type=int, default=200)
    a = ap.parse_args()

    sql = """
        SELECT f.game_key, f.game_id, tc.category, f.rating_band,
               f.white_elo, f.black_elo,
               f.w_avg_move_time, f.w_move_time_sd,
               f.b_avg_move_time, f.b_move_time_sd,
               f.sample_weight
        FROM game_fact f
        JOIN dim_timecontrol tc ON tc.tc_key = f.tc_key
        WHERE f.has_clk
    """
    with connect(get_url(a.database_url)) as con, con.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    cols = ["game_key", "game_id", "category", "rating_band", "white_elo", "black_elo",
            "w_avg", "w_sd", "b_avg", "b_sd", "weight"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["white_elo", "black_elo", "w_avg", "w_sd", "b_avg", "b_sd", "weight"]:
        df[c] = pd.to_numeric(df[c])
    print(f"Loaded {len(df):,} games with clock data")

    common = ["game_key", "game_id", "category", "rating_band", "weight"]
    w = df[common].assign(side="white", elo=df["white_elo"], avg=df["w_avg"], sd=df["w_sd"])
    b = df[common].assign(side="black", elo=df["black_elo"], avg=df["b_avg"], sd=df["b_sd"])
    s = pd.concat([w, b], ignore_index=True)
    s = s[(s["avg"] > 0) & (s["sd"] > 0)].copy()
    s["log_cv"] = np.log(s["sd"] / s["avg"])
    print(f"{len(s):,} player-sides with usable timing")

    g = s.groupby(["category", "rating_band"])
    s["z_cv"] = g["log_cv"].transform(robust_z)
    s["group_n"] = g["log_cv"].transform("size")
    s["flag"] = (s["z_cv"] <= -a.z) & (s["group_n"] >= a.min_group)

    print(f"\nFlag rule: z(log CV) <= -{a.z} within (category, rating band), group size >= {a.min_group}")
    print(f"Flagged player-sides: {int(s['flag'].sum()):,} ({100 * s['flag'].mean():.2f}% of sample)")

    summ = s.groupby("category").apply(
        lambda d: pd.Series({
            "sides": len(d),
            "flagged": int(d["flag"].sum()),
            "flag_pct_sample": round(100 * d["flag"].mean(), 2),
            "flag_pct_weighted": round(100 * (d["flag"] * d["weight"]).sum() / d["weight"].sum(), 2),
        }), include_groups=False)
    print("\nBy time-control category:")
    print(summ.to_string())

    top = s[s["flag"]].sort_values("z_cv").head(20)
    top = top.assign(url="https://lichess.org/" + top["game_id"].astype(str))
    print("\n20 most uniform timings (open the url on Lichess to inspect):")
    print(top[["url", "side", "category", "rating_band", "elo", "z_cv"]]
          .to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "tier1_flags.csv"
    s[s["flag"]].sort_values("z_cv").to_csv(path, index=False)
    print(f"\nFlagged rows written to {path}")
    allpath = OUT_DIR / "tier1_scores.csv"
    s[["game_key", "game_id", "side", "category", "rating_band", "elo", "z_cv", "flag"]] \
        .to_csv(allpath, index=False)
    print(f"All scored sides (for control sampling) written to {allpath}")


if __name__ == "__main__":
    main()
