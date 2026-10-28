"""OLAP operations on the star schema. Each builder returns the response the UI expects:
{op, title, sql, columns, rows, chart, elapsed_ms, note}.
All counts are weighted estimates: est_games = SUM(sample_weight)."""
from . import db
from .common import (BANDS, CATEGORIES, BadParam, col, csv_list, ident, int_param, lit, pick)

BASE = ("FROM game_fact f\n"
        "JOIN dim_time t         ON t.date_key = f.date_key\n"
        "JOIN dim_timecontrol tc ON tc.tc_key  = f.tc_key")
OPEN = "\nJOIN dim_opening o      ON o.opening_key = f.opening_key"

# dimension name -> (SQL expression, allowed values or None, kind)
DIMS = {
    "category": ("tc.category", CATEGORIES, "text"),
    "rating_band": ("f.rating_band", BANDS, "text"),
    "year": ("t.year", None, "int"),
    "quarter": ("t.quarter", [1, 2, 3, 4], "int"),
    "is_weekend": ("t.is_weekend", None, "bool"),
    "opening_family": ("o.opening_family", None, "text"),
    "eco_group": ("o.eco_group", None, "text"),
    "termination": ("f.termination", None, "text"),
}
PIVOT_DIMS = ["category", "rating_band", "year", "quarter"]

M_EST = "ROUND(SUM(f.sample_weight::float8))::bigint AS est_games"
M_WS = "ROUND((SUM(f.white_score * f.sample_weight::float8) / SUM(f.sample_weight::float8))::numeric, 3) AS white_score"
M_PLY = "ROUND((SUM(f.plies * f.sample_weight::float8) / SUM(f.sample_weight::float8))::numeric, 1) AS avg_plies"
NOTE = "Counts are weighted estimates (SUM of sample_weight); n is the number of sampled games behind each row."


def _from(*exprs):
    return BASE + (OPEN if any(e.startswith("o.") for e in exprs) else "")


def _coerce(dim, value):
    expr, allowed, kind = DIMS[dim]
    if kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise BadParam(f"{dim} must be an integer")
        if allowed and v not in allowed:
            raise BadParam(f"{dim} must be one of {allowed}")
        return v
    if kind == "bool":
        if str(value).lower() not in ("true", "false", "1", "0", "yes", "no"):
            raise BadParam("is_weekend must be true or false")
        return str(value).lower() in ("true", "1", "yes")
    v = str(value)
    if allowed and v not in allowed:
        raise BadParam(f"{dim} must be one of {allowed}")
    return v


def _done(op, title, sql, columns, rows, ms, chart, note=NOTE):
    return {"op": op, "title": title, "sql": sql, "columns": columns, "rows": rows,
            "chart": chart, "elapsed_ms": ms, "note": note}


EST_COLS = [col("est_games", "Est. games", "integer"), col("white_score", "White score", "number"),
            col("n", "Sample n", "integer")]


def rollup(p):
    level = pick(p, "level", "year", ["year", "quarter", "month"])
    cols, label = {
        "year": (["t.year"], "t.year::text"),
        "quarter": (["t.year", "t.quarter"], "t.year || ' Q' || t.quarter"),
        "month": (["t.year", "t.month"], "t.year || '-' || LPAD(t.month::text, 2, '0')"),
    }[level]
    g = ", ".join(cols)
    sql = (f"SELECT CASE WHEN GROUPING({g}) = {(1 << len(cols)) - 1} THEN 'Total' ELSE {label} END AS period,\n"
           f"       {M_EST},\n       {M_WS},\n       COUNT(*) AS n\n{_from()}\n"
           f"GROUP BY ROLLUP (({g}))\nORDER BY GROUPING({g}), {g};")
    rows, ms = db.timed(sql)
    for r in rows:
        r["is_total"] = r["period"] == "Total"
    return _done("rollup", f"Roll-up: estimated games by {level}", sql,
                 [col("period", level.capitalize())] + EST_COLS, rows, ms,
                 {"type": "bar" if level == "year" else "line", "x": "period", "series": ["est_games"]})


def drilldown(p):
    year = int_param(p, "year", 2017, 2013, 2018)
    cat = p.get("category")
    if cat:
        cat = pick(p, "category", None, CATEGORIES)
        sql = (f"SELECT o.opening_family,\n       {M_EST},\n       {M_WS},\n       COUNT(*) AS n\n{_from('o.x')}\n"
               f"WHERE t.year = {year} AND tc.category = {lit(cat)}\n"
               f"GROUP BY o.opening_family\nORDER BY SUM(f.sample_weight::float8) DESC\nLIMIT 15;")
        rows, ms = db.timed(sql)
        return _done("drilldown", f"Drill-down: top opening families, {cat}, {year}", sql,
                     [col("opening_family", "Opening family")] + EST_COLS, rows, ms,
                     {"type": "bar", "x": "opening_family", "series": ["est_games"]})
    sql = (f"SELECT tc.category,\n       {M_EST},\n       {M_WS},\n       COUNT(*) AS n\n{_from()}\n"
           f"WHERE t.year = {year}\nGROUP BY tc.category\n"
           f"ORDER BY CASE tc.category WHEN 'Bullet' THEN 1 WHEN 'Blitz' THEN 2 WHEN 'Rapid' THEN 3 ELSE 4 END;")
    rows, ms = db.timed(sql)
    return _done("drilldown", f"Drill-down: year {year} into time-control category", sql,
                 [col("category", "Category")] + EST_COLS, rows, ms,
                 {"type": "bar", "x": "category", "series": ["est_games"]},
                 NOTE + " Add category=Blitz to the parameters to drill one level further, into opening families.")


