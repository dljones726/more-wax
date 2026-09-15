"""Discogs search / release / price / collection-membership handlers."""

from __future__ import annotations

import urllib.error

from server.database import db_list, db_update
from server.discogs import (
    _discogs_request,
    discogs_check_collection,
    discogs_refresh_prices,
    discogs_release_full,
    discogs_remove_from_collection,
    discogs_search,
)


def discogs_error(e: Exception):
    """Map a Discogs API exception to an ``(status, payload)`` error response."""
    if isinstance(e, urllib.error.HTTPError):
        return (e.code if e.code < 500 else 502), {"error": f"Discogs {e.code}"}
    return 502, {"error": str(e)}


def backfill_master_id(discogs_id: str):
    """Fetch and save master_id for a local record if it's missing."""
    records = db_list()
    rec = next(
        (r for r in records if str(r.get("discogs_id", "")) == discogs_id),
        None,
    )
    if not rec or rec.get("master_id"):
        return  # already has master_id or not in local DB
    try:
        release = _discogs_request("GET", f"/releases/{discogs_id}")
        mid = str(release.get("master_id", "") or "0")
        db_update(rec["id"], {"master_id": mid})
    except Exception:
        pass  # non-critical, will be retried on next startup


def handle_search(q: str, barcode: str):
    if not q and not barcode:
        return 400, {"results": [], "error": "No search query provided"}
    try:
        # Read the filter fresh each call — it can change at runtime via settings.
        import server.config as _config

        results = discogs_search(
            q=q, barcode=barcode, format_filter=_config.FORMAT_FILTER
        )
        return 200, {"results": results}
    except Exception as e:
        return discogs_error(e)


def handle_release(release_id: str):
    if not release_id or not release_id.isdigit():
        return 400, {"error": "Invalid release ID"}
    try:
        return 200, discogs_release_full(release_id)
    except Exception as e:
        return discogs_error(e)


def handle_prices(release_id: str):
    try:
        return 200, discogs_refresh_prices(release_id)
    except Exception as e:
        return discogs_error(e)


def handle_in_collection(release_id: str):
    return 200, {"in_collection": discogs_check_collection(release_id)}


def handle_remove_from_collection(release_id: str):
    return 200, {"success": discogs_remove_from_collection(release_id)}
