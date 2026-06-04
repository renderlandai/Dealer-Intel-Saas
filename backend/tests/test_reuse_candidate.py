"""Coverage for the Option-A "reuse vs. fresh scan" prompt.

`find_reusable_scan` powers a non-destructive lookup: is there a recent
completed scan whose already-discovered creatives can be reused to audit a
campaign for the dealers the user is about to scan — avoiding a fresh
(expensive) Apify / website scrape?

The contract under test:

1. Returns the newest fully-covering completed scan within the per-source
   freshness window.
2. Returns ``None`` when coverage is only partial.
3. Ignores dealers the channel can't reach (no facebook_url for a facebook
   scan, etc.) when deciding coverage.
4. Returns ``None`` when no requested dealer is relevant to the channel.
5. The endpoint wraps the result with a ``reusable`` flag and resolves
   ahead of ``GET /scans/{job_id}``.

Async coroutines are driven via plain ``asyncio.run(...)``.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import jwt

from tests.conftest import ORG_A_ID, USER_A_ID

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long"


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Filtering fake supabase for the helper unit tests. discovered_images
# respects the scan_job_id filter so different candidates yield different
# coverage; other tables return their preset rows in declared order (so the
# scan_jobs list order acts as "newest first").
# ---------------------------------------------------------------------------

class _Chain:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.eqs = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def in_(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self.table == "discovered_images":
            sid = self.eqs.get("scan_job_id")
            rows = [r for r in self.store["discovered_images"]
                    if r["scan_job_id"] == sid]
            return SimpleNamespace(data=rows)
        return SimpleNamespace(data=self.store.get(self.table, []))


class _Fake:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Chain(name, self.store)


def _patched(store):
    from app.routers import scanning
    return patch.object(scanning, "supabase", _Fake(store))


D1, D2, D3 = str(uuid4()), str(uuid4()), str(uuid4())
J_NEW, J_OLD = str(uuid4()), str(uuid4())


class TestFindReusableScan:
    def test_returns_candidate_on_full_coverage(self):
        from app.routers import scanning

        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "fb/1"},
                {"id": D2, "status": "active", "facebook_url": "fb/2"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
                {"scan_job_id": J_NEW, "distributor_id": D2},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1, D2]))

        assert result is not None
        assert result["job_id"] == J_NEW
        assert result["image_count"] == 2
        assert result["dealer_count"] == 2
        assert result["max_age_days"] == 7

    def test_shared_facebook_page_counts_as_covered(self):
        from app.routers import scanning

        # Regression: a rooftop (D2) and its parent group (D1) share ONE
        # Facebook page. The scraper attributes that page's ads to a single
        # distributor id (D1). Requesting reuse for D2 must still match,
        # because coverage is keyed on the URL, not the distributor id.
        SHARED = "https://www.facebook.com/altorfercaterpillar/"
        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": SHARED},
                {"id": D2, "status": "active", "facebook_url": SHARED},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
                {"scan_job_id": J_NEW, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D2]))

        assert result is not None
        assert result["job_id"] == J_NEW
        assert result["dealer_count"] == 1

    def test_url_coverage_ignores_trailing_slash_and_case(self):
        from app.routers import scanning

        store = {
            "distributors": [
                {"id": D1, "status": "active",
                 "facebook_url": "https://FB.com/Dealer"},
                {"id": D2, "status": "active",
                 "facebook_url": "https://fb.com/dealer/"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D2]))

        assert result is not None
        assert result["job_id"] == J_NEW

    def test_succeeded_empty_dealer_counts_as_covered(self):
        from app.routers import scanning

        # Dealer was cleanly scanned but had no live ads: no discovered
        # images, but a recorded "succeeded" outcome. Reuse should still
        # be offered so we don't pay to re-scrape a known-empty dealer.
        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "https://fb.com/d1"},
            ],
            "scan_jobs": [{
                "id": J_NEW, "completed_at": "2026-06-03T00:00:00Z",
                "metadata": {"dealer_outcomes": {
                    "https://fb.com/d1": {"status": "succeeded", "ad_count": 0},
                }},
            }],
            "discovered_images": [],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1]))

        assert result is not None
        assert result["job_id"] == J_NEW
        assert result["image_count"] == 0

    def test_timeout_dealer_not_covered(self):
        from app.routers import scanning

        # A timed-out (or otherwise failed) dealer must NOT count as
        # covered — we want it re-scanned, not silently reported clean.
        for bad in ("timeout", "error", "failed", "no_dataset", "skipped"):
            store = {
                "distributors": [
                    {"id": D1, "status": "active", "facebook_url": "https://fb.com/d1"},
                ],
                "scan_jobs": [{
                    "id": J_NEW, "completed_at": "2026-06-03T00:00:00Z",
                    "metadata": {"dealer_outcomes": {
                        "https://fb.com/d1": {"status": bad, "ad_count": 0},
                    }},
                }],
                "discovered_images": [],
            }
            with _patched(store):
                result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1]))
            assert result is None, f"{bad!r} should not be covered"

    def test_mixed_images_and_succeeded_empty_coverage(self):
        from app.routers import scanning

        # D1 yielded ads (images); D2 was cleanly scanned but empty.
        # Both requested -> full coverage via the two different signals.
        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "https://fb.com/d1"},
                {"id": D2, "status": "active", "facebook_url": "https://fb.com/d2"},
            ],
            "scan_jobs": [{
                "id": J_NEW, "completed_at": "2026-06-03T00:00:00Z",
                "metadata": {"dealer_outcomes": {
                    "https://fb.com/d2": {"status": "succeeded", "ad_count": 0},
                }},
            }],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1, D2]))

        assert result is not None
        assert result["job_id"] == J_NEW
        assert result["dealer_count"] == 2

    def test_none_on_partial_coverage(self):
        from app.routers import scanning

        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "fb/1"},
                {"id": D2, "status": "active", "facebook_url": "fb/2"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},  # D2 missing
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1, D2]))

        assert result is None

    def test_ignores_channel_irrelevant_dealers(self):
        from app.routers import scanning

        # D3 has no facebook_url -> a fresh facebook scan would never hit it,
        # so coverage of {D1} is "full" for facebook purposes.
        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "fb/1"},
                {"id": D3, "status": "active", "facebook_url": None,
                 "website_url": "site/3"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1, D3]))

        assert result is not None
        assert result["job_id"] == J_NEW
        assert result["dealer_count"] == 1  # only D1 is facebook-relevant

    def test_picks_newest_full_coverage(self):
        from app.routers import scanning

        # scan_jobs returned newest-first (J_NEW before J_OLD); both cover
        # D1 — the newest must win.
        store = {
            "distributors": [
                {"id": D1, "status": "active", "facebook_url": "fb/1"},
            ],
            "scan_jobs": [
                {"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"},
                {"id": J_OLD, "completed_at": "2026-06-01T00:00:00Z"},
            ],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
                {"scan_job_id": J_OLD, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D1]))

        assert result is not None
        assert result["job_id"] == J_NEW

    def test_none_when_no_relevant_dealers(self):
        from app.routers import scanning

        store = {
            "distributors": [
                {"id": D3, "status": "active", "facebook_url": None,
                 "website_url": "site/3"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "facebook", [D3]))

        assert result is None

    def test_website_uses_longer_window(self):
        from app.routers import scanning

        store = {
            "distributors": [
                {"id": D1, "status": "active", "website_url": "site/1"},
            ],
            "scan_jobs": [{"id": J_NEW, "completed_at": "2026-06-03T00:00:00Z"}],
            "discovered_images": [
                {"scan_job_id": J_NEW, "distributor_id": D1},
            ],
        }
        with _patched(store):
            result = _run(scanning.find_reusable_scan(ORG_A_ID, "website", [D1]))

        assert result is not None
        assert result["max_age_days"] == 14


# ---------------------------------------------------------------------------
# Endpoint: wraps the helper result and must resolve ahead of /{job_id}.
# ---------------------------------------------------------------------------

def _token(user_id) -> str:
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": "a@test.com",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _inject_user(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value\
        .single.return_value.execute.return_value = MagicMock(
            data={"organization_id": str(ORG_A_ID), "role": "owner"})


class TestReuseCandidateEndpoint:
    def test_reusable_true(self, client, mock_supabase):
        _inject_user(mock_supabase)
        candidate = {
            "job_id": J_NEW, "completed_at": "2026-06-03T00:00:00Z",
            "image_count": 12, "dealer_count": 3, "max_age_days": 7,
        }
        with patch("app.routers.scanning.find_reusable_scan",
                   AsyncMock(return_value=candidate)):
            resp = client.get(
                "/api/v1/scans/reuse-candidate?source=facebook",
                headers={"Authorization": f"Bearer {_token(USER_A_ID)}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reusable"] is True
        assert body["job_id"] == J_NEW
        assert body["image_count"] == 12

    def test_reusable_false(self, client, mock_supabase):
        _inject_user(mock_supabase)
        with patch("app.routers.scanning.find_reusable_scan",
                   AsyncMock(return_value=None)):
            resp = client.get(
                "/api/v1/scans/reuse-candidate?source=facebook",
                headers={"Authorization": f"Bearer {_token(USER_A_ID)}"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"reusable": False}

    def test_route_not_swallowed_by_job_id(self, client, mock_supabase):
        # If /{job_id} matched first, "reuse-candidate" would fail UUID
        # parsing with 422. A 200 proves the dedicated route wins.
        _inject_user(mock_supabase)
        with patch("app.routers.scanning.find_reusable_scan",
                   AsyncMock(return_value=None)):
            resp = client.get(
                "/api/v1/scans/reuse-candidate?source=website",
                headers={"Authorization": f"Bearer {_token(USER_A_ID)}"},
            )
        assert resp.status_code == 200
