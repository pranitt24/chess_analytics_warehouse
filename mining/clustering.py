"""Phase H2: k-means clustering of games.

Features (available for every game): log(time-control length), average Elo,
absolute Elo gap, plies, ended-on-time flag. Fit on a WEIGHTED resample
(probability proportional to sample_weight) so clusters describe real Lichess.
k is chosen by silhouette over --k-min..--k-max unless --k is given.

Usage (from repo root):
    python mining\\clustering.py
    python mining\\clustering.py --k 5
Needs: pip install scikit-learn pandas numpy psycopg[binary]
"""
import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed" / "mining"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--draws", type=int, default=200_000)
    ap.add_argument("--k", type=int)
    ap.add_argument("--k-min", type=int, default=3)
    ap.add_argument("--k-max", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    sql = """
        SELECT tc.est_duration_seconds, f.avg_elo, f.elo_diff, f.plies, f.termination,
               f.white_score, tc.category, t.year, f.sample_weight
        FROM game_fact f
        JOIN dim_timecontrol tc ON tc.tc_key = f.tc_key
        JOIN dim_time t ON t.date_key = f.date_key
    """
    with connect(get_url(a.database_url)) as con, con.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    cols = ["duration", "avg_elo", "elo_diff", "plies", "termination",
            "white_score", "category", "year", "w"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["duration", "avg_elo", "elo_diff", "plies", "white_score", "w"]:
        df[c] = pd.to_numeric(df[c])
    df = df.dropna(subset=["duration", "avg_elo", "elo_diff", "plies"])
    print(f"Loaded {len(df):,} games")

    rng = np.random.default_rng(a.seed)
    idx = rng.choice(len(df), size=a.draws, replace=True, p=df["w"] / df["w"].sum())
    s = df.iloc[idx].reset_index(drop=True)

    s["log_duration"] = np.log(s["duration"].clip(lower=1))
    s["abs_elo_diff"] = s["elo_diff"].abs()
    s["forfeit"] = (s["termination"] == "Time forfeit").astype(float)
    feats = ["log_duration", "avg_elo", "abs_elo_diff", "plies", "forfeit"]
    X = StandardScaler().fit_transform(s[feats])

    if a.k:
        k = a.k
    else:
        sub = rng.choice(len(X), size=min(20_000, len(X)), replace=False)
        best, k = -1.0, a.k_min
        print("\nk selection (silhouette on 20k subsample):")
        for kk in range(a.k_min, a.k_max + 1):
            km = KMeans(n_clusters=kk, n_init=5, random_state=a.seed).fit(X)
            sil = silhouette_score(X[sub], km.labels_[sub])
            print(f"  k={kk}  inertia={km.inertia_:,.0f}  silhouette={sil:.3f}")
            if sil > best:
                best, k = sil, kk
        print(f"Chosen k = {k}")

    km = KMeans(n_clusters=k, n_init=10, random_state=a.seed).fit(X)
    s["cluster"] = km.labels_

    prof = s.groupby("cluster").agg(
        pct_games=("cluster", lambda x: 100 * len(x) / len(s)),
        avg_elo=("avg_elo", "mean"),
        abs_elo_diff=("abs_elo_diff", "mean"),
        plies=("plies", "mean"),
        median_duration_s=("duration", "median"),
        pct_forfeit=("forfeit", lambda x: 100 * x.mean()),
        white_score=("white_score", "mean"),
    )
    mix = pd.crosstab(s["cluster"], s["category"], normalize="index") * 100
    prof = prof.join(mix.add_prefix("pct_"))
    prof = prof.round(1).assign(white_score=prof["white_score"].round(3))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"cluster_profile_k{k}.csv"
    prof.to_csv(path)
    print(f"\nCluster profile (k={k}), weighted resample, written to {path}\n")
    print(prof.to_string())


if __name__ == "__main__":
    main()
