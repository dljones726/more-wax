"""
More'Wax — Discogs Collection Sync
One-way import: fetch user's Discogs collection, diff against local DB,
import selected records with basic metadata. Prices/ratings backfill
via the existing background refresh job.

Fuzzy duplicate detection: records with matching master_id or artist+title
(different pressing) are flagged as "possible duplicates" so the user can
decide whether to skip, import alongside, or replace the existing version.
"""

import copy
import threading
import time

from server.database import (
    _db_add_unlocked,
    db_delete,
    db_find_duplicate,
    db_list,
    db_update,
)
from server.database import (
    _lock as _db_lock,
)
from server.discogs import _discogs_request, discogs_fetch_collection

_sync_lock = threading.Lock()
_master_ids_backfilled = False

_sync_state = {
    "status": "idle",  # idle | fetching | importing | done | error
    "phase": "",
    "total": 0,
    "progress": 0,
    "diff": [],
    "imported": 0,
    "skipped": 0,
    "replaced": 0,
    "error": None,
}


def _normalize(s: str) -> str:
    """Normalize a string for fuzzy comparison."""
    return " ".join(s.lower().split())


# ── master_id backfill ───────────────────────────────────────────


def _build_master_map(discogs_records: list) -> dict:
    """Map discogs_id → master_id from a fetched Discogs collection."""
    return {
        str(r["discogs_id"]): r.get("master_id", "")
        for r in discogs_records
        if r.get("discogs_id") and r.get("master_id")
    }


def _resolve_master_ids(local: list, discogs_records: list) -> int:
    """Backfill master_id on local records that lack it. Returns the count resolved.

    Mutates the passed-in ``local`` dicts in place (so a caller that diffs right
    after sees the updated master_ids) and persists each via ``db_update``.

    Phase 1: match against the bulk Discogs collection map.
    Phase 2: for records still missing, fetch ``/releases/{id}`` individually
    (rate-limited); mark master_id="0" when no master release exists so we don't
    retry it on the next run.

    Shared by :func:`backfill_master_ids` (startup job) and :func:`sync_start_fetch`.
    """
    master_map = _build_master_map(discogs_records)
    resolved = 0

    # Phase 1: bulk resolve via the collection map
    for r in local:
        if r.get("master_id"):
            continue
        did, rid = r.get("discogs_id"), r.get("id")
        if not did or not rid:
            print(f"  ⚠️ [sync] Skipping record missing discogs_id or id: {r}")
            continue
        mid = master_map.get(str(did).strip(), "")
        if mid:
            try:
                db_update(rid, {"master_id": mid})
                r["master_id"] = mid
                resolved += 1
            except Exception as e:
                print(f"  ⚠️ [sync] Failed to update master_id for {did}: {e}")

    # Phase 2: individual release lookups for records not in the Discogs collection
    still_missing = [
        r
        for r in local
        if r.get("discogs_id") and r.get("id") and not r.get("master_id")
    ]
    if still_missing:
        print(
            f"  📦 [sync] Fetching master_id for {len(still_missing)}"
            " records via release API..."
        )
        for r in still_missing:
            did = str(r["discogs_id"]).strip()
            try:
                release = _discogs_request("GET", f"/releases/{did}")
                mid = str(release.get("master_id", "") or "")
                if mid:
                    db_update(r["id"], {"master_id": mid})
                    r["master_id"] = mid
                    resolved += 1
                else:
                    # No master release — mark so we don't retry
                    db_update(r["id"], {"master_id": "0"})
                time.sleep(1)
            except Exception as e:
                print(f"  ⚠️ [sync] Failed for {did}: {e}")

    return resolved


def backfill_master_ids():
    """Background startup job: backfill master_id on local records.

    Safe to call multiple times — skips if already done or not needed.
    """
    global _master_ids_backfilled
    with _sync_lock:
        if _master_ids_backfilled:
            return

    local = db_list()
    needs_backfill = [
        r for r in local if r.get("discogs_id") and not r.get("master_id")
    ]
    if not needs_backfill:
        with _sync_lock:
            _master_ids_backfilled = True
        return

    print(f"  📦 [sync] {len(needs_backfill)} records missing master_id")
    try:
        discogs_records = discogs_fetch_collection()
    except Exception as e:
        print(f"  ⚠️ [sync] Collection fetch failed: {e}")
        discogs_records = []

    resolved = _resolve_master_ids(local, discogs_records)

    with _sync_lock:
        _master_ids_backfilled = True
    print(f"  📦 [sync] Backfilled master_id for {resolved} records")


