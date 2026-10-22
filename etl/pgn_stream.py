"""Streaming PGN reader and small parsing helpers.

Design notes (worth knowing for the viva):
* Files are read as a STREAM from .zst. Nothing is ever decompressed to disk.
* We work on bytes, not str. Roughly 99% of games are discarded by the sampler, so skipping UTF-8
  decoding for them is a large speed-up. We only decode the games we keep.
* We do not use python-chess here. Full move validation costs ~100x more per game and the warehouse
  stage only needs headers, a ply count and clock comments. python-chess is used later (Tier 2 / Stockfish).
"""
import io
import re
from pathlib import Path

import zstandard

FILE_RE = re.compile(r"lichess_db_standard_rated_(\d{4})-(\d{2})\.pgn\.zst$")

# Column order of the extract CSVs == column order of staging_raw_games
STAGING_COLS = [
    "game_id", "source_month", "event", "site", "white", "black", "result", "utc_date", "utc_time",
    "white_elo", "black_elo", "white_rating_diff", "black_rating_diff", "eco", "opening",
    "time_control", "termination", "plies", "has_clk", "has_eval",
    "w_avg_move_time", "b_avg_move_time", "w_move_time_sd", "b_move_time_sd",
    "stratum", "stratum_seen", "stratum_kept", "moves_san",
]

WANTED = {
    b"Event", b"Site", b"Date", b"UTCDate", b"UTCTime", b"White", b"Black", b"Result",
    b"WhiteElo", b"BlackElo", b"WhiteRatingDiff", b"BlackRatingDiff", b"ECO", b"Opening",
    b"TimeControl", b"Termination", b"Variant",
}


def month_of(path) -> str:
    m = FILE_RE.search(Path(path).name)
    return f"{m.group(1)}-{m.group(2)}" if m else Path(path).stem


def iter_games(path, limit=None, wanted=WANTED):
    """Yield (headers: dict[bytes, bytes], movetext: bytes) for each game in a .pgn.zst file.

    wanted=None keeps every header (used by the profiler). limit stops after N games.
    """
    n = 0
    with open(path, "rb") as fh:
        # Lichess files use a very large zstd window, so the default max window is too small.
        dctx = zstandard.ZstdDecompressor(max_window_size=2 ** 31)
        with dctx.stream_reader(fh) as reader:
            stream = io.BufferedReader(reader, buffer_size=1 << 20)
            headers = {}
            move_lines = []
            for line in stream:
                if line[:1] == b"[":
                    parts = line.split(b'"', 2)
                    key = parts[0][1:].strip()
                    # A new header after movetext (or a second [Event) means the previous game is complete.
                    if move_lines or (key == b"Event" and headers):
                        yield headers, b" ".join(move_lines)
                        n += 1
                        if limit is not None and n >= limit:
                            return
                        headers = {}
                        move_lines = []
                    if len(parts) == 3 and (wanted is None or key in wanted):
                        headers[key] = parts[1]
                else:
                    s = line.strip()
                    if s:
                        move_lines.append(s)
            if headers:
                yield headers, b" ".join(move_lines)


# ----------------------------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------------------------
TC_RE = re.compile(rb"^(\d+)\+(\d+)$")
SITE_RE = re.compile(rb"lichess\.org/([A-Za-z0-9]+)")
COMMENT_RE = re.compile(rb"\{[^}]*\}")
CLK_RE = re.compile(rb"\[%clk (\d+):(\d{2}):(\d{2}(?:\.\d+)?)\]")
DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def parse_tc(value: bytes):
    """b'300+3' -> (300, 3). Correspondence ('-') and malformed values -> None."""
    m = TC_RE.match(value)
    return (int(m.group(1)), int(m.group(2))) if m else None


def tc_category(base: int, inc: int) -> str:
    """Lichess convention: estimated duration = base + 40 * increment (seconds).
    UltraBullet is folded into Bullet, so we get the four categories the project asks for."""
    est = base + 40 * inc
    if est <= 179:
        return "Bullet"
    if est <= 479:
        return "Blitz"
    if est <= 1499:
        return "Rapid"
    return "Classical"


def rating_band(avg_elo: float) -> str:
    if avg_elo < 1200:
        return "<1200"
    if avg_elo < 1500:
        return "1200-1499"
    if avg_elo < 1800:
        return "1500-1799"
    if avg_elo < 2100:
        return "1800-2099"
    if avg_elo < 2400:
        return "2100-2399"
    return "2400+"


def count_plies(movetext: bytes) -> int:
    """Count SAN move tokens: tokens whose first byte is a letter.
    Move numbers (1., 12...), results (1-0, 1/2-1/2, *), NAGs ($1) and clock/eval comment fragments
    ([%clk, 0:03:00], 0.17]) all start with a non-letter, so no comment stripping is needed."""
    return sum(1 for t in movetext.split() if 97 <= (t[0] | 32) <= 122)


def san_moves(movetext: bytes):
    if b"{" in movetext:
        movetext = COMMENT_RE.sub(b" ", movetext)
    return [t for t in movetext.split() if 97 <= (t[0] | 32) <= 122]


def clock_stats(movetext: bytes, base: int, inc: int):
    """Average and std-dev of seconds spent per move for White and Black, or None if no clocks.
    time_spent = previous_clock - current_clock + increment (first move: base - clock + increment)."""
    if b"%clk" not in movetext:
        return None
    clks = [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in CLK_RE.findall(movetext)]
    if len(clks) < 6:
        return None
    res = []
    for side in (clks[0::2], clks[1::2]):
        prev = float(base)
        spent = []
        for c in side:
            spent.append(max(prev - c + inc, 0.0))
            prev = c
        mean = sum(spent) / len(spent)
        sd = (sum((x - mean) ** 2 for x in spent) / len(spent)) ** 0.5
        res.append((mean, sd))
    (wm, wsd), (bm, bsd) = res
    return wm, bm, wsd, bsd
