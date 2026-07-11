"""
More'Wax — Google Drive backup
Opt-in recurring backup of collection.json + listens.json to Google Drive.

Requires Google OAuth to be configured (same client as login). Uses a
separate consent with the drive.file scope (offline) so the server holds
a refresh token independent of any browser session.

A watcher thread hashes the data files every CHECK_INTERVAL seconds and
uploads one JSON bundle per change once the data has been stable for
DEBOUNCE seconds. The backup folder keeps the RETENTION newest bundles.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from server import config
from server.auth import (
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    _generate_code_challenge,
    _generate_code_verifier,
    _get_redirect_uri,
    _sanitize_header,
    audit,
)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

TOKEN_FILE = config.DATA_DIR / "drive_backup.json"
STATE_FILE = config.DATA_DIR / "backup_state.json"
DB_FILE = config.DB_FILE
LISTENS_FILE = config.LISTENS_FILE
FOLDER_NAME = "More'Wax Backups"

RETENTION = 14  # newest bundles kept in Drive
CHECK_INTERVAL = 60  # seconds between change checks
DEBOUNCE = 120  # data must be stable this long before upload

_lock = threading.Lock()
_pending_states: dict[str, dict] = {}
_STATE_TTL = 300

# Cached short-lived access token: {"token": str, "expires_at": float}
_access_cache: dict = {}

# Watcher debounce tracking
_pending_hash: str | None = None
_pending_since: float = 0.0


# ── Token & state files ─────────────────────────────────────────


def _load_json(path) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path, data: dict, private: bool = False) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def is_connected() -> bool:
    return bool(_load_json(TOKEN_FILE).get("refresh_token"))


def disconnect() -> None:
    with _lock:
        try:
            TOKEN_FILE.unlink()
        except FileNotFoundError:
            pass
        _access_cache.clear()
    audit("DRIVE_DISCONNECT")


# ── Change detection ─────────────────────────────────────────────


def _data_hash() -> str:
    """Hash the raw bytes of both data files. Cheap and lock-free —
    writers use atomic os.replace so we never see a torn file."""
    h = hashlib.sha256()
    for path in (DB_FILE, LISTENS_FILE):
        try:
            h.update(path.read_bytes())
        except OSError:
            h.update(b"")
        h.update(b"\x00")
    return h.hexdigest()


def _build_bundle() -> bytes:
    bundle = {
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
        "collection": _load_json(DB_FILE),
        "listens": _load_json(LISTENS_FILE),
    }
    return json.dumps(bundle, ensure_ascii=False).encode("utf-8")


def _files_to_prune(files: list, keep: int) -> list:
    """Given Drive file dicts with createdTime, return the ones to delete
    so only the `keep` newest remain."""
    if len(files) <= keep:
        return []
    ordered = sorted(files, key=lambda f: f.get("createdTime", ""), reverse=True)
    return ordered[keep:]


# ── Google API helpers ───────────────────────────────────────────


def _access_token() -> str:
    """Exchange the stored refresh token for a short-lived access token."""
    now = time.time()
    cached = _access_cache.get("token")
    if cached and _access_cache.get("expires_at", 0) > now + 60:
        return cached
    refresh = _load_json(TOKEN_FILE).get("refresh_token")
    if not refresh:
        raise RuntimeError("Drive backup not connected")
    body = urllib.parse.urlencode(
        {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
        tokens = json.loads(resp.read())
    token = tokens.get("access_token")
    if not token:
        raise RuntimeError("Google did not return an access token")
    _access_cache["token"] = token
    _access_cache["expires_at"] = now + int(tokens.get("expires_in", 3600))
    return token


def _drive_request(method: str, url: str, body: bytes | None = None, headers=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {_access_token()}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        raw = resp.read()
    return json.loads(raw) if raw else {}


def _folder_id() -> str:
    """Find or create the backup folder; cache its id in the state file."""
    state = _load_json(STATE_FILE)
    cached = state.get("folder_id")
    if cached:
        return cached
    q = urllib.parse.quote(
        f"name = '{FOLDER_NAME}' and "
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    found = _drive_request("GET", f"{DRIVE_FILES_URL}?q={q}&fields=files(id)")
    if found.get("files"):
        fid = found["files"][0]["id"]
    else:
        meta = json.dumps(
            {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
        ).encode()
        created = _drive_request(
            "POST",
            f"{DRIVE_FILES_URL}?fields=id",
            body=meta,
            headers={"Content-Type": "application/json"},
        )
        fid = created["id"]
    state["folder_id"] = fid
    _save_json(STATE_FILE, state)
    return fid


def _upload_bundle(data: bytes, folder_id: str) -> str:
    """Multipart upload; returns the created file name."""
    name = (
        "morewax-backup-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + ".json"
    )
    boundary = "morewax" + secrets.token_hex(12)
    meta = json.dumps({"name": name, "parents": [folder_id]})
    body = (
        (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n--{boundary}\r\nContent-Type: application/json\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    _drive_request(
        "POST",
        f"{DRIVE_UPLOAD_URL}?uploadType=multipart&fields=id",
        body=body,
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )
    return name


def _prune(folder_id: str) -> int:
    q = urllib.parse.quote(f"'{folder_id}' in parents and trashed = false")
    listing = _drive_request(
        "GET", f"{DRIVE_FILES_URL}?q={q}&fields=files(id,createdTime)&pageSize=100"
    )
    doomed = _files_to_prune(listing.get("files", []), RETENTION)
    for f in doomed:
        _drive_request("DELETE", f"{DRIVE_FILES_URL}/{f['id']}")
    return len(doomed)


# ── Backup driver ────────────────────────────────────────────────


def backup_now() -> dict:
    """Upload a bundle immediately. Returns a status dict."""
    with _lock:
        if not is_connected():
            return {"success": False, "error": "Drive backup not connected"}
        try:
            current = _data_hash()
            folder = _folder_id()
            name = _upload_bundle(_build_bundle(), folder)
            pruned = _prune(folder)
            state = _load_json(STATE_FILE)
            state.update(
                {
                    "last_hash": current,
                    "last_backup_at": datetime.now(timezone.utc).isoformat(),
                    "last_file_name": name,
                    "last_error": None,
                }
            )
            _save_json(STATE_FILE, state)
            audit("DRIVE_BACKUP", name)
            print(f"  ☁️ [backup] Uploaded {name} (pruned {pruned})")
            return {"success": True, "file_name": name, "pruned": pruned}
        except (urllib.error.URLError, RuntimeError, OSError, KeyError) as e:
            msg = str(e)
            state = _load_json(STATE_FILE)
            state["last_error"] = msg
            _save_json(STATE_FILE, state)
            print(f"  ⚠️ [backup] Failed: {msg}")
            return {"success": False, "error": msg}


def backup_status() -> dict:
    token = _load_json(TOKEN_FILE)
    state = _load_json(STATE_FILE)
    connected = bool(token.get("refresh_token"))
    return {
        "available": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
        "connected": connected,
        "email": token.get("email", "") if connected else "",
        "last_backup_at": state.get("last_backup_at"),
        "last_error": state.get("last_error"),
        "retention": RETENTION,
        "pending": connected and state.get("last_hash") != _data_hash(),
    }


# ── Watcher thread ───────────────────────────────────────────────


def _watch_loop():
    global _pending_hash, _pending_since
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            if not is_connected():
                _pending_hash = None
                continue
            current = _data_hash()
            if current == _load_json(STATE_FILE).get("last_hash"):
                _pending_hash = None
                continue
            now = time.time()
            if current != _pending_hash:
                _pending_hash = current
                _pending_since = now
                continue
            if now - _pending_since >= DEBOUNCE:
                backup_now()
                _pending_hash = None
        except Exception as e:  # never kill the watcher
            print(f"  ⚠️ [backup] Watcher error: {e}")


def start_watcher():
    threading.Thread(target=_watch_loop, daemon=True, name="drive-backup").start()


# ── OAuth connect flow ───────────────────────────────────────────


def handle_connect(handler):
    """GET /auth/drive/connect — redirect to Google consent for drive.file."""
    if not config.GOOGLE_CLIENT_ID:
        handler.send_json({"error": "Google OAuth not configured"}, 400)
        return
    state = secrets.token_urlsafe(32)
    verifier = _generate_code_verifier()
    redirect_uri = _get_redirect_uri(handler).replace(
        "/auth/callback", "/auth/drive/callback"
    )
    with _lock:
        now = time.time()
        for k in [
            k
            for k, v in _pending_states.items()
            if v.get("created_at", 0) + _STATE_TTL < now
        ]:
            del _pending_states[k]
        _pending_states[state] = {
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "created_at": now,
        }
    params = urllib.parse.urlencode(
        {
            "client_id": config.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": f"openid email {DRIVE_SCOPE}",
            "state": state,
            "code_challenge": _generate_code_challenge(verifier),
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    handler.send_response(302)
    handler.send_header("Location", _sanitize_header(f"{GOOGLE_AUTH_URL}?{params}"))
    handler.end_headers()


def handle_callback(handler):
    """GET /auth/drive/callback — store the refresh token, back to settings."""
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    state = qs.get("state", [None])[0]
    error = qs.get("error", [None])[0]

    def fail(status, msg):
        handler.send_json({"error": msg}, status)

    if error:
        return fail(400, f"Google returned: {error}")
    if not code or not state:
        return fail(400, "Missing code or state parameter")
    with _lock:
        pending = _pending_states.pop(state, None)
    if not pending or pending.get("created_at", 0) + _STATE_TTL < time.time():
        return fail(400, "OAuth state expired or invalid — try connecting again")

    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "redirect_uri": pending["redirect_uri"],
            "grant_type": "authorization_code",
            "code_verifier": pending["code_verifier"],
        }
    ).encode()
    try:
        req = urllib.request.Request(GOOGLE_TOKEN_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
            tokens = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError):
        return fail(500, "Token exchange with Google failed")

    refresh = tokens.get("refresh_token")
    if not refresh:
        return fail(
            500,
            "Google did not return a refresh token. Remove More'Wax from "
            "your Google account's third-party access list and try again.",
        )

    email = ""
    try:
        req = urllib.request.Request(GOOGLE_USERINFO_URL)
        req.add_header("Authorization", f"Bearer {tokens.get('access_token', '')}")
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            email = json.loads(resp.read()).get("email", "")
    except (urllib.error.URLError, json.JSONDecodeError):
        pass  # email is cosmetic; the refresh token is what matters

    with _lock:
        _save_json(
            TOKEN_FILE,
            {
                "refresh_token": refresh,
                "email": email,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            },
            private=True,
        )
        _access_cache.clear()
    audit("DRIVE_CONNECT", email)

    handler.send_response(302)
    handler.send_header("Location", "/")
    handler.end_headers()