# ── diff ─────────────────────────────────────────────────────────


def _build_diff(discogs_records: list, local: list) -> list:
    """Return Discogs records not already in the local DB, annotated with duplicate info.

    A record whose discogs_id matches locally is skipped (already imported). Others
    are flagged ``_duplicate`` (with ``_local_match``) when a same-pressing (master_id)
    or fuzzy artist|title match exists locally.
    """
    local_ids = {str(r["discogs_id"]).strip() for r in local if r.get("discogs_id")}

    # master_id index (same pressing across releases)
    local_by_master = {}
    for r in local:
        mid = str(r.get("master_id", "")).strip()
        if mid and mid != "0":
            local_by_master[mid] = r

    # fuzzy "artist|title" index (fallback for records without master_id)
    local_by_name = {}
    for r in local:
        key = _normalize(r.get("artist", "")) + "|" + _normalize(r.get("title", ""))
        local_by_name[key] = r

    diff = []
    for r in discogs_records:
        if r.get("discogs_id", "") in local_ids:
            continue  # exact discogs_id match — already imported

        local_match = None
        master_id = str(r.get("master_id", "")).strip()
        if master_id and master_id != "0":
            local_match = local_by_master.get(master_id)
        if not local_match:
            key = _normalize(r.get("artist", "")) + "|" + _normalize(r.get("title", ""))
            local_match = local_by_name.get(key)

        if local_match:
            r["_duplicate"] = True
            r["_local_match"] = {
                "id": local_match.get("id"),
                "discogs_id": str(local_match.get("discogs_id", "")),
                "master_id": str(local_match.get("master_id", "")),
                "title": local_match.get("title", ""),
                "artist": local_match.get("artist", ""),
                "year": local_match.get("year", ""),
                "label": local_match.get("label", ""),
                "format": local_match.get("format", ""),
                "catalog_number": local_match.get("catalog_number", ""),
                "cover_image_url": local_match.get("cover_image_url", ""),
            }
        else:
            r["_duplicate"] = False
        diff.append(r)
    return diff


# ── public API ───────────────────────────────────────────────────


def sync_get_state() -> dict:
    """Return current sync state for polling (excludes diff to keep it small)."""
    with _sync_lock:
        s = dict(_sync_state)
        s.pop("diff", None)
        return s


def sync_start_fetch() -> dict:
    """Fetch Discogs collection and compute diff against local DB.

    Runs synchronously (fast: ~1 req per 100 records).
    Returns the diff list with fuzzy duplicate annotations.
    """
    with _sync_lock:
        if _sync_state["status"] in ("fetching", "importing"):
            return {
                "error": "A sync is already in progress",
                "status": _sync_state["status"],
            }
        _sync_state.update(
            status="fetching",
            phase="Fetching your Discogs collection...",
            total=0,
            progress=0,
            diff=[],
            imported=0,
            skipped=0,
            replaced=0,
            error=None,
        )

    try:
        discogs_records = discogs_fetch_collection()
        local = db_list()

        # Ensure master_ids are backfilled (no-op if already done at startup)
        with _sync_lock:
            needs_backfill = not _master_ids_backfilled
        if needs_backfill:
            _resolve_master_ids(local, discogs_records)

        diff = _build_diff(discogs_records, local)

        with _sync_lock:
            _sync_state.update(
                status="done" if not diff else "idle",
                phase="",
                diff=diff,
                total=len(discogs_records),
            )

        return {
            "status": "ok",
            "diff": diff,
            "total_in_discogs": len(discogs_records),
            "already_in_morewax": len(discogs_records) - len(diff),
        }

    except Exception as e:
        with _sync_lock:
            _sync_state.update(status="error", error=str(e), phase="")
        return {"error": str(e), "status": "error"}


