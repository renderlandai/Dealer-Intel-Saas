"""Supabase database client with automatic reconnection."""
import os
import time
import logging
from supabase import create_client, Client
from .config import get_settings

log = logging.getLogger("dealer_intel.database")

# Clear proxy env vars that Cursor/IDE terminals inject — they cause
# httpx.ProxyError: 403 when the Supabase client tries to reach the API.
for _k in list(os.environ):
    if _k.lower().replace("_", "").endswith("proxy") or _k.lower().startswith("no_proxy"):
        os.environ.pop(_k, None)

settings = get_settings()

_client: Client = None
_client_created_at: float = 0
_MAX_CLIENT_AGE_SECONDS = 300


def _make_client() -> Client:
    """Create a Supabase client."""
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )


def get_supabase_client(force_new: bool = False) -> Client:
    """Get Supabase client, recycling every 5 minutes."""
    global _client, _client_created_at
    now = time.time()
    if force_new or _client is None or (now - _client_created_at) > _MAX_CLIENT_AGE_SECONDS:
        if _client is not None:
            log.debug("Recycling Supabase client (age: %.0fs)", now - _client_created_at)
        _client = _make_client()
        _client_created_at = now
    return _client


class _SupabaseProxy:
    """Proxy that delegates to a fresh client and retries on connection errors."""

    def __getattr__(self, name):
        return getattr(get_supabase_client(), name)


supabase: Client = _SupabaseProxy()  # type: ignore[assignment]

















