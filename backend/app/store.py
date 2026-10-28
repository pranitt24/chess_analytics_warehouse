"""Mining results that live in files (written by the scripts in mining/), not in PostgreSQL."""
import csv
import json
import math
import re
from pathlib import Path

from .db import DATA

API_DIR = DATA / "api"        # UI-shaped JSON written by the export scripts
MINING_DIR = DATA / "mining"
CHEAT_DIR = DATA / "cheat"


def unavailable(reason):
    return {"available": False, "reason": reason}


_NUM = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")


def _num(v):
    """CSV text -> number, but only for real numbers: '1.e4' is a chess move, not 10000."""
    if v in (None, "", "nan", "NaN"):
        return None
    if not _NUM.match(v):
        return v
    f = float(v)
    if math.isnan(f):
        return None
    return int(v) if re.fullmatch(r"-?\d+", v) else f


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return [{k: _num(v) for k, v in row.items()} for row in csv.DictReader(fh)]


def api_json(name, hint):
    p = API_DIR / f"{name}.json"
    if not p.exists():
        return unavailable(f"{p.name} not found. {hint}")
    return {"available": True, **json.loads(p.read_text(encoding="utf-8"))}


def clusters():
    files = sorted(MINING_DIR.glob("cluster_profile_k*.csv"), key=lambda p: (p.stem.endswith("k6"), p.stat().st_mtime))
    if not files:
        return unavailable("No cluster profile found. Run: python mining\\clustering.py")
    rows = read_csv(files[-1])
    names, meta = {}, {}
    for fn, target in (("cluster_names.json", names), ("cluster_meta.json", meta)):
        p = API_DIR / fn
        if p.exists():
            target.update(json.loads(p.read_text(encoding="utf-8")))
    for r in rows:
        r["abs_elo_gap"] = r.get("abs_elo_diff")
        r["name"] = names.get(str(r["cluster"]), f"Cluster {r['cluster']}")
    return {"available": True, "k": len(rows), "silhouette": meta.get("silhouette"), "clusters": rows,
            "note": "k-means on a weighted resample of games. Cluster names are interpretations of the profile, not model output."}


_rules_cache = {}


def rules(p):
    seg = (p.get("segment") or "all").lower()
    files = {f.stem[len("assoc_rules_"):].lower(): f for f in MINING_DIR.glob("assoc_rules_*.csv")}
    if seg not in files:
        return unavailable("No rules file for this segment. Run: python mining\\association_rules.py")
    f = files[seg]
    key = (f, f.stat().st_mtime)
    if key not in _rules_cache:
        _rules_cache.clear()
        _rules_cache[key] = read_csv(f)
    rows = _rules_cache[key]
    mc, ml = float(p.get("min_confidence", 0)), float(p.get("min_lift", 0))
    sort = p.get("sort", "lift")
    if sort not in ("lift", "confidence", "support"):
        sort = "lift"
    sel = [r for r in rows if r["confidence"] >= mc and r["lift"] >= ml]
    if str(p.get("full_prefix", "")).lower() in ("1", "true", "yes"):
        sel = [r for r in sel if str(r.get("full_prefix")).lower() in ("true", "1")]
    sel.sort(key=lambda r: (r[sort], r["support"]), reverse=True)
    limit = max(1, min(int(p.get("limit", 50)), 500))
    out = [{"antecedent": ", ".join(str(r["antecedents"]).split()), "consequent": r["consequents"],
            "support": r["support"], "confidence": r["confidence"], "lift": r["lift"]} for r in sel[:limit]]
    return {"available": True, "total_rules": len(sel), "rows": out}


def classifier():
    p = CHEAT_DIR / "classifier_results.csv"
    if not p.exists():
        return unavailable("Run: python mining\\cheat_classifier.py")
    return {"available": True, "rows": read_csv(p)}


def tier1_validation():
    empty = {"pairs": None, "flagged_mean_acpl": None, "control_mean_acpl": None,
             "flagged_match": None, "control_match": None}
    p = CHEAT_DIR / "tier1_validation_pairs.csv"
    if not p.exists():
        return empty
    rows = read_csv(p)
    if not rows:
        return empty
    mean = lambda k: round(sum(r[k] for r in rows if r[k] is not None) / max(1, sum(r[k] is not None for r in rows)), 3)
    return {"pairs": len(rows), "flagged_mean_acpl": mean("f_acpl"), "control_mean_acpl": mean("c_acpl"),
            "flagged_match": mean("f_match"), "control_match": mean("c_match")}
