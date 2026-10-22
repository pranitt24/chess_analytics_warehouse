"""Phase I, Tier 2 benchmark: replay games through Stockfish and measure throughput.

Per game and side it computes:
  * ACPL  : average centipawn loss of the played moves vs the engine's best
  * match : share of moves equal to the engine's top choice
over plies >= --skip-plies (opening theory excluded). One analysis per position:
loss_i = max(0, score_i + score_{i+1}) where scores are from the side-to-move
point of view. Scores are capped at +-1000 cp (mate treated as 10000 then capped).

Games come from the clock-bearing population (has_clk), the population Tier 2
will use. Selection is deterministic for a given --seed.

Usage (from repo root; run on its own, it uses many CPU cores):
    python mining\\stockfish_benchmark.py
    python mining\\stockfish_benchmark.py --games 400 --depth 14 --workers 12
Needs: pip install chess
"""
import argparse
import multiprocessing as mp
import os
import time
from pathlib import Path

import chess
import chess.engine

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed" / "cheat"
DEFAULT_ENGINE = (r"C:\Users\student\AppData\Local\Microsoft\WinGet\Packages"
                  r"\Stockfish.Stockfish_Microsoft.Winget.Source_8wekyb3d8bbwe"
                  r"\stockfish\stockfish-windows-x86-64-universal.exe")
CAP = 1000
RESULT_TOKENS = {"1-0", "0-1", "1/2-1/2", "*"}


def get_url(cli_url):
    if cli_url:
        return cli_url
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("No DATABASE_URL. Fix .env at the repo root or pass --database-url.")


def connect(url):
    try:
        import psycopg
        return psycopg.connect(url)
    except ImportError:
        import psycopg2
        return psycopg2.connect(url)


def score_pos(engine, board, limit, game):
    """Return (score for side to move capped to +-CAP, best move or None)."""
    if board.is_checkmate():
        return -CAP, None
    if board.is_game_over():
        return 0, None
    info = engine.analyse(board, limit, game=game)
    cp = info["score"].pov(board.turn).score(mate_score=10000)
    cp = max(-CAP, min(CAP, cp))
    pv = info.get("pv")
    return cp, (pv[0] if pv else None)


def analyse_game(engine, limit, game_id, moves_san, skip):
    board = chess.Board()
    moves, scores, best = [], {}, {}
    for tok in moves_san.split():
        if "." in tok or tok in RESULT_TOKENS:
            continue
        tok = tok.rstrip("?!")
        i = len(moves)
        if i >= skip:
            scores[i], best[i] = score_pos(engine, board, limit, game_id)
        try:
            mv = board.parse_san(tok)
        except ValueError:
            return {"error": f"ply {i + 1}: {tok}"}
        moves.append(mv)
        board.push(mv)
    n = len(moves)
    if n <= skip:
        return {"error": "too short"}
    scores[n], _ = score_pos(engine, board, limit, game_id)

    loss = {"w": [], "b": []}
    match = {"w": [], "b": []}
    for i in range(skip, n):
        side = "w" if i % 2 == 0 else "b"
        loss[side].append(min(CAP, max(0, scores[i] + scores[i + 1])))
        match[side].append(1 if best[i] == moves[i] else 0)

    def mean(x):
        return sum(x) / len(x) if x else None

    return {"w_acpl": mean(loss["w"]), "b_acpl": mean(loss["b"]),
            "w_match": mean(match["w"]), "b_match": mean(match["b"]),
            "w_moves": len(loss["w"]), "b_moves": len(loss["b"]),
            "positions": len(scores),
            "w_losses": loss["w"], "b_losses": loss["b"],
            "w_hits": "".join(map(str, match["w"])), "b_hits": "".join(map(str, match["b"]))}


