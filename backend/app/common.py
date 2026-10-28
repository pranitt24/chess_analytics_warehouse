"""Shared constants and input validation for the API.

Every value that ends up inside SQL is either (a) checked against a whitelist or an int
cast, or (b) a free-text value escaped by lit(). Identifiers are never taken from the
request: they come from the whitelists in olap.py / queries.py.
"""
CATEGORIES = ["Bullet", "Blitz", "Rapid", "Classical"]
BANDS = ["<1200", "1200-1499", "1500-1799", "1800-2099", "2100-2399", "2400+"]
SIGNALS = ["both", "timing_only", "quality_only", "none", "unscored"]


class BadParam(ValueError):
    """Raised for an invalid query parameter; main.py turns it into HTTP 400."""


def lit(v):
    """Render a validated Python value as a SQL literal."""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)
    if "\x00" in s or "\\" in s or len(s) > 100:
        raise BadParam("Invalid value.")
    return "'" + s.replace("'", "''") + "'"


def ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def pick(params, key, default, allowed):
    v = params.get(key, default)
    if v not in allowed:
        raise BadParam(f"{key} must be one of: {', '.join(map(str, allowed))}")
    return v


def int_param(params, key, default, lo, hi):
    try:
        v = int(params.get(key, default))
    except (TypeError, ValueError):
        raise BadParam(f"{key} must be an integer")
    if not lo <= v <= hi:
        raise BadParam(f"{key} must be between {lo} and {hi}")
    return v


def float_param(params, key, default, lo, hi):
    try:
        v = float(params.get(key, default))
    except (TypeError, ValueError):
        raise BadParam(f"{key} must be a number")
    if not lo <= v <= hi:
        raise BadParam(f"{key} must be between {lo} and {hi}")
    return v


def csv_list(params, key, default, allowed=None, cast=str):
    raw = params.get(key, default)
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            part = cast(part)
        except ValueError:
            raise BadParam(f"{key}: invalid value '{part}'")
        if allowed is not None and part not in allowed:
            raise BadParam(f"{key}: '{part}' is not allowed")
        if part not in out:
            out.append(part)
    if not out:
        raise BadParam(f"{key} must not be empty")
    return out


def col(key, label, type_="text"):
    return {"key": key, "label": label, "type": type_}
