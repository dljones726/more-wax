"""
More'Wax — Configuration
Loads environment variables from data/.env and defines all paths/constants.
"""

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = (
    Path(os.environ["DATA_DIR"]) if "DATA_DIR" in os.environ else BASE_DIR / "data"
)
COVERS_DIR = DATA_DIR / "covers"
DB_FILE = DATA_DIR / "collection.json"
LISTENS_FILE = DATA_DIR / "listens.json"

# Ensure data directories exist
DATA_DIR.mkdir(exist_ok=True)
COVERS_DIR.mkdir(exist_ok=True)


def _load_env_file(path: Path):
    """Load a .env file into os.environ (setdefault — won't override existing)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _migrate_env():
    """One-time migration: copy ./.env to data/.env if data/.env doesn't exist."""
    root_env = BASE_DIR / ".env"
    data_env = DATA_DIR / ".env"
    if root_env.exists() and not data_env.exists():
        import shutil

        shutil.copy2(root_env, data_env)
        print("  📦 Migrated .env → data/.env")


SUPPORTED_MODELS = [
    "claude-sonnet-4-6",
    "claude-haiku-4",
    "claude-opus-4",
]


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the runtime configuration.

    Prefer ``config.settings.<field>`` in new code. The module-level globals
    (``config.DISCOGS_TOKEN`` etc.) are kept as a compatibility shim, rebuilt
    from this object on every load, so existing reads keep working.
    """

    anthropic_api_key: str = ""
    vision_model: str = "claude-sonnet-4-6"
    discogs_token: str = ""
    format_filter: str = "Vinyl"  # Vinyl, CD, or All
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: str = ""  # comma-separated; blank = first-login-locks


# Current settings snapshot — reassigned on every _load_config().
settings = Settings()


def _load_config():
    """(Re)load configuration from data/.env into ``settings`` + legacy globals."""
    global ANTHROPIC_API_KEY, VISION_MODEL, DISCOGS_TOKEN, FORMAT_FILTER
    global GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ALLOWED_EMAILS, settings
    _load_env_file(DATA_DIR / ".env")
    settings = Settings(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        vision_model=os.environ.get("VISION_MODEL", "claude-sonnet-4-6"),
        discogs_token=os.environ.get("DISCOGS_TOKEN", ""),
        format_filter=os.environ.get("FORMAT_FILTER", "Vinyl"),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        allowed_emails=os.environ.get("ALLOWED_EMAILS", ""),
    )
    # Compatibility shim: mirror the snapshot into module-level globals.
    ANTHROPIC_API_KEY = settings.anthropic_api_key
    VISION_MODEL = settings.vision_model
    DISCOGS_TOKEN = settings.discogs_token
    FORMAT_FILTER = settings.format_filter
    GOOGLE_CLIENT_ID = settings.google_client_id
    GOOGLE_CLIENT_SECRET = settings.google_client_secret
    ALLOWED_EMAILS = settings.allowed_emails


def save_token(key: str, value: str):
    """Save or update a key=value pair in data/.env and reload config."""
    env_path = DATA_DIR / ".env"
    lines = []
    found = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                if k.strip() == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    # Atomic write: create temp file with restricted permissions, then rename.
    # Prevents a window where the file is world-readable between write and chmod.
    # CodeQL: py/clear-text-storage — accepted risk for self-hosted single-user app.
    import tempfile

    content = ("\n".join(lines) + "\n").encode()
    fd = -1
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), prefix=".env.tmp.")
        os.fchmod(fd, 0o600)
        os.write(fd, content)
        os.close(fd)
        fd = -1
        os.replace(tmp_path, str(env_path))
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    # Update os.environ so reload picks it up
    os.environ[key] = value
    _load_config()


DISCOGS_API = "https://api.discogs.com"

# Initial load
_migrate_env()
_load_config()