def work(task):
    chunk, path, depth, hash_mb, skip = task
    out = []
    engine = chess.engine.SimpleEngine.popen_uci(path)
    try:
        engine.configure({"Threads": 1, "Hash": hash_mb})
        limit = chess.engine.Limit(depth=depth)
        for gid, san in chunk:
            out.append((gid, analyse_game(engine, limit, gid, san, skip)))
    finally:
        engine.quit()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url")
    ap.add_argument("--engine", default=os.getenv("STOCKFISH_PATH", DEFAULT_ENGINE))
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--hash-mb", type=int, default=64)
    ap.add_argument("--skip-plies", type=int, default=10)
    ap.add_argument("--chunk", type=int, default=5)
    ap.add_argument("--seed", default="42")
    a = ap.parse_args()

    if not Path(a.engine).exists():
        raise SystemExit(f"Stockfish not found at {a.engine}. Pass --engine <path>.")

    sql = ("SELECT f.game_id, m.moves_san, f.rating_band FROM game_fact f "
           "JOIN game_moves m ON m.game_key = f.game_key "
           "WHERE f.has_clk ORDER BY md5(f.game_id || %s) LIMIT %s")
    with connect(get_url(a.database_url)) as con, con.cursor() as cur:
        cur.execute(sql, (a.seed, a.games))
        games = cur.fetchall()
    print(f"Loaded {len(games)} clock-bearing games; depth {a.depth}, {a.workers} workers")

    band = {g: b for g, _, b in games}
    pairs = [(g, s) for g, s, _ in games]
    tasks = [(pairs[i:i + a.chunk], a.engine, a.depth, a.hash_mb, a.skip_plies)
             for i in range(0, len(pairs), a.chunk)]

    t0 = time.time()
    results = []
    with mp.Pool(a.workers) as pool:
        for batch in pool.imap_unordered(work, tasks):
            results.extend(batch)
            print(f"  {len(results)}/{len(games)} games, {time.time() - t0:.0f}s", end="\r")
    wall = time.time() - t0
    print()

    ok = [(g, r) for g, r in results if r is not None and "error" not in r]
    errors = [(g, r["error"]) for g, r in results if r is not None and "error" in r]
    failed = len(results) - len(ok)
    positions = sum(r["positions"] for _, r in ok)
    gpm = len(ok) / wall * 60

    def avg(key):
        v = [r[key] for _, r in ok if r[key] is not None]
        return sum(v) / len(v) if v else float("nan")

    print(f"\nGames analysed: {len(ok)} ok, {failed} failed to parse/replay")
    for g, e in errors[:8]:
        print(f"  failed {g}: {e}")
    print(f"Positions analysed: {positions:,} in {wall:.0f}s "
          f"({positions / wall:.0f} positions/s, {gpm:.1f} games/min)")
    print(f"Projected time at this depth: 20,000 games = {20000 / gpm / 60:.1f} h, "
          f"50,000 games = {50000 / gpm / 60:.1f} h")
    print(f"Mean ACPL: white {avg('w_acpl'):.1f}, black {avg('b_acpl'):.1f}")
    print(f"Mean engine top-move match: white {avg('w_match'):.3f}, black {avg('b_match'):.3f}")
    print("\nACPL / match by rating band (should FALL / RISE with rating if the replay logic is right):")
    for bd in ["<1200", "1200-1499", "1500-1799", "1800-2099", "2100-2399", "2400+"]:
        rs = [r for g, r in ok if band.get(g) == bd]
        if rs:
            ac = [x for r in rs for x in (r["w_acpl"], r["b_acpl"]) if x is not None]
            mt = [x for r in rs for x in (r["w_match"], r["b_match"]) if x is not None]
            print(f"  {bd:>10}: n={len(rs):4d}  ACPL {sum(ac) / len(ac):6.1f}  match {sum(mt) / len(mt):.3f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "stockfish_benchmark.csv"
    cols = ["w_acpl", "b_acpl", "w_match", "b_match", "w_moves", "b_moves", "positions"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("game_id," + ",".join(cols) + "\n")
        for g, r in ok:
            f.write(g + "," + ",".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")
    print(f"Per-game results written to {path}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
