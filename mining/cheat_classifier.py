"""Phase I: synthetic-label classifier for engine-assisted play.

MARKER: cheat_classifier v1 2026-10-17

What it does
  * Reads per-move centipawn losses and engine-match flags from `game_analysis`.
  * Negatives = real player-sides, taken as they are (assumed mostly clean).
  * Positives = a real player-side in which each move is, with probability p
    (20/40/60/80%), replaced by a perfect engine move (loss 0, match 1).
    This is feature-level substitution: no game replay, because swapping a move
    would make the opponent's recorded replies illegal.
  * Splits by GAME, so a real side and its synthetic copy never straddle
    train and test.
  * Reports AUC per substitution rate, plus TPR and precision at realistic
    prevalence (0.5% and 1%) at fixed false-positive rates.

What it does NOT show: accuracy at catching real cheaters. The labels are
synthetic, so this measures how separable *simulated* engine assistance is
from real play.

Run from the repo root:  python mining\\cheat_classifier.py
"""
import argparse
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed" / "cheat"
LEVELS = (0.2, 0.4, 0.6, 0.8)
CATS = ["Bullet", "Blitz", "Rapid", "Classical"]
MIN_MOVES = 10          # scored moves per side needed to be usable
BLUNDER = 200           # centipawn loss counted as a blunder
NEAR_PERFECT = 5        # centipawn loss counted as near-perfect
FEATURES = ["n_moves", "acpl", "match_rate", "loss_sd", "loss_median",
            "near_perfect_share", "blunders", "blunder_share", "elo"] + \
           ["cat_" + c for c in CATS]

SQL = """
SELECT ga.game_key, f.white_elo, f.black_elo, t.category,
       ga.w_losses, ga.b_losses, ga.w_hits, ga.b_hits
FROM game_analysis ga
JOIN game_fact f ON f.game_key = ga.game_key
JOIN dim_timecontrol t ON t.tc_key = f.tc_key
WHERE ga.w_losses IS NOT NULL AND ga.b_losses IS NOT NULL
"""


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


def fetch_rows(url):
    try:
        import psycopg
        conn = psycopg.connect(url)
    except ImportError:
        import psycopg2
        conn = psycopg2.connect(url)
    with conn:
        cur = conn.cursor()
        cur.execute(SQL)
        rows = cur.fetchall()
    conn.close()
    return rows


def load_sides(url):
    """One tuple per usable player-side: (game_key, elo, category, losses, hits)."""
    sides = []
    for gk, we, be, cat, wl, bl, wh, bh in fetch_rows(url):
        for elo, losses, hits in ((we, wl, wh), (be, bl, bh)):
            if elo is None or losses is None or hits is None:
                continue
            loss = np.asarray(losses, dtype=np.float32)
            hit = np.frombuffer(hits.encode("ascii"), dtype=np.uint8).astype(np.int16) - 48
            if len(loss) != len(hit) or len(loss) < MIN_MOVES:
                continue
            if hit.min() < 0 or hit.max() > 1:
                continue
            sides.append((gk, float(elo), cat, loss, hit.astype(np.float32)))
    return sides


def features(loss, hit, elo, cat):
    big = loss > BLUNDER
    return [len(loss), loss.mean(), hit.mean(), loss.std(), float(np.median(loss)),
            (loss <= NEAR_PERFECT).mean(), big.sum(), big.mean(), elo] + \
           [1.0 if cat == c else 0.0 for c in CATS]


def substitute(loss, hit, p, rng):
    mask = rng.random(len(loss)) < p
    return np.where(mask, 0.0, loss), np.where(mask, 1.0, hit)


def op_point(neg, pos, fpr_target):
    thr = np.quantile(neg, 1 - fpr_target)
    return float((pos > thr).mean()), float((neg > thr).mean())


