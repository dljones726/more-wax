"""Listen-logging handlers."""

from __future__ import annotations

from server.database import db_get
from server.listens import listens_add, listens_delete, listens_list


def handle_list(record_id_param: str | None):
    """List listens, newest first. Optional record_id filter (as a string)."""
    record_id = None
    if record_id_param is not None:
        try:
            record_id = int(record_id_param)
        except ValueError:
            return 400, {"error": "record_id must be an integer"}
    return 200, listens_list(record_id)


def handle_add(body: dict):
    """Log a listen for a record. Body: {record_id: int}."""
    try:
        record_id = int(body.get("record_id"))
    except (TypeError, ValueError):
        return 400, {"error": "record_id is required"}
    if db_get(record_id) is None:
        return 404, {"error": "Record not found"}
    return 201, listens_add(record_id)


def handle_delete(listen_id: int):
    return 200, {"success": listens_delete(listen_id)}
