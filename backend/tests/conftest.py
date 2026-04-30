"""Shared fixtures for Dealer Intel test suite."""
import os
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

# Set required env vars BEFORE importing anything from the app
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-that-is-at-least-32-chars-long")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("BRIGHTDATA_API_TOKEN", "test-brightdata-token")
os.environ.setdefault("BRIGHTDATA_UNLOCKER_ZONE", "test_zone")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")

USER_A_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
ORG_A_ID = UUID("11111111-1111-1111-1111-111111111111")
ORG_B_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture()
def user_a():
    from app.auth import AuthUser
    return AuthUser(user_id=USER_A_ID, org_id=ORG_A_ID, role="owner", email="a@test.com")


@pytest.fixture()
def user_b():
    from app.auth import AuthUser
    return AuthUser(user_id=USER_B_ID, org_id=ORG_B_ID, role="owner", email="b@test.com")


@pytest.fixture(autouse=True)
def _clear_auth_caches():
    """Reset auth caches between tests."""
    yield
    from app.auth import clear_profile_cache
    clear_profile_cache()


@pytest.fixture()
def mock_supabase():
    """Provide a mock supabase client that can be pre-loaded with return values."""
    mock = MagicMock()
    with patch("app.database.get_supabase_client", return_value=mock):
        yield mock


@pytest.fixture()
def client(mock_supabase):
    """FastAPI TestClient with scheduler disabled."""
    with patch("app.services.scheduler_service.start", new_callable=AsyncMock), \
         patch("app.services.scheduler_service.shutdown", new_callable=AsyncMock):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
