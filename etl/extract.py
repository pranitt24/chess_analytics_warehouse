"""PHASE C + E1/E2: stratified, reproducible sampling extractor.

One streaming pass per monthly .pgn.zst file, one file per worker process. For each month:
  1. Apply filter rules (rated standard, both Elo present, normal termination, valid result, >= min plies,
     real time control i.e. not correspondence).
  2. Assign every qualifying game to a stratum = <Bullet|Blitz|Rapid|Classical> x <rating band>.
  3. Keep at most --per-cell games per stratum using reservoir sampling (Algorithm R): a uniform random
     sample of each stratum in ONE pass with bounded memory, no need to know the stratum size in advance.
  4. Record, for every kept game, how many qualifying games its stratum had (stratum_seen) and how many
     were kept (stratum_kept). sample_weight = seen / kept lets us estimate population totals later.

Reproducible: the RNG is seeded from "<seed>:<month>", so the same files + same seed give the same sample.
Resumable: a finished month writes data/processed/staging/<month>.csv; re-runs skip it (use --force).

Output: one CSV per month, columns = STAGING_COLS (see pgn_stream.py), ready for etl/load_warehouse.py.

Usage (PowerShell, repo root, venv active):
    # 5k-game smoke test on the first month (takes seconds):
    python etl/extract.py --months 2013-01 --max-games 5000 --per-cell 50 --out data\\processed\\staging_test
    # full run:
    python etl/extract.py --per-cell 800 --workers 12
"""
import argparse
import csv
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from config import PROCESSED_DIR, RAW_DIR, SEED, STAGING_DIR
from pgn_stream import (DATE_RE, FILE_RE, SITE_RE, STAGING_COLS, TIME_RE, clock_stats, count_plies,
                        iter_games, month_of, parse_tc, rating_band, san_moves, tc_category)

BAD_TERMINATION = {b"Abandoned", b"Rules infraction", b"Unterminated"}
GOOD_RESULT = {b"1-0", b"0-1", b"1/2-1/2"}


def build_row(month, hdr, mt, plies, tc, game_id, stratum, seen, kept):
    def d(key):
        return hdr.get(key, b"").decode("utf-8", "replace")

    utc_date = d(b"UTCDate") or d(b"Date")
    if not DATE_RE.match(utc_date):
        utc_date = ""
    utc_time = d(b"UTCTime")
    if not TIME_RE.match(utc_time):
        utc_time = ""
    cs = clock_stats(mt, tc[0], tc[1])
    f = lambda x: "" if x is None else f"{x:.3f}"
    return [
        game_id.decode("ascii"), month, d(b"Event"), d(b"Site"), d(b"White"), d(b"Black"), d(b"Result"),
        utc_date, utc_time, d(b"WhiteElo"), d(b"BlackElo"), d(b"WhiteRatingDiff"), d(b"BlackRatingDiff"),
        d(b"ECO"), d(b"Opening"), d(b"TimeControl"), d(b"Termination"), plies,
        "t" if b"%clk" in mt else "f", "t" if b"%eval" in mt else "f",
        f(cs[0]) if cs else "", f(cs[1]) if cs else "", f(cs[2]) if cs else "", f(cs[3]) if cs else "",
        stratum, seen, kept, b" ".join(san_moves(mt)).decode("ascii", "replace"),
    ]


