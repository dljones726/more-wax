"""Collection analytics — snapshot aggregation over records."""

from __future__ import annotations

import json
from collections import defaultdict


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_list(v) -> list:
    # genres/styles come in as JSON-string lists
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else [v]
        except (json.JSONDecodeError, ValueError):
            return [v]
    return []


def _decade(year) -> str | None:
    try:
        y = int(str(year)[:4])
    except (TypeError, ValueError):
        return None
    return f"{(y // 10) * 10}s" if y > 0 else None


def _rank(mapping: dict, by_name: bool = False) -> list:
    items = [
        {"name": k, "count": v["count"], "value": round(v["value"], 2)}
        for k, v in mapping.items()
    ]
    items.sort(
        key=(lambda d: d["name"]) if by_name else (lambda d: d["value"]),
        reverse=not by_name,
    )
    return items


def _top(records, key, reverse=True, predicate=None) -> list:
    pool = [r for r in records if (predicate(r) if predicate else True)]
    pool.sort(key=key, reverse=reverse)
    return [
        {
            "id": r.get("id"),
            "artist": r.get("artist", ""),
            "title": r.get("title", ""),
            "price_median": _to_float(r.get("price_median")),
            "num_for_sale": r.get("num_for_sale"),
            "rating_average": _to_float(r.get("rating_average")),
        }
        for r in pool[:10]
    ]


def _value_over_time(records: list) -> list:
    # Cumulative collection value by acquisition date, preferring the Discogs
    # date_added (acquired_at) and falling back to when it entered the app.
    # Uses current prices — we don't store historical price snapshots.
    dated = []
    for r in records:
        when = r.get("acquired_at") or r.get("added_at")
        if not when:
            continue
        dated.append((str(when)[:10], _to_float(r.get("price_median"))))
    dated.sort(key=lambda t: t[0])

    series: list = []
    cumulative = 0.0
    for day, value in dated:
        cumulative += value
        if series and series[-1]["date"] == day:
            series[-1]["value"] = round(cumulative, 2)
        else:
            series.append({"date": day, "value": round(cumulative, 2)})
    return series


def compute_summary(records: list) -> dict:
    total_low = total_median = total_high = 0.0
    currency = None
    by_genre: dict = defaultdict(lambda: {"count": 0, "value": 0.0})
    by_decade: dict = defaultdict(lambda: {"count": 0, "value": 0.0})

    for r in records:
        median = _to_float(r.get("price_median"))
        total_low += _to_float(r.get("price_low"))
        total_median += median
        total_high += _to_float(r.get("price_high"))
        if currency is None and r.get("price_currency"):
            currency = r.get("price_currency")
        for g in _parse_list(r.get("genres")):
            by_genre[g]["count"] += 1
            by_genre[g]["value"] += median
        d = _decade(r.get("year"))
        if d:
            by_decade[d]["count"] += 1
            by_decade[d]["value"] += median

    return {
        "count": len(records),
        "value": {
            "currency": currency or "USD",
            "low": round(total_low, 2),
            "median": round(total_median, 2),
            "high": round(total_high, 2),
        },
        "by_genre": _rank(by_genre),
        "by_decade": _rank(by_decade, by_name=True),
        "value_over_time": _value_over_time(records),
        "top_value": _top(records, key=lambda r: _to_float(r.get("price_median"))),
        "rarest": _top(
            records,
            key=lambda r: _to_float(r.get("num_for_sale")),
            reverse=False,
            predicate=lambda r: _to_float(r.get("num_for_sale")) > 0,
        ),
        "highest_rated": _top(
            records,
            key=lambda r: _to_float(r.get("rating_average")),
            predicate=lambda r: _to_float(r.get("rating_average")) > 0,
        ),
    }
