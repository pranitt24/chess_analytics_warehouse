"""PHASE A: inventory and integrity check.

Lists every file, finds missing months, flags oddly named / empty / partial downloads, and (optionally)
verifies SHA256 against Lichess's published checksum list.

Usage (PowerShell, from the repo root, venv active):
    python etl/inventory.py                                   # list + missing months (fast)
    python etl/inventory.py --hash                            # also compute SHA256 (5-20 min for 64.7 GB)
    python etl/inventory.py --hash --checksums data\\sha256sums.txt   # compute AND compare
"""
import argparse
import csv
import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import DOCS_DIR, END_MONTH, RAW_DIR, START_MONTH
from pgn_stream import FILE_RE


def month_range(start, end):
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    while (y, m) <= (ey, em):
        yield f"{y}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def sha256_file(path, chunk=8 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_checksums(path):
    ref = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                ref[parts[-1].lstrip("*")] = parts[0].lower()
    return ref


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW_DIR))
    ap.add_argument("--start", default=START_MONTH)
    ap.add_argument("--end", default=END_MONTH)
    ap.add_argument("--hash", action="store_true", help="compute SHA256 of every file")
    ap.add_argument("--checksums", help="Lichess sha256sums.txt to compare against (implies --hash)")
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()
    do_hash = args.hash or bool(args.checksums)

    from pathlib import Path
    raw = Path(args.raw)
    if not raw.exists():
        sys.exit(f"Raw folder not found: {raw}")

    found, odd = {}, []
    for p in sorted(raw.iterdir()):
        if not p.is_file():
            continue
        m = FILE_RE.search(p.name)
        if m:
            found[f"{m.group(1)}-{m.group(2)}"] = p
        else:
            odd.append(p)

    expected = list(month_range(args.start, args.end))
    missing = [m for m in expected if m not in found]
    extra = [m for m in found if m not in set(expected)]
    empty = [m for m, p in found.items() if p.stat().st_size == 0]

    ref = load_checksums(args.checksums) if args.checksums else {}
    hashes = {}
    if do_hash:
        print(f"Hashing {len(found)} files with {args.threads} threads ...")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futs = {ex.submit(sha256_file, p): m for m, p in found.items()}
            for i, fut in enumerate(as_completed(futs), 1):
                hashes[futs[fut]] = fut.result()
                print(f"  [{i}/{len(found)}] {futs[fut]} done ({time.time() - t0:.0f}s)")

    rows = []
    for m in sorted(found):
        p = found[m]
        size_gb = p.stat().st_size / 1e9
        if not do_hash:
            status = "NOT_CHECKED"
        elif not ref:
            status = "HASHED_ONLY"
        elif p.name not in ref:
            status = "NO_REFERENCE"
        else:
            status = "OK" if hashes[m] == ref[p.name] else "MISMATCH"
        rows.append((m, p.name, round(size_gb, 3), hashes.get(m, ""), status))

    DOCS_DIR.mkdir(exist_ok=True)
    with open(DOCS_DIR / "data_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "file", "size_gb", "sha256", "status"])
        w.writerows(rows)

    total = sum(r[2] for r in rows)
    lines = [
        "# Data manifest (Phase A)", "",
        f"- Expected window: {args.start} to {args.end} ({len(expected)} months)",
        f"- Files found matching the naming pattern: **{len(found)}**",
        f"- Total size: **{total:.1f} GB** (compressed)",
        f"- Missing months: **{', '.join(missing) if missing else 'none'}**",
        f"- Outside the expected window: {', '.join(extra) if extra else 'none'}",
        f"- Zero-byte files: {', '.join(empty) if empty else 'none'}",
        f"- Files that do not match the naming pattern (partial downloads?): "
        f"{', '.join(p.name for p in odd) if odd else 'none'}",
        "",
    ]
    if missing:
        lines += ["## Missing month(s): decision required", "",
                  "Download from the Lichess open database page (Standard rated games section), then re-run this script.",
                  "Expected file name pattern: `lichess_db_standard_rated_YYYY-MM.pgn.zst`.",
                  "Alternatively record in writing here that the month is excluded and why.", ""]
    lines += ["## Files", "", "| Month | File | Size (GB) | Checksum status |", "|---|---|---|---|"]
    lines += [f"| {m} | {n} | {s} | {st} |" for m, n, s, _, st in rows]
    (DOCS_DIR / "data_manifest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n===== SUMMARY =====")
    print(f"files found     : {len(found)} (expected {len(expected)})")
    print(f"total size      : {total:.1f} GB")
    print(f"MISSING months  : {missing if missing else 'none'}")
    if extra:
        print(f"outside window  : {extra}")
    if empty:
        print(f"ZERO-BYTE files : {empty}")
    if odd:
        print(f"odd file names  : {[p.name for p in odd]}")
    if ref:
        bad = [r[0] for r in rows if r[4] == "MISMATCH"]
        noref = [r[0] for r in rows if r[4] == "NO_REFERENCE"]
        print(f"checksum OK     : {sum(1 for r in rows if r[4] == 'OK')}/{len(rows)}")
        print(f"checksum BAD    : {bad if bad else 'none'}  <-- re-download these")
        if noref:
            print(f"no reference    : {noref}")
    print("Wrote docs/data_manifest.md and docs/data_manifest.csv")


if __name__ == "__main__":
    main()
