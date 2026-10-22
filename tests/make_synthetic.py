"""Generate small FAKE Lichess-format .pgn.zst files so the pipeline can be tested without the real data.
The games are not legal chess (moves are random SAN-looking tokens); the pipeline does not validate moves.

Usage:
    python tests/make_synthetic.py --out data\\raw_synth --months 2013-01 2013-02 2016-05 --games 20000
Then point the pipeline at it with --raw data\\raw_synth.
"""
import argparse
import random
from pathlib import Path

import zstandard

SAN = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "d4", "d5", "c4", "e6", "Nc3",
       "Bg4", "h3", "Bh5", "Qd2", "Rfe1", "Rad1", "Qxd4", "Nxd4", "exd4", "Bxf6", "gxf6", "Kh1", "Rg8"]
OPENINGS = [("B90", "Sicilian Defense: Najdorf Variation"), ("C20", "King's Pawn Game"),
            ("D35", "Queen's Gambit Declined: Exchange Variation"), ("A00", "Uncommon Opening"),
            ("C60", "Ruy Lopez"), ("B01", "Scandinavian Defense")]
TCS = ["60+0", "120+1", "180+0", "300+0", "300+3", "600+0", "900+10", "1800+0", "-"]
TERMS = ["Normal"] * 85 + ["Time forfeit"] * 12 + ["Abandoned"] * 2 + ["Rules infraction"]


def fmt_clk(sec):
    sec = max(sec, 0)
    return f"{int(sec // 3600)}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}"


def make_game(rng, month, i, era):
    tc = rng.choice(TCS)
    cat = {"-": "Correspondence", "60+0": "Bullet", "120+1": "Bullet", "180+0": "Blitz", "300+0": "Blitz",
           "300+3": "Blitz", "600+0": "Rapid", "900+10": "Rapid", "1800+0": "Classical"}[tc]
    we, be = rng.randint(900, 2600), rng.randint(900, 2600)
    if rng.random() < 0.01:
        be = "?"
    plies = rng.choice([4, 6, 8] + [rng.randint(20, 90)] * 10)
    res = rng.choice(["1-0", "0-1", "1/2-1/2", "1-0", "0-1"])
    day = rng.randint(1, 28)
    gid = f"{rng.getrandbits(40):010x}"[:8]
    h = [("Event", f"Rated {cat} game"), ("Site", f"https://lichess.org/{gid}"),
         ("White", f"user{rng.randint(1, 600)}"), ("Black", f"user{rng.randint(1, 600)}"), ("Result", res)]
    if era >= 1:
        h += [("UTCDate", f"{month.replace('-', '.')}.{day:02d}"), ("UTCTime", "12:00:00")]
    else:
        h += [("Date", f"{month.replace('-', '.')}.{day:02d}")]
    h += [("WhiteElo", we), ("BlackElo", be)]
    if era >= 1:
        h += [("WhiteRatingDiff", f"{rng.randint(-20, 20):+d}"), ("BlackRatingDiff", f"{rng.randint(-20, 20):+d}")]
    eco, name = rng.choice(OPENINGS)
    h += [("ECO", eco), ("Opening", name), ("TimeControl", tc)]
    if era >= 1:
        h += [("Termination", rng.choice(TERMS))]
    head = "\n".join(f'[{k} "{v}"]' for k, v in h)

    base, inc = (0, 0) if tc == "-" else map(int, tc.split("+"))
    toks, clock = [], [float(base), float(base)]
    for p in range(plies):
        san = rng.choice(SAN)
        side = p % 2
        mv = f"{p // 2 + 1}. {san}" if side == 0 else (f"{p // 2 + 1}... {san}" if era >= 2 else san)
        if era >= 2:
            clock[side] = clock[side] - rng.uniform(0.5, 6) + inc
            mv += f" {{ [%clk {fmt_clk(clock[side])}] }}" if rng.random() > 0.0 else ""
            if rng.random() < 0.05:
                mv = mv[:-2] + f" [%eval {rng.uniform(-2, 2):.2f}] }}"
        toks.append(mv)
    return head + "\n\n" + " ".join(toks) + f" {res}\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--months", nargs="+", required=True)
    ap.add_argument("--games", type=int, default=20000)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for month in args.months:
        rng = random.Random(month)
        era = 0 if month < "2014-06" else (1 if month < "2016-01" else 2)   # early months lack fields on purpose
        path = out / f"lichess_db_standard_rated_{month}.pgn.zst"
        cctx = zstandard.ZstdCompressor(level=3)
        with open(path, "wb") as fh, cctx.stream_writer(fh) as w:
            for i in range(args.games):
                w.write(make_game(rng, month, i, era).encode("utf-8"))
        print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
