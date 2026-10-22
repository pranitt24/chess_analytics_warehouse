"""PHASE B: data profiling on small streamed samples (never decompresses a whole file).

Streams the first N games of selected months (default: first available month of each year + the last
file) and records which headers exist, how common clock/eval annotations are, and basic distributions.
Writes docs/data_profile.md.

Caveat to state in the report: the first N games of a month are from the first hours of day 1, so this is
a quick look at FIELD AVAILABILITY, not an unbiased distribution of the whole month.

Usage:
    python etl/profile.py                       # default months, 20000 games each
    python etl/profile.py --games 5000
    python etl/profile.py --months 2013-01 2015-06 2018-02
"""
import argparse
import statistics
import time
from collections import Counter, defaultdict

from config import DOCS_DIR, RAW_DIR
from pgn_stream import FILE_RE, count_plies, iter_games, parse_tc, tc_category

KEY_HEADERS = ["Event", "Site", "Date", "UTCDate", "UTCTime", "White", "Black", "Result", "WhiteElo",
               "BlackElo", "WhiteRatingDiff", "BlackRatingDiff", "WhiteTitle", "BlackTitle", "ECO",
               "Opening", "TimeControl", "Termination", "Variant"]


def default_months(files):
    by_year = {}
    for m in sorted(files):
        by_year.setdefault(m[:4], m)
    chosen = list(by_year.values())
    last = sorted(files)[-1]
    if last not in chosen:
        chosen.append(last)
    return chosen


def profile_month(path, n_games):
    present = Counter()
    clk = ev = rated = 0
    tc_cat, term, result, event = Counter(), Counter(), Counter(), Counter()
    plies, elos = [], []
    n = 0
    t0 = time.time()
    for hdr, mt in iter_games(path, limit=n_games, wanted=None):
        n += 1
        for k in hdr:
            present[k.decode("ascii", "replace")] += 1
        if b"%clk" in mt:
            clk += 1
        if b"%eval" in mt:
            ev += 1
        e = hdr.get(b"Event", b"")
        event[e.split(b" ")[1].decode("ascii", "replace") if e.startswith(b"Rated") and b" " in e else "other"] += 1
        tc = parse_tc(hdr.get(b"TimeControl", b""))
        tc_cat[tc_category(*tc) if tc else "none/-"] += 1
        term[hdr.get(b"Termination", b"(absent)").decode("utf-8", "replace")] += 1
        result[hdr.get(b"Result", b"(absent)").decode("utf-8", "replace")] += 1
        plies.append(count_plies(mt))
        for k in (b"WhiteElo", b"BlackElo"):
            v = hdr.get(k, b"")
            if v.isdigit():
                elos.append(int(v))
    return dict(n=n, present=present, clk=clk, eval=ev, tc=tc_cat, term=term, result=result, event=event,
                plies=plies, elos=elos, secs=time.time() - t0)


def pct(a, n):
    return f"{100 * a / n:.0f}%" if n else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW_DIR))
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--months", nargs="*")
    args = ap.parse_args()

    from pathlib import Path
    files = {}
    for p in Path(args.raw).iterdir():
        m = FILE_RE.search(p.name)
        if m:
            files[f"{m.group(1)}-{m.group(2)}"] = p
    if not files:
        raise SystemExit(f"No lichess_db_standard_rated_*.pgn.zst files in {args.raw}")
    months = args.months or default_months(files)

    results = {}
    for m in months:
        if m not in files:
            print(f"skip {m}: file not found")
            continue
        print(f"profiling {m} ...", flush=True)
        results[m] = profile_month(files[m], args.games)
        r = results[m]
        print(f"  {r['n']} games in {r['secs']:.1f}s | clk {pct(r['clk'], r['n'])} | eval {pct(r['eval'], r['n'])}")

    ms = list(results)
    L = ["# Data profile (Phase B)", "",
         f"Streamed the first {args.games} games of each sampled month. These are the first hours of the "
         "month's first day, so this shows **field availability**, not the month's overall distribution.", "",
         "## Header availability (% of sampled games that contain the header)", "",
         "| Header | " + " | ".join(ms) + " |", "|---|" + "---|" * len(ms)]
    all_keys = list(KEY_HEADERS) + sorted({k for m in ms for k in results[m]["present"]} - set(KEY_HEADERS))
    for k in all_keys:
        L.append(f"| {k} | " + " | ".join(pct(results[m]["present"].get(k, 0), results[m]["n"]) for m in ms) + " |")

    L += ["", "## Move annotations", "", "| Month | Games with `%clk` | Games with `%eval` |", "|---|---|---|"]
    for m in ms:
        r = results[m]
        L.append(f"| {m} | {pct(r['clk'], r['n'])} | {pct(r['eval'], r['n'])} |")

    L += ["", "## Distributions", ""]
    for m in ms:
        r = results[m]
        pl = r["plies"]
        L += [f"### {m}  (n={r['n']})", "",
              f"- Time-control category: " + ", ".join(f"{k} {pct(v, r['n'])}" for k, v in r["tc"].most_common()),
              f"- Termination: " + ", ".join(f"{k} {pct(v, r['n'])}" for k, v in r["term"].most_common()),
              f"- Result: " + ", ".join(f"{k} {pct(v, r['n'])}" for k, v in r["result"].most_common()),
              f"- Event type: " + ", ".join(f"{k} {pct(v, r['n'])}" for k, v in r["event"].most_common(6)),
              f"- Plies per game: median {statistics.median(pl):.0f}, mean {statistics.mean(pl):.1f}, "
              f"share under 10 plies {pct(sum(1 for x in pl if x < 10), len(pl))}" if pl else "- no games",
              f"- Elo: min {min(r['elos'])}, median {statistics.median(r['elos']):.0f}, max {max(r['elos'])}"
              if r["elos"] else "- no Elo values", ""]

    L += ["## Which features are usable, per year", "",
          "| Year | Month sampled | Clock timing features | Embedded evals | Termination | Rating diffs | ECO/Opening |",
          "|---|---|---|---|---|---|---|"]
    for m in ms:
        r, n = results[m], results[m]["n"]
        pr = r["present"]
        L.append(f"| {m[:4]} | {m} | {'yes' if r['clk'] / n > 0.5 else ('partial' if r['clk'] else 'no')} "
                 f"({pct(r['clk'], n)}) | {'some' if r['eval'] else 'none'} ({pct(r['eval'], n)}) | "
                 f"{'yes' if pr.get('Termination', 0) / n > 0.9 else 'no/partial'} | "
                 f"{'yes' if pr.get('WhiteRatingDiff', 0) / n > 0.9 else 'no/partial'} | "
                 f"{'yes' if pr.get('Opening', 0) / n > 0.9 and pr.get('ECO', 0) / n > 0.9 else 'no/partial'} |")

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "data_profile.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\nWrote docs/data_profile.md")


if __name__ == "__main__":
    main()
