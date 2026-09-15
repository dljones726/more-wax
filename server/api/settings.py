"""Setup + settings handlers, and the cached Anthropic-key validity state.

This module owns ``_anthropic_key_valid`` (was previously a handler global):
None = not yet checked, True = valid, False = invalid. ``server.py`` starts
:func:`check_anthropic_key` in a background thread at boot.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import server.config as _config
import server.discogs as _discogs_mod
from server.api.collection import count_missing_master_ids

# None = not yet checked, True = valid, False = invalid
_anthropic_key_valid = None


def anthropic_key_valid():
    """Return the cached Anthropic-key validity (None/True/False)."""
    return _anthropic_key_valid


def validate_anthropic_key(key: str) -> dict:
    """Validate an Anthropic API key by listing models (free, no tokens used)."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        method="GET",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):  # nosec B310
            return {"valid": True}
    except urllib.error.HTTPError as e:
        return {"valid": False, "error": f"Anthropic returned {e.code}"}
    except Exception as e:
        return {"valid": False, "error": str(e)}


def check_anthropic_key():
    """Background check: validate the configured key and cache the result."""
    global _anthropic_key_valid
    if not _config.ANTHROPIC_API_KEY:
        _anthropic_key_valid = None
        return
    result = validate_anthropic_key(_config.ANTHROPIC_API_KEY)
    _anthropic_key_valid = result["valid"]
    if result["valid"]:
        print("  🤖 [anthropic] API key is valid")
    else:
        print(f"  ⚠️ [anthropic] API key invalid: {result.get('error', '')}")


def _mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) > 4 else ""


def settings_payload() -> dict:
    """Current settings with masked secrets — the shared GET/response body."""
    dt = _config.DISCOGS_TOKEN
    ak = _config.ANTHROPIC_API_KEY
    gid = _config.GOOGLE_CLIENT_ID
    gs = _config.GOOGLE_CLIENT_SECRET
    return {
        "discogs_token_set": bool(dt),
        "discogs_token_masked": _mask(dt),
        "anthropic_key_set": bool(ak),
        "anthropic_key_masked": _mask(ak),
        "vision_model": _config.VISION_MODEL,
        "supported_models": _config.SUPPORTED_MODELS,
        "format_filter": _config.FORMAT_FILTER,
        "google_client_id_set": bool(gid),
        "google_client_id_masked": _mask(gid),
        "google_client_secret_set": bool(gs),
        "google_client_secret_masked": _mask(gs),
        "allowed_emails": _config.ALLOWED_EMAILS,
        "sync_missing_master_ids": count_missing_master_ids(),
    }


def handle_get_settings():
    return 200, settings_payload()


def handle_setup(body: dict):
    global _anthropic_key_valid
    discogs_token = body.get("discogs_token", "").strip()
    anthropic_key = body.get("anthropic_api_key", "").strip()

    if discogs_token:
        result = _discogs_mod.discogs_validate_token(discogs_token)
        if not result["valid"]:
            return 400, {"success": False, "error": result["error"]}
        _config.save_token("DISCOGS_TOKEN", discogs_token)
        _discogs_mod._discogs_username = result["username"]

    if anthropic_key:
        _config.save_token("ANTHROPIC_API_KEY", anthropic_key)
        _anthropic_key_valid = True  # validated inline already

    return 200, {
        "success": True,
        "discogs_connected": _discogs_mod._discogs_username is not None,
        "discogs_username": _discogs_mod._discogs_username,
        "discogs_token_set": bool(_config.DISCOGS_TOKEN),
        "anthropic_key_set": bool(_config.ANTHROPIC_API_KEY),
    }


def handle_setup_validate(body: dict):
    discogs_token = body.get("discogs_token", "").strip()
    anthropic_key = body.get("anthropic_api_key", "").strip()

    if discogs_token:
        return 200, _discogs_mod.discogs_validate_token(discogs_token)
    if anthropic_key:
        return 200, validate_anthropic_key(anthropic_key)
    return 400, {"valid": False, "error": "No token provided"}


