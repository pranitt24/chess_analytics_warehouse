"""PostgreSQL access: one small thread-safe pool, read-only, with a statement timeout."""
import math
import os
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "processed"


class DbError(Exception):
    """Database not reachable or query failed."""


class MissingTable(DbError):
    """A table that a pipeline script creates does not exist yet."""


def _env_file():
    p = ROOT / ".env"
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def database_url():
    url = os.getenv("DATABASE_URL") or _env_file().get("DATABASE_URL", "")
    if not url:
        raise DbError("DATABASE_URL is not set (put it in .env at the repo root).")
    return url


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        import psycopg2.pool
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1, 8, database_url(),
                options="-c statement_timeout=60000 -c default_transaction_read_only=on")
        except Exception as e:  # noqa: BLE001
            raise DbError(f"Database not reachable: {str(e).splitlines()[0]}")
    return _pool


def _clean(v):
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and abs(v) < 10**15 and v.as_tuple().exponent == 0 else float(v)
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def run(sql):
    """Execute one read-only statement; return a list of dicts."""
    import psycopg2
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
            names = [d[0] for d in cur.description]
            return [{n: _clean(v) for n, v in zip(names, r)} for r in cur.fetchall()]
    except psycopg2.Error as e:
        if getattr(e, "pgcode", None) == "42P01":
            raise MissingTable(str(e).splitlines()[0])
        raise DbError(str(e).splitlines()[0])
    finally:
        pool.putconn(conn)


def timed(sql):
    t0 = time.perf_counter()
    rows = run(sql)
    return rows, round((time.perf_counter() - t0) * 1000)
