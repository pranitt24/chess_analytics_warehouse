-- =====================================================================
-- Chess Analytics Warehouse: schema (PostgreSQL 14+)
-- Safe to re-run: everything is IF NOT EXISTS / ON CONFLICT DO NOTHING.
--
-- Layers
--   1. staging_raw_games : landing table, one row per sampled game, mirrors the extract CSVs
--   2. dim_*             : star-schema dimensions
--   3. game_fact         : one row per game (Tier 1 = header-level, Tier 2 = engine-enriched later)
--   4. game_moves        : wide move text kept OUT of the fact table to keep scans fast
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. STAGING (raw layer). Header fields stay TEXT so bad data never blocks a load;
--    typing/cleaning happens in db/transform.sql.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS staging_raw_games (
    game_id            TEXT,
    source_month       TEXT,
    event              TEXT,
    site               TEXT,
    white              TEXT,
    black              TEXT,
    result             TEXT,
    utc_date           TEXT,
    utc_time           TEXT,
    white_elo          TEXT,
    black_elo          TEXT,
    white_rating_diff  TEXT,
    black_rating_diff  TEXT,
    eco                TEXT,
    opening            TEXT,
    time_control       TEXT,
    termination        TEXT,
    plies              INT,
    has_clk            BOOLEAN,
    has_eval           BOOLEAN,
    w_avg_move_time    REAL,
    b_avg_move_time    REAL,
    w_move_time_sd     REAL,
    b_move_time_sd     REAL,
    stratum            TEXT,      -- "<TimeControlCategory>|<RatingBand>", the sampling cell
    stratum_seen       INT,       -- qualifying games in that cell for that month (population)
    stratum_kept       INT,       -- games kept from that cell (sample)
    moves_san          TEXT
);

-- ---------------------------------------------------------------------
-- 2. DIMENSIONS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_time (
    date_key      INT PRIMARY KEY,          -- YYYYMMDD
    full_date     DATE UNIQUE NOT NULL,
    year          SMALLINT NOT NULL,
    quarter       SMALLINT NOT NULL,
    month         SMALLINT NOT NULL,
    month_name    TEXT NOT NULL,
    day           SMALLINT NOT NULL,
    day_of_week   SMALLINT NOT NULL,        -- 1 = Monday ... 7 = Sunday (ISO)
    day_name      TEXT NOT NULL,
    is_weekend    BOOLEAN NOT NULL
);

INSERT INTO dim_time
SELECT to_char(d, 'YYYYMMDD')::int, d::date,
       extract(year    FROM d)::smallint,
       extract(quarter FROM d)::smallint,
       extract(month   FROM d)::smallint,
       trim(to_char(d, 'Month')),
       extract(day     FROM d)::smallint,
       extract(isodow  FROM d)::smallint,
       trim(to_char(d, 'Day')),
       extract(isodow  FROM d) IN (6, 7)
FROM generate_series('2013-01-01'::timestamp, '2018-12-31'::timestamp, interval '1 day') AS d
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS dim_timecontrol (
    tc_key                SERIAL PRIMARY KEY,
    time_control          TEXT UNIQUE NOT NULL,   -- raw header, e.g. "300+3"
    base_seconds          INT NOT NULL,
    increment_seconds     INT NOT NULL,
    est_duration_seconds  INT NOT NULL,           -- base + 40 * increment (Lichess convention)
    category              TEXT NOT NULL CHECK (category IN ('Bullet','Blitz','Rapid','Classical'))
);

CREATE TABLE IF NOT EXISTS dim_opening (
    opening_key     SERIAL PRIMARY KEY,
    eco             TEXT NOT NULL,                -- e.g. "B90"
    opening_name    TEXT NOT NULL,                -- e.g. "Sicilian Defense: Najdorf Variation"
    opening_family  TEXT NOT NULL,                -- text before the first ':' e.g. "Sicilian Defense"
    eco_group       TEXT NOT NULL,                -- A..E (or '?')
    UNIQUE (eco, opening_name)
);
INSERT INTO dim_opening (eco, opening_name, opening_family, eco_group)
VALUES ('?', 'Unknown', 'Unknown', '?')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS dim_player (
    player_key  SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL
);

-- ---------------------------------------------------------------------
-- 3. FACT
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_fact (
    game_key           BIGSERIAL PRIMARY KEY,
    game_id            TEXT UNIQUE NOT NULL,      -- natural key from the Site header (dedup + idempotent loads)
    white_player_key   INT NOT NULL REFERENCES dim_player(player_key),
    black_player_key   INT NOT NULL REFERENCES dim_player(player_key),
    date_key           INT NOT NULL REFERENCES dim_time(date_key),
    tc_key             INT NOT NULL REFERENCES dim_timecontrol(tc_key),
    opening_key        INT NOT NULL REFERENCES dim_opening(opening_key),
    result             TEXT NOT NULL CHECK (result IN ('1-0','0-1','1/2-1/2')),
    white_score        NUMERIC(2,1) NOT NULL,     -- 1, 0.5 or 0 (white's point)
    white_elo          SMALLINT NOT NULL,
    black_elo          SMALLINT NOT NULL,
    avg_elo            REAL NOT NULL,
    elo_diff           SMALLINT NOT NULL,         -- white_elo - black_elo
    rating_band        TEXT NOT NULL,
    white_rating_diff  SMALLINT,                  -- nullable: absent in some years
    black_rating_diff  SMALLINT,
    termination        TEXT,                      -- nullable: absent in some years
    plies              SMALLINT NOT NULL,
    has_clk            BOOLEAN NOT NULL DEFAULT FALSE,
    has_eval           BOOLEAN NOT NULL DEFAULT FALSE,
    w_avg_move_time    REAL,                      -- seconds, only where clocks exist
    b_avg_move_time    REAL,
    w_move_time_sd     REAL,
    b_move_time_sd     REAL,
    first_moves        TEXT,                      -- first 10 plies, for opening association rules
    sample_weight      REAL NOT NULL,             -- inverse inclusion probability (population / sample in its cell)
    analysis_tier      SMALLINT NOT NULL DEFAULT 1,  -- 1 = header-level, 2 = engine-enriched
    source_month       TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- 4. MOVES (kept separate from the fact table)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_moves (
    game_key   BIGINT PRIMARY KEY REFERENCES game_fact(game_key) ON DELETE CASCADE,
    moves_san  TEXT NOT NULL
);
