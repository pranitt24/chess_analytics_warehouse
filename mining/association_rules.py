"""Phase H1: association rules on opening move sequences.

Items are ply-tagged moves ("1.e4", "1...c5", "2.Nf3") so the same SAN move at a
different ply or colour is a different item. Baskets come from a WEIGHTED resample
(probability proportional to sample_weight) so supports describe real Lichess
games, not the stratified sample. Only "predictive" rules are kept: a single
consequent move that is played AFTER every move in the antecedent.

Usage (from repo root):
    python mining\\association_rules.py
    python mining\\association_rules.py --category Blitz --min-elo 2000
Needs: pip install mlxtend pandas numpy psycopg[binary]   (or psycopg2)
"""
import argparse
import os
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from mlxtend.frequent_patterns import association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder

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


def basket(moves):
    items = []
    for i, m in enumerate(moves.split()):
        m = m.rstrip("+#")
        n = i // 2 + 1
        items.append(f"{n}.{m}" if i % 2 == 0 else f"{n}...{m}")
    return items


def ply(item):
    head, rest = item.split(".", 1)
    n = int(head)
    return 2 * n if rest.startswith("..") else 2 * n - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--draws", type=int, default=300_000, help="weighted resample size")
    ap.add_argument("--min-support", type=float, default=0.003)
    ap.add_argument("--min-conf", type=float, default=0.5)
    ap.add_argument("--min-lift", type=float, default=1.2)
    ap.add_argument("--max-len", type=int, default=5)
    ap.add_argument("--category", choices=["Bullet", "Blitz", "Rapid", "Classical"])
    ap.add_argument("--min-elo", type=int)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    sql = ("SELECT f.first_moves, f.sample_weight FROM game_fact f "
           "JOIN dim_timecontrol tc ON tc.tc_key = f.tc_key "
           "WHERE f.first_moves IS NOT NULL")
    params = []
    if a.category:
        sql += " AND tc.category = %s"
        params.append(a.category)
    if a.min_elo:
        sql += " AND f.avg_elo >= %s"
        params.append(a.min_elo)

    with connect(get_url(a.database_url)) as con, con.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    moves = [r[0] for r in rows]
    w = np.array([float(r[1]) for r in rows])
    print(f"Loaded {len(rows):,} games")

    rng = np.random.default_rng(a.seed)
    idx = rng.choice(len(rows), size=a.draws, replace=True, p=w / w.sum())
    uniq = {i: basket(moves[i]) for i in set(idx.tolist())}
    baskets = [uniq[i] for i in idx]

    # drop items that can never reach min_support (keeps the matrix small)
    cnt = Counter(it for b in baskets for it in b)
    keep = {it for it, c in cnt.items() if c / a.draws >= a.min_support}
    baskets = [[it for it in b if it in keep] for b in baskets]
    print(f"{len(keep):,} items reach support >= {a.min_support}")

    te = TransactionEncoder()
    onehot = pd.DataFrame(te.fit(baskets).transform(baskets), columns=te.columns_)

    freq = fpgrowth(onehot, min_support=a.min_support, use_colnames=True, max_len=a.max_len)
    print(f"{len(freq):,} frequent itemsets")

    try:
        rules = association_rules(freq, num_itemsets=len(onehot),
                                  metric="confidence", min_threshold=a.min_conf)
    except TypeError:
        rules = association_rules(freq, metric="confidence", min_threshold=a.min_conf)

    rules = rules[rules["lift"] >= a.min_lift]
    rules = rules[rules["consequents"].apply(len) == 1]
    rules = rules[rules.apply(
        lambda r: ply(next(iter(r["consequents"]))) > max(ply(x) for x in r["antecedents"]),
        axis=1)]

    # full_prefix: antecedent is the ENTIRE move history before the consequent
    rules = rules.assign(full_prefix=rules.apply(
        lambda r: {ply(x) for x in r["antecedents"]}
        == set(range(1, ply(next(iter(r["consequents"]))))), axis=1))

    out = rules.copy()
    out["antecedents"] = out["antecedents"].apply(lambda s: " ".join(sorted(s, key=ply)))
    out["consequents"] = out["consequents"].apply(lambda s: next(iter(s)))
    out = out[["antecedents", "consequents", "support", "confidence", "lift", "full_prefix"]]
    out = out.sort_values(["lift", "support"], ascending=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = "_".join(x for x in [a.category, f"elo{a.min_elo}" if a.min_elo else None] if x) or "all"
    path = OUT_DIR / f"assoc_rules_{tag}.csv"
    out.to_csv(path, index=False)
    print(f"{len(out):,} predictive rules written to {path}")
    fp = out[out["full_prefix"]]
    print(f"\n{len(fp):,} of these are full-prefix rules (opening-tree reading).")
    print("Full-prefix rules, support >= 0.01, top 20 by confidence:")
    print(fp[fp["support"] >= 0.01].sort_values("confidence", ascending=False).head(20)
          .to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nTop 15 by lift:")
    print(out.head(15).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    print("\nTop 15 by support:")
    print(out.sort_values("support", ascending=False).head(15)
          .to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
