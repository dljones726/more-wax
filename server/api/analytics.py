"""Analytics endpoint handlers."""

from __future__ import annotations

from server.analytics import compute_summary
from server.database import db_list


def summary():
    return 200, compute_summary(db_list())
