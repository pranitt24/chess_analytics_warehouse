-- Indexes for OLAP queries. Created AFTER the bulk load (much faster than indexing during load).
CREATE INDEX IF NOT EXISTS ix_fact_date     ON game_fact (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_tc       ON game_fact (tc_key);
CREATE INDEX IF NOT EXISTS ix_fact_opening  ON game_fact (opening_key);
CREATE INDEX IF NOT EXISTS ix_fact_white    ON game_fact (white_player_key);
CREATE INDEX IF NOT EXISTS ix_fact_black    ON game_fact (black_player_key);
CREATE INDEX IF NOT EXISTS ix_fact_band     ON game_fact (rating_band);
CREATE INDEX IF NOT EXISTS ix_fact_tier     ON game_fact (analysis_tier);
CREATE INDEX IF NOT EXISTS ix_fact_month    ON game_fact (source_month);
