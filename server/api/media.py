"""Cover upload, image conversion, and Claude Vision identification handlers."""

from __future__ import annotations

from server.images import convert_image, identify_cover, upload_cover


def handle_upload_cover(body: dict):
    result = upload_cover(body.get("image", ""), body.get("record_id", "tmp"))
    return 200, result


def handle_convert_image(body: dict):
    result = convert_image(body.get("image", ""))
    return (200 if result.get("success") else 500), result


def handle_identify_cover(body: dict):
    result = identify_cover(body.get("image", ""))
    # A missing/unconfigured key is 501; every other outcome (including a
    # confident "could not identify") is a normal 200 with success=False.
    if result.get("success"):
        return 200, result
    if "not configured" in result.get("error", ""):
        return 501, result
    return 200, result
