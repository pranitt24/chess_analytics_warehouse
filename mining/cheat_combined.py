"""Phase I: combined cheat-suspicion TRIAGE score (Tier 1 timing + Tier 2 move quality).

MARKER: cheat_combined v1 2026-10-17

Inputs
  * data/processed/cheat/tier1_scores.csv  (game_key, game_id, side, category,
    rating_band, elo, z_cv, flag)  -> timing uniformity (lower z_cv = more uniform)
  * table game_analysis (Tier 2)  -> per-side ACPL and engine top-move match rate
  * table game_fact               -> dimension keys, so the output is a proper fact table

Method (all within (category, rating band), so a Bullet 1200 player is only
compared with Bullet 1200 players)
  timing_pct  = percentile rank of -z_cv            (1.0 = most uniform timing)
  quality_pct = mean of percentile(match_rate) and percentile(-ACPL)
  score       = mean(timing_pct, quality_pct)       (0..1, higher = more suspicious)
  signal      = 'both'         timing flag (z <= -3) AND quality_pct >= 0.99
                'timing_only'  timing flag only
                'quality_only' quality_pct >= 0.99 only
                'none'
Groups with fewer than MIN_GROUP scored sides get no score (percentiles are unstable).

Output: table `cheat_score` (one row per game and side = a second fact table at
player-game grain that shares dim_player, dim_time, dim_timecontrol and dim_opening
with game_fact, i.e. a fact constellation) and data/processed/cheat/cheat_score.csv.

THIS IS A TRIAGE RANKING, NOT PROOF. Both inputs are statistical signals with no
ground truth; a high score means "worth a human look".

Run from the repo root:  python mining\\cheat_combined.py
"""
import argparse
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHEAT_DIR = ROOT / "data" / "processed" / "cheat"
TIER1_CSV = CHEAT_DIR / "tier1_scores.csv"
MIN_MOVES = 15          # scored moves per side; shorter sides have noisy ACPL / match
MIN_GROUP = 100         # scored sides needed in a (category, band) group
QUALITY_CUT = 0.99      # top 1% move quality within group counts as a signal
GROUP = ["category", "rating_band"]

SQL = """
SELECT ga.game_key, f.white_player_key, f.black_player_key, f.date_key, f.tc_key,
       f.opening_key, ga.w_acpl, ga.b_acpl, ga.w_match, ga.b_match,
       ga.w_moves, ga.b_moves
FROM game_analysis ga
JOIN game_fact f ON f.game_key = ga.game_key
WHERE ga.w_acpl IS NOT NULL AND ga.b_acpl IS NOT NULL
"""

DDL = """
CREATE TABLE IF NOT EXISTS cheat_score (
    game_key     BIGINT   NOT NULL,
    side         TEXT     NOT NULL,
    game_id      TEXT,
    player_key   BIGINT,
    date_key     INTEGER,
    tc_key       INTEGER,
    opening_key  INTEGER,
    category     TEXT,
    rating_band  TEXT,
    elo          INTEGER,
    z_cv         REAL,
    acpl         REAL,
    match_rate   REAL,
    moves        SMALLINT,
    timing_pct   REAL,
    quality_pct  REAL,
    score        REAL,
    signal       TEXT,
    scored_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (game_key, side)
);
CREATE INDEX IF NOT EXISTS cheat_score_score_idx ON cheat_score (score DESC);
"""

COLS = ["game_key", "side", "game_id", "player_key", "date_key", "tc_key", "opening_key",
        "category", "rating_band", "elo", "z_cv", "acpl", "match_rate", "moves",
        "timing_pct", "quality_pct", "score", "signal"]


def get_url(cli_url):
    url = cli_url or os.environ.get("DATABASE_URL")
    if not url:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                m = re.match(r"\s*DATABASE_URL\s*=\s*(.+?)\s*$", line)
                if m:
                    url = m.group(1).strip("'\"")
    if not url:
        raise SystemExit("No DATABASE_URL (env var, .env, or --database-url).")
    return re.sub(r"^postgresql\+\w+", "postgresql", url)


def connect(url):
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError:
        import psycopg2
        return psycopg2.connect(url)


