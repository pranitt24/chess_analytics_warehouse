"""Overview, schema, monthly series, exploration and cheat-triage queries."""
import re

from . import db
from .common import BANDS, CATEGORIES, BadParam, SIGNALS, int_param, float_param, lit, pick
from .store import tier1_validation

CAT_ORDER = "CASE tc.category WHEN 'Bullet' THEN 1 WHEN 'Blitz' THEN 2 WHEN 'Rapid' THEN 3 ELSE 4 END"
GAP_MONTHS = ["2016-05", "2017-07"]


def _count(table):
    try:
        return db.run(f"SELECT COUNT(*) AS c FROM {table}")[0]["c"]
    except db.MissingTable:
        return None


def overview():
    k = db.run("SELECT ROUND(SUM(sample_weight::float8))::bigint AS est, COUNT(*) AS n, "
               "COUNT(*) FILTER (WHERE has_clk) AS clk, COUNT(DISTINCT source_month) AS months "
               "FROM game_fact")[0]
    try:
        analysed = db.run("SELECT COUNT(*) AS c FROM game_analysis WHERE w_acpl IS NOT NULL")[0]["c"]
    except db.MissingTable:
        analysed = 0
    mix = db.run(
        "SELECT tc.category, SUM(f.sample_weight::float8) / SUM(SUM(f.sample_weight::float8)) OVER () AS est_share,\n"
        "       COUNT(*)::float / SUM(COUNT(*)) OVER () AS sample_share,\n"
        "       SUM(f.white_score * f.sample_weight::float8) / SUM(f.sample_weight::float8) AS white_score\n"
        "FROM game_fact f JOIN dim_timecontrol tc ON tc.tc_key = f.tc_key\n"
        f"GROUP BY tc.category ORDER BY {CAT_ORDER}")
    for r in mix:
        for key, nd in (("est_share", 4), ("sample_share", 4), ("white_score", 3)):
            r[key] = round(float(r[key]), nd)
    tables = ["game_fact", "game_moves", "game_analysis", "cheat_score", "dim_player", "dim_opening",
              "dim_timecontrol", "dim_time"]
    trows = [{"table": t, "rows": c} for t in tables if (c := _count(t)) is not None]
    return {"kpis": {"est_games_total": k["est"], "sample_games": k["n"], "players": _count("dim_player"),
                     "months_covered": k["months"], "clock_games": k["clk"], "analysed_games": analysed},
            "category_mix": mix, "table_rows": trows}


def schema():
    n = {t: _count(t) for t in ("game_fact", "cheat_score", "dim_player", "dim_time", "dim_timecontrol", "dim_opening")}
    return {
        "fact_tables": [
            {"name": "game_fact", "grain": "one row per sampled game", "rows": n["game_fact"],
             "dimensions": ["dim_player (white)", "dim_player (black)", "dim_time", "dim_timecontrol", "dim_opening"],
             "measures": [
                 {"name": "plies", "additive": True, "note": "weight by sample_weight for population totals"},
                 {"name": "sample_weight", "additive": True, "note": "sums to the estimated number of real games"},
                 {"name": "white_score", "additive": False, "note": "needs sample_weight to aggregate"},
                 {"name": "white_elo / black_elo", "additive": False, "note": "average, never sum"},
                 {"name": "w_avg_move_time", "additive": False, "note": "only where clocks exist"}]},
            {"name": "cheat_score", "grain": "one row per game and side (white or black)", "rows": n["cheat_score"],
             "dimensions": ["dim_player", "dim_time", "dim_timecontrol", "dim_opening"],
             "measures": [
                 {"name": "score", "additive": False, "note": "percentile based, triage only"},
                 {"name": "acpl", "additive": False, "note": "average centipawn loss"},
                 {"name": "match_rate", "additive": False, "note": "share of moves equal to the engine's first choice"},
                 {"name": "z_cv", "additive": False, "note": "robust z-score of move-time variability"}]}],
        "dimensions": [{"name": "dim_player", "rows": n["dim_player"]}, {"name": "dim_time", "rows": n["dim_time"]},
                       {"name": "dim_timecontrol", "rows": n["dim_timecontrol"]},
                       {"name": "dim_opening", "rows": n["dim_opening"]}]}


