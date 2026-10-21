"""Cover upload, image conversion, and Claude Vision identification handlers."""

from __future__ import annotations

from server.images import convert_image as _convert_image
from server.images import identify_cover as _identify_cover
from server.images import upload_cover as _upload_cover


def upload_cover(body: dict):
    result = _upload_cover(body.get("image", ""), body.get("record_id", "tmp"))
    return 200, result


def convert_image(body: dict):
    result = _convert_image(body.get("image", ""))
    return (200 if result.get("success") else 500), result


def identify_cover(body: dict):
    result = _identify_cover(body.get("image", ""))
    # A missing/unconfigured key is 501; every other outcome (including a
    # confident "could not identify") is a normal 200 with success=False.
    if result.get("success"):
        return 200, result
    if "not configured" in result.get("error", ""):
        return 501, result
    return 200, result