def process_month(job):
    path, out_dir, per_cell, min_plies, seed, max_games = job
    t0 = time.time()
    month = month_of(path)
    rng = random.Random(f"{seed}:{month}")
    cells = {}            # stratum -> [reservoir list, seen counter]
    drops = Counter()
    read = passed = 0

    for hdr, mt in iter_games(path, limit=max_games):
        read += 1
        if b"Rated" not in hdr.get(b"Event", b""):
            drops["not_rated"] += 1
            continue
        var = hdr.get(b"Variant")
        if var is not None and var != b"Standard":
            drops["variant"] += 1
            continue
        tc = parse_tc(hdr.get(b"TimeControl", b""))
        if tc is None:
            drops["no_time_control"] += 1
            continue
        we, be = hdr.get(b"WhiteElo", b""), hdr.get(b"BlackElo", b"")
        if not (we.isdigit() and be.isdigit()):
            drops["no_elo"] += 1
            continue
        if hdr.get(b"Result") not in GOOD_RESULT:
            drops["bad_result"] += 1
            continue
        if hdr.get(b"Termination") in BAD_TERMINATION:
            drops["bad_termination"] += 1
            continue
        m = SITE_RE.search(hdr.get(b"Site", b""))
        if not m:
            drops["no_game_id"] += 1
            continue
        plies = count_plies(mt)
        if plies < min_plies:
            drops["too_short"] += 1
            continue

        passed += 1
        stratum = f"{tc_category(*tc)}|{rating_band((int(we) + int(be)) / 2)}"
        cell = cells.get(stratum)
        if cell is None:
            cell = cells[stratum] = [[], 0]
        cell[1] += 1
        item = (hdr, mt, plies, tc, m.group(1))
        if len(cell[0]) < per_cell:
            cell[0].append(item)
        else:
            j = rng.randrange(cell[1])
            if j < per_cell:
                cell[0][j] = item

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{month}.csv"
    tmp = out_dir / f"{month}.csv.tmp"
    kept = 0
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(STAGING_COLS)
        for stratum in sorted(cells):
            items, seen = cells[stratum]
            for hdr, mt, plies, tc, gid in items:
                w.writerow(build_row(month, hdr, mt, plies, tc, gid, stratum, seen, len(items)))
                kept += 1
    os.replace(tmp, final)      # atomic: a half-written month never looks finished
    return dict(month=month, read=read, passed=passed, kept=kept, strata=len(cells),
                drops=dict(drops), secs=time.time() - t0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(RAW_DIR))
    ap.add_argument("--out", default=str(STAGING_DIR))
    ap.add_argument("--per-cell", type=int, default=800, help="max games kept per (month, time-control, rating-band)")
    ap.add_argument("--min-plies", type=int, default=10, help="drop games shorter than this many half-moves")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--workers", type=int, default=12, help="parallel files; each worker can use 1-2 GB RAM")
    ap.add_argument("--months", nargs="*", help="only these YYYY-MM months")
    ap.add_argument("--max-games", type=int, default=None, help="stop after N games per file (smoke tests)")
    ap.add_argument("--force", action="store_true", help="re-do months that already have an output CSV")
    args = ap.parse_args()

    files = []
    for p in Path(args.raw).iterdir():
        mm = FILE_RE.search(p.name)
        if mm:
            files.append((f"{mm.group(1)}-{mm.group(2)}", p))
    if not files:
        sys.exit(f"No lichess_db_standard_rated_*.pgn.zst files in {args.raw}")
    if args.months:
        files = [x for x in files if x[0] in set(args.months)]

    out = Path(args.out)
    todo = [(m, p) for m, p in files if args.force or not (out / f"{m}.csv").exists()]
    todo.sort(key=lambda x: x[1].stat().st_size, reverse=True)   # biggest first = best load balancing
    print(f"{len(files)} files selected, {len(files) - len(todo)} already done, {len(todo)} to process "
          f"| per-cell={args.per_cell} min-plies={args.min_plies} seed={args.seed} workers={args.workers}")
    if not todo:
        print("Nothing to do (use --force to redo).")
        return

    jobs = [(str(p), str(out), args.per_cell, args.min_plies, args.seed, args.max_games) for _, p in todo]
    report_path = Path(PROCESSED_DIR) / "extract_report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    new_report = not report_path.exists()
    t_all = time.time()
    tot_read = tot_kept = 0
    with open(report_path, "a", newline="", encoding="utf-8") as rf, \
            ProcessPoolExecutor(max_workers=min(args.workers, len(jobs))) as ex:
        rw = csv.writer(rf)
        if new_report:
            rw.writerow(["month", "games_read", "passed_filters", "kept", "strata", "seconds", "drops"])
        futs = [ex.submit(process_month, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            tot_read += r["read"]
            tot_kept += r["kept"]
            rw.writerow([r["month"], r["read"], r["passed"], r["kept"], r["strata"], f"{r['secs']:.0f}", r["drops"]])
            rf.flush()
            print(f"[{i}/{len(jobs)}] {r['month']}  read={r['read']:,}  passed={r['passed']:,}  "
                  f"kept={r['kept']:,}  strata={r['strata']}  {r['secs']:.0f}s  "
                  f"({r['read'] / max(r['secs'], 1e-9):,.0f} games/s)", flush=True)
    print(f"\nDONE in {(time.time() - t_all) / 60:.1f} min | read {tot_read:,} games | kept {tot_kept:,} rows")
    print(f"CSVs in {out}  |  per-month report: {report_path}")


if __name__ == "__main__":
    main()
