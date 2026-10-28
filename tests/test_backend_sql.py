"""Run every API builder against a real PostgreSQL and check the response shapes the UI needs.

No psycopg2 or FastAPI needed: db.run is replaced by a psql call.
    python tests/test_backend_sql.py --port 5432 --db chess_warehouse --user postgres [--host localhost]
(set PGPASSWORD first for a password-protected server)
"""
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import db, olap, queries, store  # noqa: E402
from backend.app.common import BadParam  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="localhost"); ap.add_argument("--port", default="5432")
ap.add_argument("--db", default="chess_warehouse"); ap.add_argument("--user", default="postgres")
ap.add_argument("--psql", default="psql")
A = ap.parse_args()


def psql_run(sql):
    wrapped = f"SELECT COALESCE(json_agg(t), '[]'::json) FROM ({sql.strip().rstrip(';')}) t"
    r = subprocess.run([A.psql, "-h", A.host, "-p", A.port, "-U", A.user, "-d", A.db, "-At", "-c", wrapped],
                       capture_output=True, text=True)
    if r.returncode:
        msg = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "psql failed"
        if "does not exist" in r.stderr and "relation" in r.stderr:
            raise db.MissingTable(msg)
        raise db.DbError(msg + "\nSQL: " + sql)
    return json.loads(r.stdout)


db.run = psql_run
import time
def timed(sql):
    t = time.perf_counter(); rows = psql_run(sql); return rows, round((time.perf_counter() - t) * 1000)
db.timed = timed

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond: fails.append(name)

def has(d, keys): return all(k in d for k in keys)
OLAP_KEYS = ["op", "title", "sql", "columns", "rows", "chart", "elapsed_ms", "note"]

for op, params in [("rollup", {}), ("rollup", {"level": "quarter"}), ("rollup", {"level": "month"}),
                   ("drilldown", {"year": "2017"}), ("drilldown", {"year": "2017", "category": "Blitz"}),
                   ("slice", {"dimension": "category", "value": "Blitz"}), ("slice", {"dimension": "year", "value": "2016"}),
                   ("slice", {"dimension": "opening_family", "value": "Ruy Lopez"}),
                   ("dice", {"categories": "Blitz,Rapid", "years": "2016,2017"}),
                   ("pivot", {"rows": "category", "cols": "rating_band", "measure": "est_games"}),
                   ("pivot", {"rows": "year", "cols": "category", "measure": "white_score"}),
                   ("pivot", {"rows": "rating_band", "cols": "quarter", "measure": "n"})]:
    try:
        r = olap.OPS[op](params)
        ok = has(r, OLAP_KEYS) and r["rows"] and all(c["key"] in r["rows"][0] for c in r["columns"])
        ch = r["chart"]; ok = ok and all(s in r["rows"][0] for s in ch["series"]) and ch["x"] in r["rows"][0]
        check(f"olap {op} {params}", ok, str(r["rows"][:1]))
    except Exception as e:  # noqa: BLE001
        check(f"olap {op} {params}", False, repr(e))

r = olap.rollup({}); check("rollup has a Total row marked is_total", any(x.get("is_total") for x in r["rows"]))
tot = [x for x in r["rows"] if x.get("is_total")][0]["est_games"]
parts = sum(x["est_games"] for x in r["rows"] if not x.get("is_total"))
# each row is ROUND()ed on its own, so allow 1 unit of rounding per row
check("rollup total equals sum of years (within rounding)", abs(tot - parts) <= len(r["rows"]), f"total={tot} sum={parts}")

for bad in [("slice", {"dimension": "category", "value": "x'; DROP TABLE game_fact;--"}), ("slice", {"dimension": "nope"}),
            ("pivot", {"rows": "year", "cols": "year"}), ("dice", {"years": "1999"}), ("rollup", {"level": "day"}),
            ("drilldown", {"year": "abc"})]:
    try: olap.OPS[bad[0]](bad[1]); check(f"rejects bad {bad}", False)
    except BadParam: check(f"rejects bad {bad}", True)
check("game_fact still exists after injection attempt", psql_run("SELECT COUNT(*) AS c FROM game_fact")[0]["c"] > 0)

o = queries.overview(); check("overview", has(o, ["kpis", "category_mix", "table_rows"]) and has(o["kpis"], ["est_games_total", "sample_games", "players", "analysed_games"]), str(o)[:200])
check("overview category_mix keys", has(o["category_mix"][0], ["category", "est_share", "sample_share", "white_score"]))
s = queries.schema(); check("schema", len(s["fact_tables"]) == 2 and s["fact_tables"][0]["dimensions"] and has(s["fact_tables"][1], ["name", "grain", "rows", "measures"]))
m = queries.monthly()["rows"]
check("monthly covers 62 months", len(m) == 62 and m[0]["month"] == "2013-01" and m[-1]["month"] == "2018-02", str(len(m)))
check("monthly gaps are null", {r["month"] for r in m if r["est_games"] is None} == {"2016-05", "2017-07"})
es = queries.explore_summary(); check("explore summary", es["rows"] and has(es["rows"][0], ["variable", "count", "mean", "std", "min", "q1", "median", "q3", "max"]))
for metric in ("acpl", "match_rate", "elo"):
    for by in ("rating_band", "category"):
        b = queries.explore_boxplot({"metric": metric, "by": by})["rows"]
        check(f"boxplot {metric}/{by}", b and has(b[0], ["group", "n", "q1", "median", "q3", "whisker_low", "whisker_high"]) and b[0]["whisker_low"] <= b[0]["q1"])
for metric in ("plies", "white_elo", "acpl"):
    h = queries.explore_histogram({"metric": metric, "bins": "30"})["bins"]
    check(f"histogram {metric}", len(h) == 30 and has(h[0], ["from", "to", "count"]) and sum(x["count"] for x in h) > 0)
sc = queries.explore_scatter({"n": "500"})["points"]; check("scatter", len(sc) == 500 and has(sc[0], ["x", "y", "category"]))
cs = queries.cheat_summary(); check("cheat summary", cs["signal_counts"] and "flag_rule" in cs["tier1"] and "pairs" in cs["tier1_validation"])
for sig in ("both", "timing_only", "quality_only", "none"):
    t = queries.cheat_top({"signal": sig, "limit": "5"})
    check(f"cheat top {sig}", has(t, ["total", "rows"]) and (not t["rows"] or has(t["rows"][0], ["game_id", "lichess_url", "category", "rating_band", "elo", "z_cv", "acpl", "match_rate", "score"])))
t = queries.cheat_top({"limit": "5"}); sc_ = [r["score"] for r in t["rows"]]
check("cheat top has no NULL scores first and is sorted", None not in sc_ and sc_ == sorted(sc_, reverse=True), str(sc_))
check("no usernames in cheat rows", not any("username" in k or "player" in k for k in t["rows"][0]))
gid = t["rows"][0]["game_id"]; g = queries.cheat_game({"game_id": gid})
check("cheat game", g and g["available"] and len(g["rows"]) == 2 and has(g["rows"][0], ["side", "timing_pct", "quality_pct", "signal"]))
check("cheat game unknown -> None (404)", queries.cheat_game({"game_id": "zzzzzzzz"}) is None)
try: queries.cheat_game({"game_id": "x"}); check("cheat game bad id", False)
except BadParam: check("cheat game bad id", True)
print("\nFAILED: " + ", ".join(fails) if fails else "\nAll checks passed.")
sys.exit(1 if fails else 0)
