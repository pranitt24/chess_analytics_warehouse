-- =====================================================================
-- E2 + E3: staging -> dimensions -> fact.  Idempotent: re-running adds nothing new.
-- Executed by etl/load_warehouse.py as ONE transaction (all or nothing).
-- =====================================================================

-- Players ---------------------------------------------------------------
INSERT INTO dim_player (username)
SELECT DISTINCT u
FROM (SELECT white AS u FROM staging_raw_games
      UNION ALL
      SELECT black FROM staging_raw_games) x
WHERE u IS NOT NULL
ON CONFLICT (username) DO NOTHING;

-- Time controls: bucket by Lichess estimated duration = base + 40 * increment ---
INSERT INTO dim_timecontrol (time_control, base_seconds, increment_seconds, est_duration_seconds, category)
SELECT tc, base, inc, base + 40 * inc,
       CASE WHEN base + 40 * inc <= 179  THEN 'Bullet'
            WHEN base + 40 * inc <= 479  THEN 'Blitz'
            WHEN base + 40 * inc <= 1499 THEN 'Rapid'
            ELSE 'Classical' END
FROM (SELECT DISTINCT time_control AS tc,
             split_part(time_control, '+', 1)::int AS base,
             split_part(time_control, '+', 2)::int AS inc
      FROM staging_raw_games
      WHERE time_control ~ '^[0-9]+\+[0-9]+$') t
ON CONFLICT (time_control) DO NOTHING;

-- Openings: built from the (ECO, Opening) pairs actually present in the headers ---
INSERT INTO dim_opening (eco, opening_name, opening_family, eco_group)
SELECT DISTINCT
       COALESCE(eco, '?'),
       COALESCE(opening, 'Unknown'),
       trim(split_part(COALESCE(opening, 'Unknown'), ':', 1)),
       COALESCE(left(eco, 1), '?')
FROM staging_raw_games
ON CONFLICT (eco, opening_name) DO NOTHING;

-- Fact ----------------------------------------------------------------------
INSERT INTO game_fact (
    game_id, white_player_key, black_player_key, date_key, tc_key, opening_key,
    result, white_score, white_elo, black_elo, avg_elo, elo_diff, rating_band,
    white_rating_diff, black_rating_diff, termination, plies, has_clk, has_eval,
    w_avg_move_time, b_avg_move_time, w_move_time_sd, b_move_time_sd,
    first_moves, sample_weight, analysis_tier, source_month)
SELECT
    s.game_id, pw.player_key, pb.player_key, dt.date_key, tc.tc_key, o.opening_key,
    s.result,
    CASE s.result WHEN '1-0' THEN 1.0 WHEN '0-1' THEN 0.0 ELSE 0.5 END,
    s.white_elo::smallint, s.black_elo::smallint,
    (s.white_elo::int + s.black_elo::int) / 2.0,
    (s.white_elo::int - s.black_elo::int)::smallint,
    split_part(s.stratum, '|', 2),
    s.white_rating_diff::smallint, s.black_rating_diff::smallint,
    s.termination, s.plies, COALESCE(s.has_clk, FALSE), COALESCE(s.has_eval, FALSE),
    s.w_avg_move_time, s.b_avg_move_time, s.w_move_time_sd, s.b_move_time_sd,
    array_to_string((string_to_array(s.moves_san, ' '))[1:10], ' '),
    s.stratum_seen::real / NULLIF(s.stratum_kept, 0),
    1,
    s.source_month
FROM staging_raw_games s
JOIN dim_player      pw ON pw.username     = s.white
JOIN dim_player      pb ON pb.username     = s.black
JOIN dim_timecontrol tc ON tc.time_control = s.time_control
JOIN dim_opening     o  ON o.eco = COALESCE(s.eco, '?') AND o.opening_name = COALESCE(s.opening, 'Unknown')
JOIN dim_time        dt ON dt.full_date =
        COALESCE(to_date(s.utc_date, 'YYYY.MM.DD'), to_date(s.source_month || '-01', 'YYYY-MM-DD'))
ON CONFLICT (game_id) DO NOTHING;

-- Moves -----------------------------------------------------------------------
INSERT INTO game_moves (game_key, moves_san)
SELECT f.game_key, s.moves_san
FROM staging_raw_games s
JOIN game_fact f ON f.game_id = s.game_id
WHERE s.moves_san IS NOT NULL
ON CONFLICT (game_key) DO NOTHING;