def monthly():
    rows = db.run("SELECT t.year, t.month, ROUND(SUM(f.sample_weight::float8))::bigint AS est\n"
                  "FROM game_fact f JOIN dim_time t ON t.date_key = f.date_key GROUP BY t.year, t.month")
    have = {f"{r['year']}-{r['month']:02d}": r["est"] for r in rows}
    src = {r["m"] for r in db.run("SELECT DISTINCT source_month AS m FROM game_fact")}
    out = []
    for y in range(2013, 2019):
        for m in range(1, 13):
            key = f"{y}-{m:02d}"
            if key > "2018-02":
                break
            # a month with no source file is a gap, even if a few games carry that UTC date
            gap = key not in src
            out.append({"month": key, "est_games": None if gap else have.get(key), "gap": gap})
    return {"rows": out}


# ---------------- exploration ----------------
SRC = {  # metric -> (table alias source, column)
    "acpl": ("cheat_score", "acpl"), "match_rate": ("cheat_score", "match_rate"), "elo": ("cheat_score", "elo"),
    "z_cv": ("cheat_score", "z_cv"), "plies": ("game_fact", "plies"), "white_elo": ("game_fact", "white_elo"),
    "black_elo": ("game_fact", "black_elo"), "avg_elo": ("game_fact", "avg_elo")}


def _src(metric):
    t, c = SRC[metric]
    return t, c, f"SELECT {c}::float8 AS v FROM {t} WHERE {c} IS NOT NULL"


def explore_summary():
    rows = []
    for m in ("white_elo", "black_elo", "plies", "acpl", "match_rate"):
        t, c, src = _src(m)
        try:
            r = db.run(f"SELECT COUNT(*) AS count, AVG(v) AS mean, STDDEV_SAMP(v) AS std, MIN(v) AS min,\n"
                       "percentile_cont(0.25) WITHIN GROUP (ORDER BY v) AS q1,\n"
                       "percentile_cont(0.5) WITHIN GROUP (ORDER BY v) AS median,\n"
                       "percentile_cont(0.75) WITHIN GROUP (ORDER BY v) AS q3, MAX(v) AS max\n"
                       f"FROM ({src}) x")[0]
        except db.MissingTable:
            continue
        rows.append({"variable": m, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}})
    return {"rows": rows}


def explore_boxplot(p):
    metric = pick(p, "metric", "acpl", ["acpl", "match_rate", "elo"])
    by = pick(p, "by", "rating_band", ["rating_band", "category"])
    c = SRC[metric][1]
    sql = (f"WITH x AS (SELECT {by} AS grp, {c}::float8 AS v FROM cheat_score WHERE {c} IS NOT NULL AND {by} IS NOT NULL),\n"
           "s AS (SELECT grp, COUNT(*) AS n, MIN(v) AS mn, MAX(v) AS mx,\n"
           "      percentile_cont(0.25) WITHIN GROUP (ORDER BY v) AS q1,\n"
           "      percentile_cont(0.5) WITHIN GROUP (ORDER BY v) AS median,\n"
           "      percentile_cont(0.75) WITHIN GROUP (ORDER BY v) AS q3 FROM x GROUP BY grp)\n"
           "SELECT s.grp AS \"group\", s.n, s.mn AS min, s.q1, s.median, s.q3, s.mx AS max,\n"
           "  (SELECT MIN(v) FROM x WHERE x.grp = s.grp AND v >= s.q1 - 1.5 * (s.q3 - s.q1)) AS whisker_low,\n"
           "  (SELECT MAX(v) FROM x WHERE x.grp = s.grp AND v <= s.q3 + 1.5 * (s.q3 - s.q1)) AS whisker_high\n"
           "FROM s")
    rows = db.run(sql)
    order = BANDS if by == "rating_band" else CATEGORIES
    rows.sort(key=lambda r: order.index(r["group"]) if r["group"] in order else 99)
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float):
                r[k] = round(v, 3)
    return {"rows": rows}


