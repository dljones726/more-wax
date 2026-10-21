"""
More'Wax — HTTP Request Handler
Thin routing/transport layer. Request parsing, the auth gate, path-safety, and
file/stream responses live here; per-endpoint business logic lives in
``server.api.*`` as functions returning ``(status, payload)``.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import server.auth as _auth
import server.backup as _backup
import server.config as _config
import server.discogs as _discogs_mod
from server.api import collection as _collection
from server.api import discogs as _discogs_api
from server.api import listens as _listens_api
from server.api import media as _media
from server.api import settings as _settings_api
from server.api import sync as _sync_api
from server.config import DATA_DIR, STATIC_DIR
from server.database import db_export

MAX_BODY_BYTES = 20 * 1024 * 1024  # 20 MB cap on request bodies


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        from datetime import datetime, timezone

        status = args[1] if len(args) > 1 else "?"
        # Sanitise path for log output (strip control chars)
        safe_path = self.path.replace("\n", "").replace("\r", "")
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"  {ts}  {self.command:6s} {safe_path}  →  {status}")

    # ── path safety ───────────────────────────────────────────

    # Trusted base directories — only these are allowed for file serving.
    _ALLOWED_BASES: dict[str, Path] = {
        "static": STATIC_DIR.resolve(),
        "data": DATA_DIR.resolve(),
    }

    @staticmethod
    def _safe_resolve(base_key: str, untrusted: str) -> Path | None:
        """Resolve *untrusted* within a trusted base directory.

        *base_key* must be a key in _ALLOWED_BASES (e.g. "static", "data").
        Walks the directory tree segment-by-segment using only trusted Path
        operations (iterdir), never constructing a Path from user input.
        Returns the resolved Path, or None if the path is invalid.
        """
        base_real = Handler._ALLOWED_BASES.get(base_key)
        if base_real is None:
            return None
        # Reject obvious traversal/absolute paths at the string level
        normalized = os.path.normpath(untrusted)
        if ".." in normalized or os.path.isabs(normalized):
            return None
        segments = [s for s in normalized.replace("\\", "/").split("/") if s]
        if not segments:
            return None
        # Walk the tree segment-by-segment using directory listings
        # so no user-provided string is ever passed to Path constructors.
        current = base_real
        for seg in segments:
            if not current.is_dir():
                return None
            # Find the matching entry in the actual directory listing
            match = None
            try:
                for entry in current.iterdir():
                    if entry.name == seg:
                        match = entry
                        break
            except OSError:
                return None
            if match is None:
                return None
            current = match.resolve()
        # Final containment check against the trusted base
        try:
            current.relative_to(base_real)
        except ValueError:
            return None
        return current

    # ── low-level helpers ────────────────────────────────────────

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path):
        if not path.is_file():
            self._404()
            return
        try:
            data = path.read_bytes()
        except (FileNotFoundError, PermissionError, OSError):
            self._404()
            return
        mime, _ = mimetypes.guess_type(str(path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return {}
        if n <= 0:
            return {}
        if n > MAX_BODY_BYTES:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}

    def path_parts(self):
        return urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

    def _query(self) -> dict:
        """Parsed query string as {key: [values]}."""
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    # ── routing ──────────────────────────────────────────────────

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        p = self.path_parts()

        # ── Auth routes (always public) ───────────────────────
        if p == "/auth/login":
            return _auth.handle_login(self)
        elif p == "/auth/callback":
            return _auth.handle_callback(self)
        elif p == "/auth/logout":
            return _auth.handle_logout(self)
        elif p == "/auth/status":
            # Tell the client if auth is actually required for this connection.
            # Local/private IPs bypass auth even when credentials are configured.
            is_proxied = bool(
                self.headers.get("X-Forwarded-For")
                or self.headers.get("X-Forwarded-Proto")
                or self.headers.get("Cf-Connecting-Ip")
            )
            skip_auth = not is_proxied and self._is_private_ip(
                self.client_address[0] if self.client_address else ""
            )
            return _auth.handle_status(self, skip_auth=skip_auth)

        # ── Auth gate ─────────────────────────────────────────
        if not self._check_auth():
            return

        # Drive backup connect flow (session required — settings action)
        if p == "/auth/drive/connect":
            return _backup.handle_connect(self)
        elif p == "/auth/drive/callback":
            return _backup.handle_callback(self)

        self._dispatch("GET", p)

    def do_POST(self):
        if not self._check_auth():
            return
        self._dispatch("POST", self.path_parts())

    def do_PUT(self):
        if not self._check_auth():
            return
        self._dispatch("PUT", self.path_parts())

    def do_DELETE(self):
        if not self._check_auth():
            return
        self._dispatch("DELETE", self.path_parts())

    def _dispatch(self, method: str, p: str):
        """Match (method, path) against the route table; invoke the handler."""
        for m, matcher, fn in _ROUTES:
            if m != method:
                continue
            params = matcher(p)
            if params is not None:
                return fn(self, params)
        self._404()

    def _respond(self, result):
        """Serialise an (status, payload) tuple from an api.* handler."""
        status, payload = result
        self.send_json(payload, status)

    def _404(self):
        self.send_response(404)
        self.end_headers()

    def _send_html(self, status: int, html: str):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── auth middleware ────────────────────────────────────────────

    # Paths that never require authentication
    _PUBLIC_PATHS = frozenset(
        {
            "/auth/login",
            "/auth/callback",
            "/auth/logout",
            "/auth/status",
        }
    )

    @staticmethod
    def _is_private_ip(ip: str) -> bool:
        """True if the IP is localhost or a private/link-local address (IPv4 + IPv6)."""
        if not ip:
            return True
        ip = ip.strip("[]")  # Strip IPv6 brackets (e.g. [::1])
        # IPv4 loopback and private ranges
        if ip in ("127.0.0.1", "::1", "localhost"):
            return True
        if ip.startswith("192.168.") or ip.startswith("10."):
            return True
        if ip.startswith("172."):
            parts = ip.split(".")
            try:
                if len(parts) >= 2 and 16 <= int(parts[1]) <= 31:
                    return True
            except ValueError:
                pass
        # IPv6 private ranges
        ip_lower = ip.lower().strip("[]")
        if ip_lower.startswith("fc") or ip_lower.startswith("fd"):  # Unique Local
            return True
        if ip_lower.startswith("fe80"):  # Link-Local (fe80::/10)
            return True
        if ip_lower.startswith("::ffff:"):  # IPv4-mapped IPv6
            return Handler._is_private_ip(ip_lower[7:])
        return False

    def _check_auth(self) -> bool:
        """Return True if request is authorized. If False, a response was sent."""
        if not _config.GOOGLE_CLIENT_ID or not _config.GOOGLE_CLIENT_SECRET:
            return True  # auth disabled — need both client ID and secret
        # If a reverse proxy is forwarding the request, auth is required
        # (even if the proxy itself connects from a private IP like Docker).
        # Otherwise, skip auth for direct LAN connections so users are never locked out.
        is_proxied = bool(
            self.headers.get("X-Forwarded-For")
            or self.headers.get("X-Forwarded-Proto")
            or self.headers.get("Cf-Connecting-Ip")
        )
        if not is_proxied:
            client_ip = self.client_address[0] if self.client_address else ""
            if self._is_private_ip(client_ip):
                return True
        p = self.path_parts()
        # Auth routes are always public
        if p in self._PUBLIC_PATHS:
            return True
        # The index page, static assets, and covers are public so
        # auth.js can load and show the login overlay
        if p in ("/", "/index.html"):
            return True
        if p.startswith("/static/") or p.startswith("/covers/"):
            return True
        # Check session cookie
        session = _auth.get_session(self.headers.get("Cookie", ""))
        if session:
            return True
        # Not authenticated
        if p.startswith("/api/"):
            self.send_json({"error": "Not authenticated"}, 401)
        else:
            # Redirect to home (auth.js will show login overlay)
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        return False

    @staticmethod
    def _tail_id(path: str) -> int:
        try:
            return int(path.split("/")[-1])
        except ValueError:
            return -1

    def _settings_redirect_uri(self) -> str:
        """Build the OAuth redirect URI for the Google credential probe."""
        host = (
            self.headers.get("X-Forwarded-Host")
            or self.headers.get("Host")
            or "localhost"
        )
        proto = self.headers.get("X-Forwarded-Proto", "http")
        return f"{proto}://{host}/auth/callback"

    # ── status ─────────────────────────────────────────────────────

    def _api_status(self):
        from server.version import BUILD_DATE, GIT_REVISION, VERSION

        self.send_json(
            {
                "discogs_connected": _discogs_mod._discogs_username is not None,
                "discogs_username": _discogs_mod._discogs_username,
                "discogs_token_set": bool(_config.DISCOGS_TOKEN),
                "anthropic_key_set": bool(_config.ANTHROPIC_API_KEY),
                "anthropic_key_valid": _settings_api.anthropic_key_valid(),
                "vision_model": _config.VISION_MODEL,
                "format_filter": _config.FORMAT_FILTER,
                "version": VERSION,
                "build_date": BUILD_DATE,
                "git_revision": GIT_REVISION,
            }
        )

    # ── export (streaming download) ────────────────────────────────

    def _api_export(self):
        """Export the collection as a downloadable JSON file."""
        from datetime import datetime, timezone

        data = db_export()
        export = {
            "schema_version": data.get("schema_version", "1.0"),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "records": data.get("records", []),
        }
        body = json.dumps(export, indent=2, ensure_ascii=False).encode("utf-8")
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="morewax-export-{date_str}.json"',
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── cover proxy (for share card CORS) ──────────────────────

    def _api_cover_proxy(self):
        """Proxy a Discogs cover image to avoid CORS issues for canvas rendering."""
        raw_url = self._query().get("url", [""])[0]
        # Parse and reconstruct URL to prevent SSRF — only allow i.discogs.com
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme != "https" or parsed.hostname != "i.discogs.com":
            self._404()
            return
        # Reconstruct a clean URL from validated components (breaks taint chain)
        safe_url = urllib.parse.urlunparse(
            ("https", "i.discogs.com", parsed.path, "", parsed.query, "")
        )
        try:
            req = urllib.request.Request(safe_url)  # nosec B310
            req.add_header("User-Agent", "MoreWax/1.0")
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                if not content_type.startswith("image/"):
                    self._404()
                    return
                data = resp.read(5 * 1024 * 1024)  # 5MB max
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self._404()


# ── route table ──────────────────────────────────────────────────
#
# Each entry is (method, matcher, handler). ``matcher(path)`` returns a dict of
# captured params (possibly empty) on a match, else None. ``handler(h, params)``
# sends the response. Adding an endpoint is a one-line entry here — no more
# growing an if/elif ladder. Auth-route dispatch and the auth gate stay in the
# do_* methods above; this table covers everything past the gate.


def _compile(pattern: str):
    """Build a path matcher. ``{name}`` captures one segment ([^/]+); ``{name*}``
    captures a trailing path (.+). A pattern with no braces is an exact match."""
    if "{" not in pattern:
        return lambda p: {} if p == pattern else None
    parts = []
    for seg in pattern.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            name = seg[1:-1]
            if name.endswith("*"):
                parts.append(f"(?P<{name[:-1]}>.+)")
            else:
                parts.append(f"(?P<{name}>[^/]+)")
        else:
            parts.append(re.escape(seg))
    rx = re.compile("^" + "/".join(parts) + "$")
    return lambda p: m.groupdict() if (m := rx.match(p)) else None


def _to_int(s) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return -1


def _serve_index(h, _params):
    h.send_file(STATIC_DIR / "index.html")


def _serve_base(h, base_key: str, rel: str):
    f = h._safe_resolve(base_key, rel)
    h.send_file(f) if f else h._404()


def _search_args(h):
    q = h._query()
    return q.get("q", [""])[0], q.get("barcode", [""])[0]


def _backup_now(h):
    result = _backup.backup_now()
    h.send_json(result, 200 if result.get("success") else 502)


def _backup_disconnect(h):
    _backup.disconnect()
    h.send_json({"success": True})


def _R(method, pattern, fn):
    return (method, _compile(pattern), fn)


_ROUTES = [
    # ── GET: files & pages ──
    _R("GET", "/", _serve_index),
    _R("GET", "/index.html", _serve_index),
    _R("GET", "/static/{path*}", lambda h, prm: _serve_base(h, "static", prm["path"])),
    _R(
        "GET",
        "/covers/{path*}",
        lambda h, prm: _serve_base(h, "data", "covers/" + prm["path"]),
    ),
    # ── GET: JSON / streams ──
    _R("GET", "/api/cover-proxy", lambda h, _: h._api_cover_proxy()),
    _R("GET", "/api/status", lambda h, _: h._api_status()),
    _R("GET", "/api/collection", lambda h, _: h._respond(_collection.list())),
    _R(
        "GET",
        "/api/collection/{id}/details",
        lambda h, prm: h._respond(_collection.details(_to_int(prm["id"]))),
    ),
    _R(
        "GET",
        "/api/collection/{id}",
        lambda h, prm: h._respond(_collection.get(_to_int(prm["id"]))),
    ),
    _R(
        "GET",
        "/api/settings",
        lambda h, _: h._respond(_settings_api.get_settings()),
    ),
    _R("GET", "/api/export", lambda h, _: h._api_export()),
    _R("GET", "/api/sync/status", lambda h, _: h._respond(_sync_api.status())),
    _R(
        "GET",
        "/api/discogs/search",
        lambda h, _: h._respond(_discogs_api.search(*_search_args(h))),
    ),
    _R(
        "GET",
        "/api/discogs/release/{id}",
        lambda h, prm: h._respond(_discogs_api.release(prm["id"])),
    ),
    _R(
        "GET",
        "/api/discogs/prices/{id}",
        lambda h, prm: h._respond(_discogs_api.prices(prm["id"])),
    ),
    _R(
        "GET",
        "/api/discogs/in-collection/{id}",
        lambda h, prm: h._respond(_discogs_api.in_collection(prm["id"])),
    ),
    _R(
        "GET",
        "/api/listens",
        lambda h, _: h._respond(
            _listens_api.list(h._query().get("record_id", [None])[0])
        ),
    ),
    _R("GET", "/api/backup/status", lambda h, _: h.send_json(_backup.backup_status())),
    # ── POST ──
    _R(
        "POST",
        "/api/setup",
        lambda h, _: h._respond(_settings_api.setup(h.read_json())),
    ),
    _R(
        "POST",
        "/api/setup/validate",
        lambda h, _: h._respond(_settings_api.setup_validate(h.read_json())),
    ),
    _R(
        "POST",
        "/api/settings",
        lambda h, _: h._respond(
            _settings_api.update_settings(h.read_json(), h._settings_redirect_uri())
        ),
    ),
    _R(
        "POST",
        "/api/collection",
        lambda h, _: h._respond(_collection.add(h.read_json())),
    ),
    _R(
        "POST",
        "/api/upload-cover",
        lambda h, _: h._respond(_media.upload_cover(h.read_json())),
    ),
    _R(
        "POST",
        "/api/convert-image",
        lambda h, _: h._respond(_media.convert_image(h.read_json())),
    ),
    _R(
        "POST",
        "/api/identify-cover",
        lambda h, _: h._respond(_media.identify_cover(h.read_json())),
    ),
    _R(
        "POST",
        "/api/discogs/add-to-collection/{id}",
        lambda h, prm: h._respond(_collection.add_to_collection(prm["id"])),
    ),
    _R(
        "POST",
        "/api/collection/refresh-prices",
        lambda h, _: h._respond(_collection.refresh_all_prices("force" in h._query())),
    ),
    _R("POST", "/api/sync/fetch", lambda h, _: h._respond(_sync_api.fetch())),
    _R(
        "POST",
        "/api/sync/import",
        lambda h, _: h._respond(_sync_api.import_(h.read_json())),
    ),
    _R(
        "POST",
        "/api/listens",
        lambda h, _: h._respond(_listens_api.add(h.read_json())),
    ),
    _R("POST", "/api/backup/now", lambda h, _: _backup_now(h)),
    _R("POST", "/api/backup/disconnect", lambda h, _: _backup_disconnect(h)),
    # ── PUT ──
    _R(
        "PUT",
        "/api/collection/{id}",
        lambda h, prm: h._respond(
            _collection.update(_to_int(prm["id"]), h.read_json())
        ),
    ),
    # ── DELETE ──
    _R(
        "DELETE",
        "/api/discogs/collection/{id}",
        lambda h, prm: h._respond(_discogs_api.remove_from_collection(prm["id"])),
    ),
    _R(
        "DELETE",
        "/api/collection/{id}",
        lambda h, prm: h._respond(_collection.delete(_to_int(prm["id"]))),
    ),
    _R(
        "DELETE",
        "/api/listens/{id}",
        lambda h, prm: h._respond(_listens_api.delete(_to_int(prm["id"]))),
    ),
]