def slice_(p):
    dim = pick(p, "dimension", "category", list(DIMS))
    value = _coerce(dim, p.get("value", "Blitz"))
    expr = DIMS[dim][0]
    grp, glabel = ("t.year", "Year") if dim != "year" else ("tc.category", "Category")
    sql = (f"SELECT {grp}::text AS {ident(grp.split('.')[1])},\n       {M_EST},\n       {M_WS},\n"
           f"       {M_PLY},\n       COUNT(*) AS n\n{_from(expr, grp)}\n"
           f"WHERE {expr} = {lit(value)}\nGROUP BY {grp}\nORDER BY {grp};")
    rows, ms = db.timed(sql)
    key = grp.split(".")[1]
    return _done("slice", f"Slice: {dim} = {value}", sql,
                 [col(key, glabel)] + EST_COLS[:2] + [col("avg_plies", "Avg plies", "number"), EST_COLS[2]], rows, ms,
                 {"type": "line" if key == "year" else "bar", "x": key, "series": ["est_games"]})


def dice(p):
    cats = csv_list(p, "categories", "Blitz,Rapid", CATEGORIES)
    years = csv_list(p, "years", "2016,2017", None, int)
    for y in years:
        if not 2013 <= y <= 2018:
            raise BadParam("years must be between 2013 and 2018")
    where = [f"tc.category IN ({', '.join(lit(c) for c in cats)})", f"t.year IN ({', '.join(map(str, years))})"]
    if p.get("bands"):
        bands = csv_list(p, "bands", "", BANDS)
        where.append(f"f.rating_band IN ({', '.join(lit(b) for b in bands)})")
    cols_sql = ",\n       ".join(
        f"ROUND(SUM(f.sample_weight::float8) FILTER (WHERE tc.category = {lit(c)}))::bigint AS {ident(c)}" for c in cats)
    sql = (f"SELECT t.year::text AS year,\n       {cols_sql},\n       COUNT(*) AS n\n{_from()}\n"
           f"WHERE {' AND '.join(where)}\nGROUP BY t.year\nORDER BY t.year;")
    rows, ms = db.timed(sql)
    return _done("dice", f"Dice: {', '.join(cats)} in {', '.join(map(str, years))}", sql,
                 [col("year", "Year")] + [col(c, c, "integer") for c in cats] + [EST_COLS[2]], rows, ms,
                 {"type": "bar", "x": "year", "series": cats})


def _values(dim):
    expr, allowed, _ = DIMS[dim]
    if allowed:
        return list(allowed)
    return [r["v"] for r in db.run(f"SELECT DISTINCT {expr} AS v FROM dim_time t ORDER BY 1")]


def pivot(p):
    rdim = pick(p, "rows", "category", PIVOT_DIMS)
    cdim = pick(p, "cols", "rating_band", PIVOT_DIMS)
    if rdim == cdim:
        raise BadParam("rows and cols must be different dimensions")
    measure = pick(p, "measure", "est_games", ["est_games", "white_score", "avg_plies", "n"])
    rexpr, cexpr = DIMS[rdim][0], DIMS[cdim][0]
    cvals = _values(cdim)
    ctext = f"{cexpr}::text"

    def cell(v):
        flt = f"FILTER (WHERE {ctext} = {lit(str(v))})"
        if measure == "est_games":
            return f"ROUND(SUM(f.sample_weight::float8) {flt})::bigint"
        if measure == "n":
            return f"COUNT(*) {flt}"
        num = "f.white_score" if measure == "white_score" else "f.plies"
        return f"ROUND((SUM({num} * f.sample_weight::float8) {flt} / NULLIF(SUM(f.sample_weight::float8) {flt}, 0))::numeric, 3)"

    cols_sql = ",\n       ".join(f"{cell(v)} AS {ident(v)}" for v in cvals)
    sql = (f"SELECT {rexpr}::text AS {ident(rdim)},\n       {cols_sql},\n       COUNT(*) AS n\n{_from()}\n"
           f"GROUP BY {rexpr}\nORDER BY {rexpr};")
    rows, ms = db.timed(sql)
    ctype = "integer" if measure in ("est_games", "n") else "number"
    return _done("pivot", f"Pivot: {measure} with {rdim} as rows and {cdim} as columns", sql,
                 [col(rdim, rdim)] + [col(str(v), str(v), ctype) for v in cvals] + [EST_COLS[2]], rows, ms,
                 {"type": "stacked_bar" if measure == "est_games" else "bar", "x": rdim,
                  "series": [str(v) for v in cvals]})


OPS = {"rollup": rollup, "drilldown": drilldown, "slice": slice_, "dice": dice, "pivot": pivot}