def precision(tpr, fpr, prevalence):
    den = tpr * prevalence + fpr * (1 - prevalence)
    return tpr * prevalence / den if den > 0 else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--train-frac", type=float, default=0.7)
    args = ap.parse_args()

    t0 = time.time()
    rng = np.random.default_rng(args.seed)
    sides = load_sides(get_url(args.database_url))
    if not sides:
        raise SystemExit("No usable sides found in game_analysis.")
    games = np.array([s[0] for s in sides])
    uniq = rng.permutation(np.unique(games))
    train_games = set(uniq[: int(len(uniq) * args.train_frac)].tolist())
    is_train = np.array([g in train_games for g in games.tolist()])
    print(f"Usable player-sides: {len(sides):,} from {len(uniq):,} games "
          f"(train {is_train.sum():,} / test {(~is_train).sum():,} sides, split by game)")

    X_real = np.array([features(l, h, e, c) for _, e, c, l, h in sides], dtype=np.float64)
    print(f"Real sides: mean ACPL {X_real[:, 1].mean():.1f}, mean match {X_real[:, 2].mean():.3f}")

    # Training positives: one random substitution rate per training side
    X_pos_train = []
    for i in np.where(is_train)[0]:
        _, e, c, l, h = sides[i]
        l2, h2 = substitute(l, h, rng.choice(LEVELS), rng)
        X_pos_train.append(features(l2, h2, e, c))
    X_pos_train = np.array(X_pos_train, dtype=np.float64)
    X_train = np.vstack([X_real[is_train], X_pos_train])
    y_train = np.r_[np.zeros(is_train.sum()), np.ones(len(X_pos_train))]

    models = {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "grad_boost": HistGradientBoostingClassifier(random_state=args.seed),
    }
    for m in models.values():
        m.fit(X_train, y_train)
    print(f"Trained on {len(X_train):,} rows in {time.time() - t0:.0f} s")

    # Test: negatives = real test sides; positives = same sides at each rate p
    test_idx = np.where(~is_train)[0]
    X_neg_test = X_real[test_idx]
    rows = []
    for p in LEVELS:
        X_pos = []
        for i in test_idx:
            _, e, c, l, h = sides[i]
            l2, h2 = substitute(l, h, p, rng)
            X_pos.append(features(l2, h2, e, c))
        X_pos = np.array(X_pos, dtype=np.float64)
        for name, model in models.items():
            neg = model.predict_proba(X_neg_test)[:, 1]
            pos = model.predict_proba(X_pos)[:, 1]
            auc = roc_auc_score(np.r_[np.zeros(len(neg)), np.ones(len(pos))], np.r_[neg, pos])
            row = {"model": name, "p_substituted": p, "auc": round(auc, 4)}
            for fpr_t in (0.01, 0.001):
                tpr, fpr = op_point(neg, pos, fpr_t)
                tag = f"fpr{fpr_t * 100:g}pct"
                row[f"tpr_at_{tag}"] = round(tpr, 3)
                row[f"prec_at_{tag}_prev0.5pct"] = round(precision(tpr, fpr, 0.005), 3)
                row[f"prec_at_{tag}_prev1pct"] = round(precision(tpr, fpr, 0.01), 3)
            rows.append(row)

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 220, "display.max_columns", 20)
    print("\n" + res.to_string(index=False))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "classifier_results.csv"
    res.to_csv(out, index=False)
    print(f"\nSaved {out}  (labels are SYNTHETIC; this measures separability of simulated "
          f"assistance, not accuracy at catching real cheaters)")

    gb = models["grad_boost"]
    from sklearn.inspection import permutation_importance
    sub = rng.choice(len(X_neg_test), size=min(5000, len(X_neg_test)), replace=False)
    Xp = np.vstack([X_neg_test[sub], X_pos[sub]])
    yp = np.r_[np.zeros(len(sub)), np.ones(len(sub))]
    imp = permutation_importance(gb, Xp, yp, scoring="roc_auc", n_repeats=3,
                                 random_state=args.seed)
    order = np.argsort(-imp.importances_mean)
    print("\nPermutation importance (grad_boost, p=0.8 test sample, drop in AUC):")
    for j in order[:6]:
        print(f"  {FEATURES[j]:20s} {imp.importances_mean[j]:.4f}")
    print(f"Done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