def validate_google_oauth(redirect_uri: str) -> dict:
    """Validate Google OAuth credentials with a probe token request.

    A valid client_id/secret yields 'invalid_grant' (no real code); an invalid
    client yields 'invalid_client'. Returns {"valid": bool, ["error": str]}.
    """
    import json
    import urllib.parse

    params = urllib.parse.urlencode(
        {
            "code": "test_validation_code",
            "client_id": _config.GOOGLE_CLIENT_ID,
            "client_secret": _config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()

    try:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        urllib.request.urlopen(req, timeout=10)  # nosec B310
        # Shouldn't succeed with a fake code, but if it does, creds are valid
        return {"valid": True}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            return {"valid": False, "error": f"Google returned {e.code}"}

        error_code = body.get("error", "")
        error_desc = body.get("error_description", "")
        if error_code == "invalid_grant":
            return {"valid": True}  # creds valid — the fake code was rejected
        elif error_code == "invalid_client":
            return {"valid": False, "error": "Invalid Google Client ID or Secret"}
        elif error_code == "redirect_uri_mismatch":
            return {
                "valid": False,
                "error": f"Redirect URI mismatch. Register {redirect_uri} in Google Cloud Console.",
            }
        else:
            return {
                "valid": False,
                "error": error_desc or f"Google error: {error_code}",
            }
    except Exception as e:
        return {"valid": False, "error": f"Could not reach Google: {e}"}


def handle_update_settings(body: dict, redirect_uri: str):
    """Apply a settings update. Returns (status, settings_payload | error)."""
    global _anthropic_key_valid

    # Token updates (reuse setup validation)
    discogs_token = body.get("discogs_token", "").strip()
    if discogs_token:
        result = _discogs_mod.discogs_validate_token(discogs_token)
        if not result["valid"]:
            return 400, {"success": False, "error": result["error"]}
        _config.save_token("DISCOGS_TOKEN", discogs_token)
        _discogs_mod._discogs_username = result["username"]

    anthropic_key = body.get("anthropic_api_key", "").strip()
    if anthropic_key:
        result = validate_anthropic_key(anthropic_key)
        if not result["valid"]:
            return 400, {"success": False, "error": result["error"]}
        _config.save_token("ANTHROPIC_API_KEY", anthropic_key)
        _anthropic_key_valid = True

    # Non-token preferences
    if "vision_model" in body:
        model = body["vision_model"].strip()
        if model in _config.SUPPORTED_MODELS:
            _config.save_token("VISION_MODEL", model)

    if "format_filter" in body:
        fmt = body["format_filter"].strip()
        if fmt in ("Vinyl", "CD", "All"):
            _config.save_token("FORMAT_FILTER", fmt)

    # Clear Google OAuth
    if body.get("clear_google_auth"):
        _config.save_token("GOOGLE_CLIENT_ID", "")
        _config.save_token("GOOGLE_CLIENT_SECRET", "")
        _config.save_token("ALLOWED_EMAILS", "")
        from server.auth import clear_all_sessions

        clear_all_sessions()
        return 200, settings_payload()

    # Google OAuth settings — validate before saving
    google_id = body.get("google_client_id", "").strip()
    google_secret = body.get("google_client_secret", "").strip()

    if google_id:
        if not google_id.endswith(".apps.googleusercontent.com"):
            return 400, {
                "success": False,
                "error": "Invalid Client ID — must end with .apps.googleusercontent.com",
            }
        _config.save_token("GOOGLE_CLIENT_ID", google_id)

    if google_secret:
        _config.save_token("GOOGLE_CLIENT_SECRET", google_secret)

    # If both are now set, validate the full credentials against Google
    if (
        (google_id or google_secret)
        and _config.GOOGLE_CLIENT_ID
        and _config.GOOGLE_CLIENT_SECRET
    ):
        validation = validate_google_oauth(redirect_uri)
        if not validation["valid"]:
            # Roll back — clear the credential that was just saved
            if google_id:
                _config.save_token("GOOGLE_CLIENT_ID", "")
            if google_secret:
                _config.save_token("GOOGLE_CLIENT_SECRET", "")
            return 400, {"success": False, "error": validation["error"]}

    if "allowed_emails" in body:
        _config.save_token("ALLOWED_EMAILS", body["allowed_emails"].strip())
        # Invalidate all sessions when allowed emails change
        from server.auth import clear_all_sessions

        clear_all_sessions()

    return 200, settings_payload()