def explore_histogram(p):
    metric = pick(p, "metric", "plies", ["plies", "white_elo", "acpl", "match_rate"])
    bins = int_param(p, "bins", 30, 5, 100)
    _, _, src = _src(metric)
    sql = (f"WITH x AS ({src}),\nr AS (SELECT percentile_cont(0.01) WITHIN GROUP (ORDER BY v) AS lo,\n"
           "      percentile_cont(0.99) WITHIN GROUP (ORDER BY v) AS hi FROM x)\n"
           f"SELECT LEAST(GREATEST(FLOOR((x.v - r.lo) / NULLIF((r.hi - r.lo) / {bins}, 0)), 0), {bins - 1})::int AS b,\n"
           f"       COUNT(*) AS count, MIN(r.lo) AS lo, MIN(r.hi) AS hi\nFROM x, r GROUP BY 1 ORDER BY 1")
    rows = db.run(sql)
    if not rows:
        return {"bins": []}
    lo, hi = rows[0]["lo"], rows[0]["hi"]
    w = (hi - lo) / bins
    cnt = {r["b"]: r["count"] for r in rows}
    d = 3 if metric == "match_rate" else 1
    return {"bins": [{"from": round(lo + i * w, d), "to": round(lo + (i + 1) * w, d), "count": cnt.get(i, 0)}
                     for i in range(bins)],
            "note": "Range is the 1st to 99th percentile; values outside are counted in the end bins."}


def explore_scatter(p):
    x = pick(p, "x", "elo", ["elo", "acpl", "match_rate", "z_cv"])
    y = pick(p, "y", "acpl", ["elo", "acpl", "match_rate", "z_cv"])
    n = int_param(p, "n", 2000, 100, 5000)
    rows = db.run(f"SELECT {x} AS x, {y} AS y, category FROM cheat_score\n"
                  f"WHERE {x} IS NOT NULL AND {y} IS NOT NULL ORDER BY random() LIMIT {n}")
    for r in rows:
        r["x"], r["y"] = round(r["x"], 3), round(r["y"], 3)
    return {"points": rows}


# ---------------- cheat triage (never exposes usernames) ----------------
SIDE_COLS = ("side, category, rating_band, elo, ROUND(z_cv::numeric, 2) AS z_cv, ROUND(acpl::numeric, 1) AS acpl, "
             "ROUND(match_rate::numeric, 3) AS match_rate, ROUND(timing_pct::numeric, 3) AS timing_pct, "
             "ROUND(quality_pct::numeric, 3) AS quality_pct, ROUND(score::numeric, 3) AS score, signal")


def cheat_summary():
    rows = db.run("SELECT signal, COUNT(*) AS count FROM cheat_score GROUP BY signal")
    rows.sort(key=lambda r: SIGNALS.index(r["signal"]) if r["signal"] in SIGNALS else 99)
    return {"signal_counts": rows,
            "tier1": {"flag_rule": "robust z-score of log(CV of move times) <= -3 within (category, rating band)"},
            "tier1_validation": tier1_validation()}


def cheat_top(p):
    where = []
    if p.get("signal"):
        where.append(f"signal = {lit(pick(p, 'signal', None, SIGNALS))}")
    if p.get("category"):
        where.append(f"category = {lit(pick(p, 'category', None, CATEGORIES))}")
    if p.get("band"):
        where.append(f"rating_band = {lit(pick(p, 'band', None, BANDS))}")
    if p.get("min_score"):
        where.append(f"score >= {float_param(p, 'min_score', 0, 0, 1)}")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    limit, offset = int_param(p, "limit", 25, 1, 200), int_param(p, "offset", 0, 0, 10**6)
    total = db.run(f"SELECT COUNT(*) AS c FROM cheat_score {w}")[0]["c"]
    rows = db.run(f"SELECT game_id, {SIDE_COLS} FROM cheat_score {w} ORDER BY score DESC NULLS LAST, game_id "
                  f"LIMIT {limit} OFFSET {offset}")
    for r in rows:
        r["lichess_url"] = f"https://lichess.org/{r['game_id']}"
    return {"total": total, "rows": rows}


def cheat_game(p):
    gid = str(p.get("game_id", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8}", gid):
        raise BadParam("game_id must be the 8-character Lichess game ID.")
    rows = db.run(f"SELECT {SIDE_COLS} FROM cheat_score WHERE game_id = {lit(gid)} ORDER BY side DESC")
    return {"available": True, "game_id": gid, "rows": rows} if rows else None
