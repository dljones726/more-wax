# feat: Google Drive backup — backend

**Date:** 2026-07-11
**Type:** Feature

## Intent

Recurring off-site backup of the collection to the user's own Google Drive, available when Google OAuth is configured. This PR is the backend: a separate Drive consent flow, upload/retention logic, and a change-watcher. The Settings UI follows in its own PR.

Decisions (user-confirmed): JSON only (collection + listens, no covers), backup on every change (debounced), keep the 14 newest bundles.

### Prompts summary

1. Add a recurring Google Drive backup for users who have Google auth active.
2. Scoping answers: JSON-only bundles, on-every-change frequency, retention of 14.

## Design

The login flow uses `access_type=online` and discards Google tokens after the userinfo fetch, so backups cannot reuse login sessions. Instead, an opt-in `GET /auth/drive/connect` runs a second PKCE consent with scope `drive.file` (only files the app creates), `access_type=offline` + `prompt=consent`, and stores the resulting refresh token in `data/drive_backup.json` (0600). The token never leaves the server; `/api/backup/status` exposes only the connected email.

A daemon thread wakes every 60s, hashes the raw bytes of `collection.json` + `listens.json`, and uploads once the hash differs from the last backup **and** has been stable for 120s (debounce). This catches every mutation path — including manual file edits — without hooking each write site. Each backup is one self-contained JSON bundle (`morewax-backup-<utc>.json`) in a "More'Wax Backups" Drive folder; after upload, files beyond the 14 newest are deleted.

## Changes

### `server/backup.py` (new)
- OAuth connect/callback handlers reusing the PKCE helpers from `server/auth.py`.
- Drive API via stdlib `urllib` (no new dependencies): token refresh with in-memory access-token cache, find-or-create folder (id cached in `data/backup_state.json`), multipart upload, retention pruning.
- `backup_now()`, `backup_status()`, `disconnect()`, `start_watcher()`.
- Errors land in `backup_state.json:last_error` and surface via status; the watcher never dies on exceptions.

### `server/handler.py`
- `GET /auth/drive/connect`, `GET /auth/drive/callback` — behind the auth gate (settings actions, session cookie present on the Google redirect).
- `GET /api/backup/status`, `POST /api/backup/now` (502 on failure), `POST /api/backup/disconnect`.

### `server.py`
- Starts the watcher thread at startup (no-op until connected).

### `tests/test_backup.py` (new)
- 15 unit tests: retention math, change-hash behavior, bundle content, token lifecycle + 0600 mode, status flags, disconnect idempotency. No network.

## Verification

- 242 unit tests pass; ruff + bandit clean.
- Smoke-tested against a dev server: status/now/disconnect respond correctly when unconfigured and when configured-but-not-connected; `/auth/drive/connect` 302s to Google with `drive.file` scope, `access_type=offline`, `prompt=consent`, PKCE challenge, and the right callback URI.
- Full OAuth round-trip requires the real Google client — **the Drive API must be enabled for the existing Google Cloud project** before first use.

## Files modified

| File | Change |
|------|--------|
| `server/backup.py` | New Drive backup module |
| `server/handler.py` | Connect/callback + 3 API routes |
| `server.py` | Start backup watcher |
| `tests/test_backup.py` | 15 unit tests |