def sides_from_rows(rows):
    """Turn game_analysis rows into one record per player-side."""
    recs = []
    for gk, wpk, bpk, dk, tck, ok, wa, ba, wm, bm, wn, bn in rows:
        recs.append((gk, "white", wpk, dk, tck, ok, wa, wm, wn))
        recs.append((gk, "black", bpk, dk, tck, ok, ba, bm, bn))
    df = pd.DataFrame(recs, columns=["game_key", "side", "player_key", "date_key", "tc_key",
                                     "opening_key", "acpl", "match_rate", "moves"])
    for c in ("acpl", "match_rate", "moves"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_scores(tier1, sides):
    """Pure function: merge Tier 1 and Tier 2 and compute percentiles, score and signal."""
    t1 = tier1.copy()
    t1["side"] = t1["side"].astype(str).str.lower()
    t1["flag"] = t1["flag"].astype(str).str.lower().isin(["true", "1"])
    df = sides.merge(t1, on=["game_key", "side"], how="inner")
    df = df[(df["moves"] >= MIN_MOVES) & df["z_cv"].notna()
            & df["acpl"].notna() & df["match_rate"].notna()].copy()
    g = df.groupby(GROUP)
    df["group_n"] = g["z_cv"].transform("size")
    df["timing_pct"] = g["z_cv"].rank(pct=True, ascending=False)        # low z -> high pct
    m_pct = g["match_rate"].rank(pct=True)                              # high match -> high pct
    a_pct = g["acpl"].rank(pct=True, ascending=False)                   # low ACPL -> high pct
    df["quality_pct"] = (m_pct + a_pct) / 2
    df["score"] = (df["timing_pct"] + df["quality_pct"]) / 2
    small = df["group_n"] < MIN_GROUP
    df.loc[small, ["timing_pct", "quality_pct", "score"]] = np.nan
    q_sig = df["quality_pct"] >= QUALITY_CUT
    df["signal"] = np.select(
        [df["flag"] & q_sig, df["flag"], q_sig],
        ["both", "timing_only", "quality_only"], default="none")
    df.loc[small, "signal"] = "unscored"
    return df


def to_python(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or v is pd.NaT:
        return None
    return v.item() if hasattr(v, "item") else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    args = ap.parse_args()
    t0 = time.time()

    if not TIER1_CSV.exists():
        raise SystemExit(f"Missing {TIER1_CSV}; run mining\\cheat_tier1.py first.")
    tier1 = pd.read_csv(TIER1_CSV)
    conn = connect(get_url(args.database_url))
    cur = conn.cursor()
    cur.execute(SQL)
    sides = sides_from_rows(cur.fetchall())
    print(f"Tier 1 sides: {len(tier1):,}; Tier 2 sides: {len(sides):,}")

    df = build_scores(tier1, sides)
    print(f"Scored sides (both tiers, >= {MIN_MOVES} moves): {len(df):,} "
          f"from {df['game_key'].nunique():,} games; "
          f"unscored (small groups): {(df['signal'] == 'unscored').sum():,}")
    out = df[COLS].copy()
    CHEAT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CHEAT_DIR / "cheat_score.csv", index=False)

    rows = [tuple(to_python(v) for v in r) for r in out.itertuples(index=False, name=None)]
    placeholders = ",".join(["%s"] * len(COLS))
    cur.execute(DDL)
    cur.execute("TRUNCATE cheat_score")
    cur.executemany(f"INSERT INTO cheat_score ({','.join(COLS)}) VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()
    print(f"Wrote table cheat_score ({len(rows):,} rows) and {CHEAT_DIR / 'cheat_score.csv'}")

    pd.set_option("display.width", 200, "display.max_columns", 20)
    print("\nSignal counts:")
    print(df["signal"].value_counts().to_string())
    print("\nSpearman correlation, timing_pct vs quality_pct "
          f"(scored sides): {df['timing_pct'].corr(df['quality_pct'], method='spearman'):.3f}")
    print("\nSignal by category (share of scored sides):")
    sc = df[df["signal"] != "unscored"]
    print((pd.crosstab(sc["category"], sc["signal"], normalize="index") * 100).round(2).to_string())
    print("\nTop 10 by score (open https://lichess.org/<game_id> to inspect):")
    top = df.sort_values("score", ascending=False).head(10)
    print(top[["game_id", "side", "category", "rating_band", "elo", "z_cv", "acpl",
               "match_rate", "score", "signal"]].round(3).to_string(index=False))
    print(f"\nDone in {time.time() - t0:.0f} s. TRIAGE ranking, not proof of cheating.")


if __name__ == "__main__":
    main()
