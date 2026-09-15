"""Discogs collection-sync handlers (fetch diff, import)."""

from __future__ import annotations

import threading

from server.sync import sync_get_state, sync_start_fetch, sync_start_import


def handle_status():
    return 200, sync_get_state()


def handle_fetch():
    result = sync_start_fetch()
    if "error" in result:
        return (400 if result.get("status") != "error" else 500), result
    return 200, result


def handle_import(body: dict):
    selected = body.get("selected", [])
    replace_ids = body.get("replace", [])
    if not isinstance(selected, list) or not selected:
        return 400, {"error": "No records selected"}
    if not isinstance(replace_ids, list):
        replace_ids = []

    def _run():
        sync_start_import(selected, replace_ids)

    threading.Thread(target=_run, daemon=True).start()
    return 200, {"status": "importing", "total": len(selected)}