def _build_import_record(rec: dict) -> dict:
    """Project a fetched diff record down to the fields we persist locally."""
    return {
        "discogs_id": rec.get("discogs_id"),
        "master_id": rec.get("master_id", ""),
        "title": rec.get("title", ""),
        "artist": rec.get("artist", ""),
        "year": rec.get("year", ""),
        "label": rec.get("label", ""),
        "catalog_number": rec.get("catalog_number", ""),
        "format": rec.get("format", ""),
        "genres": rec.get("genres", "[]"),
        "styles": rec.get("styles", "[]"),
        "cover_image_url": rec.get("cover_image_url", ""),
        "add_source": "discogs_sync",
    }


def _import_one(rec: dict, replace_set: set) -> dict:
    """Import a single fetched record. Returns delta counters for the caller to sum.

    Keys are a subset of {"imported", "replaced", "skipped", "failed"}, each 1.
    A replace both deletes the old record (``replaced``) and adds the new one
    (``imported``).
    """
    did = rec.get("discogs_id")
    if not did:
        print(
            f"  ⚠️ [sync] Record missing discogs_id, skipping: {rec.get('title', '?')}"
        )
        return {"failed": 1}

    record = _build_import_record(rec)
    delta = {}

    # Handle replace: delete old record first
    if did in replace_set and rec.get("_local_match"):
        old_id = rec["_local_match"].get("id")
        if old_id:
            db_delete(old_id)
            delta["replaced"] = 1

    # Atomic duplicate check + add under the DB lock
    with _db_lock:
        if db_find_duplicate(record):
            delta["skipped"] = 1
        else:
            _db_add_unlocked(record)
            delta["imported"] = 1

    return delta


def sync_start_import(selected_ids: list, replace_ids: list = None) -> dict:
    """Import selected records using basic data from the fetch phase.

    selected_ids: discogs_ids to import (new or import alongside existing)
    replace_ids: discogs_ids where the user chose to replace the local version

    No per-record API calls — uses data already fetched.
    Prices/ratings will backfill via background refresh.
    """
    # Normalize inputs to strings
    selected_ids = [str(x) for x in (selected_ids or [])]
    replace_set = {str(x) for x in (replace_ids or [])}

    with _sync_lock:
        if _sync_state["status"] == "importing":
            return {"error": "Import already in progress"}

        # Deep copy selected records from diff so we're safe outside the lock
        diff_by_id = {
            str(r["discogs_id"]): r for r in _sync_state["diff"] if r.get("discogs_id")
        }
        to_import = [
            copy.deepcopy(diff_by_id[did]) for did in selected_ids if did in diff_by_id
        ]

        if not to_import:
            return {"error": "No valid records selected", "imported": 0}

        _sync_state.update(
            status="importing",
            phase="Importing records...",
            total=len(to_import),
            progress=0,
            imported=0,
            skipped=0,
            replaced=0,
        )

    imported = 0
    skipped = 0
    replaced = 0
    failed = []

    try:
        for i, rec in enumerate(to_import):
            delta = _import_one(rec, replace_set)
            imported += delta.get("imported", 0)
            skipped += delta.get("skipped", 0)
            replaced += delta.get("replaced", 0)
            if delta.get("failed"):
                failed.append(rec)

            with _sync_lock:
                _sync_state["progress"] = i + 1
                _sync_state["imported"] = imported
                _sync_state["skipped"] = skipped
                _sync_state["replaced"] = replaced
    except Exception as e:
        print(f"  ⚠️ [sync] Import error: {e}")
    finally:
        with _sync_lock:
            _sync_state.update(
                status="done",
                phase="",
                diff=[],  # Clear diff to free memory
                failed=failed,
            )

    print(
        f"  📦 [sync] Import complete: {imported} imported,"
        f" {replaced} replaced, {skipped} skipped (duplicates)"
        + (f", {len(failed)} failed" if failed else "")
    )
    return {
        "imported": imported,
        "replaced": replaced,
        "skipped": skipped,
        "failed": failed,
    }
