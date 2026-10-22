# API requests

## GET /api/cheat/game?game_id=<8 chars>
Used by the "Check a game" box on the Cheat triage page.
Returns the same row shape as /api/cheat/top, one row per side (white, black), no usernames:
{"available": true, "game_id": "v5QwS0a3", "rows": [{side, category, rating_band, elo, z_cv, acpl, match_rate, timing_pct, quality_pct, score, signal}]}
If the game has no analysis, return 404 {"detail": "No analysis for this game (only about 51,000 games from 2017-2018 are scored)."}
