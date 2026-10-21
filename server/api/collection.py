"""Collection CRUD, record details, and price-refresh handlers."""

from __future__ import annotations

import threading
import time

from server.api.discogs import backfill_master_id, discogs_error
from server.database import (
    _db_add_unlocked,
    _lock,
    db_delete,
    db_find_duplicate,
    db_get,
    db_list,
    db_update,
)
from server.discogs import discogs_refresh_prices, discogs_release_details
from server.listens import listens_delete_for_record

# Fields a client may set when creating a record.
_ADD_FIELDS = (
    "discogs_id",
    "master_id",
    "title",
    "artist",
    "year",
    "label",
    "catalog_number",
    "format",
    "genres",
    "styles",
    "country",
    "notes",
    "cover_image_url",
    "local_cover",
    "barcode",
    "price_low",
    "price_median",
    "price_high",
    "price_currency",
    "num_for_sale",
    "rating_average",
    "rating_count",
    "add_source",
)

# Fields a client may change on an existing record.
_UPDATE_FIELDS = (
    "title",
    "artist",
    "year",
    "label",
    "notes",
    "local_cover",
    "cover_image_url",
    "price_low",
    "price_median",
    "price_high",
    "price_currency",
    "num_for_sale",
    "rating_average",
    "rating_count",
    "liked_tracks",
)


def count_missing_master_ids() -> int:
    """Count records with a discogs_id but no master_id."""
    records = db_list()
    return sum(1 for r in records if r.get("discogs_id") and not r.get("master_id"))


def list():
    return 200, db_list()


def get(rid: int):
    rec = db_get(rid)
    return (200, rec) if rec else (404, {"error": "Not found"})


def add(body: dict):
    record = {k: body[k] for k in _ADD_FIELDS if k in body}
    record.setdefault("title", "")
    record.setdefault("artist", "")

    with _lock:
        dup = db_find_duplicate(record)
        if dup:
            return 409, {"duplicate": True, "existing": dup}
        new_id = _db_add_unlocked(record)

    return 201, {"id": new_id, "success": True}


def update(rid: int, body: dict):
    fields = {k: body[k] for k in _UPDATE_FIELDS if k in body}
    ok = db_update(rid, fields)
    return 200, {"success": ok}


def delete(rid: int):
    ok = db_delete(rid)
    if ok:
        listens_delete_for_record(rid)
    return 200, {"success": ok}


def details(rid: int):
    """Return cached Discogs extra details, fetching + caching on first request."""
    rec = db_get(rid)
    if not rec:
        return 404, {"error": "Not found"}

    discogs_id = rec.get("discogs_id")
    if not discogs_id:
        return 400, {"error": "No Discogs ID"}

    if rec.get("discogs_extra"):
        return 200, rec["discogs_extra"]

    try:
        extra = discogs_release_details(str(discogs_id))
        db_update(rid, {"discogs_extra": extra})
        return 200, extra
    except Exception as e:
        return discogs_error(e)


def add_to_collection(release_id: str):
    """Add a release to the user's Discogs collection, then backfill master_id."""
    from server.discogs import discogs_add_to_collection

    ok = discogs_add_to_collection(release_id)
    if ok:
        backfill_master_id(release_id)
    return 200, {"success": ok}


def refresh_all_prices(force: bool):
    """Refresh prices for stale (or all) records in a background thread."""
    records = db_list()
    stale = [
        r
        for r in records
        if r.get("discogs_id")
        and (
            force
            or not r.get("price_median")
            or not r.get("price_high")
            or not r.get("rating_average")
        )
    ]

    if not stale:
        return 200, {"updated": 0, "total_stale": 0}

    def _do_refresh():
        updated = 0
        for r in stale:
            did = r.get("discogs_id")
            rid = r.get("id")
            if not did or not rid:
                print(f"  ⚠️ [prices] Skipping record missing discogs_id or id: {r}")
                continue
            try:
                needs_rating = not r.get("rating_average")
                prices = discogs_refresh_prices(did, fetch_rating=needs_rating)
                if any(
                    prices.get(k)
                    for k in (
                        "price_low",
                        "price_median",
                        "price_high",
                        "rating_average",
                    )
                ):
                    db_update(rid, prices)
                    updated += 1
            except Exception as e:
                if "429" in str(e):
                    print(f"  ⚠️ Rate limit hit after {updated} updates, stopping")
                    break
            # 5s between records — leaves ~50% rate budget for user browsing
            time.sleep(5)
        print(f"  📊 Background price refresh done: {updated}/{len(stale)} updated")

    threading.Thread(target=_do_refresh, daemon=True).start()
    return 200, {"updated": "pending", "total_stale": len(stale)}
