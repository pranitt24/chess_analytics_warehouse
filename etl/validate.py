"""PHASE F: warehouse validation. Prints and writes docs/etl_validation.md.

Every number in this report must be explainable before moving on to OLAP/mining.

Usage:
    python etl/validate.py
    python etl/validate.py --database-url postgresql://postgres:PW@localhost:5432/chess_dw_test
"""
import argparse

import psycopg2

from config import DATABASE_URL, DOCS_DIR


def run(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def table(cols, rows):
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join("" if v is None else (f"{v:,.3f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(out)


CHECKS = [
    ("1. Row reconciliation", """
        SELECT (SELECT count(*) FROM staging_raw_games)                  AS staging_rows,
               (SELECT count(DISTINCT game_id) FROM staging_raw_games)   AS staging_distinct_ids,
               (SELECT count(*) FROM game_fact)                          AS fact_rows,
               (SELECT count(*) FROM game_moves)                         AS moves_rows,
               (SELECT count(*) FROM dim_player)                         AS players,
               (SELECT count(*) FROM dim_opening)                        AS openings,
               (SELECT count(*) FROM dim_timecontrol)                    AS time_controls"""),
    ("2. Staging rows that did NOT reach the fact table (expect 0; duplicates across months are the only valid reason)", """
        SELECT count(*) AS missing_from_fact
        FROM (SELECT DISTINCT game_id FROM staging_raw_games) s
        LEFT JOIN game_fact f USING (game_id) WHERE f.game_id IS NULL"""),
    ("3. Orphan foreign keys (expect all 0)", """
        SELECT (SELECT count(*) FROM game_fact f WHERE NOT EXISTS (SELECT 1 FROM dim_player p WHERE p.player_key = f.white_player_key)) AS orphan_white,
               (SELECT count(*) FROM game_fact f WHERE NOT EXISTS (SELECT 1 FROM dim_player p WHERE p.player_key = f.black_player_key)) AS orphan_black,
               (SELECT count(*) FROM game_fact f WHERE NOT EXISTS (SELECT 1 FROM dim_time t WHERE t.date_key = f.date_key))             AS orphan_date,
               (SELECT count(*) FROM game_fact f WHERE NOT EXISTS (SELECT 1 FROM dim_timecontrol t WHERE t.tc_key = f.tc_key))          AS orphan_tc,
               (SELECT count(*) FROM game_fact f WHERE NOT EXISTS (SELECT 1 FROM dim_opening o WHERE o.opening_key = f.opening_key))    AS orphan_opening,
               (SELECT count(*) - count(DISTINCT game_id) FROM game_fact)                                                              AS duplicate_game_ids"""),
    ("4. Time-control bucket consistency: Python stratum vs SQL dimension (expect 0 mismatches)", """
        SELECT count(*) AS mismatches
        FROM staging_raw_games s JOIN dim_timecontrol t ON t.time_control = s.time_control
        WHERE split_part(s.stratum, '|', 1) <> t.category"""),
    ("5. Rows per year and tier", """
        SELECT t.year, f.analysis_tier AS tier, count(*) AS games,
               round(sum(f.sample_weight)::numeric, 0) AS est_population_games
        FROM game_fact f JOIN dim_time t USING (date_key)
        GROUP BY t.year, f.analysis_tier ORDER BY t.year, tier"""),
    ("6. Null / availability rates by year (matches Phase B expectations?)", """
        SELECT t.year,
               count(*) AS games,
               round(100.0 * avg(has_clk::int), 1)                    AS pct_with_clock,
               round(100.0 * avg(has_eval::int), 1)                   AS pct_with_eval,
               round(100.0 * avg((termination IS NOT NULL)::int), 1)  AS pct_termination,
               round(100.0 * avg((white_rating_diff IS NOT NULL)::int), 1) AS pct_rating_diff
        FROM game_fact f JOIN dim_time t USING (date_key) GROUP BY t.year ORDER BY t.year"""),
    ("7. Time-control mix: sample vs weighted estimate of the population", """
        SELECT tc.category, count(*) AS sample_games,
               round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS sample_pct,
               round((100.0 * sum(f.sample_weight) / sum(sum(f.sample_weight)) OVER ())::numeric, 1) AS weighted_pct
        FROM game_fact f JOIN dim_timecontrol tc USING (tc_key)
        GROUP BY tc.category ORDER BY sample_games DESC"""),
    ("8. Sanity: White score by time control (expect roughly 0.50 to 0.55; weighted removes sampling skew)", """
        SELECT tc.category, count(*) AS games,
               round(avg(f.white_score)::numeric, 3) AS white_score_unweighted,
               round((sum(f.white_score * f.sample_weight) / sum(f.sample_weight))::numeric, 3) AS white_score_weighted
        FROM game_fact f JOIN dim_timecontrol tc USING (tc_key)
        GROUP BY tc.category ORDER BY tc.category"""),
    ("9. Sanity: plies and Elo ranges (no impossible values)", """
        SELECT min(plies) AS min_plies, round(avg(plies), 1) AS avg_plies, max(plies) AS max_plies,
               min(white_elo) AS min_elo, max(white_elo) AS max_elo
        FROM game_fact"""),
    ("10. Months with the fewest sampled games (coverage check)", """
        SELECT source_month, count(*) AS games FROM game_fact GROUP BY source_month ORDER BY games LIMIT 5"""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=DATABASE_URL)
    args = ap.parse_args()
    conn = psycopg2.connect(args.database_url.replace("postgresql+psycopg2://", "postgresql://"))
    cur = conn.cursor()
    md = ["# ETL validation report (Phase F)", ""]
    for title, sql in CHECKS:
        cols, rows = run(cur, sql)
        block = table(cols, rows)
        print(f"\n## {title}\n{block}")
        md += [f"## {title}", "", block, ""]
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "etl_validation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\nWrote docs/etl_validation.md")
    conn.close()


if __name__ == "__main__":
    main()
