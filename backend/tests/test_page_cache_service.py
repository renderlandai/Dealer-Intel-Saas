"""Phase 6.5.5 — page_cache_service unit tests.

The previous implementation of ``record_page_hits`` used
``.maybe_single().execute()`` on the lookup. In this version of
supabase-py, ``maybe_single`` raises ``code: '204'`` on an empty result
set instead of returning ``data=None`` — so every brand-new page hit
fell through to the ``except`` branch and the insert never ran. The
result was the entire page-hit-cache early-stop optimisation went dead
silently from migration 016 forward.

The fix replaces ``.maybe_single()`` with ``.limit(1).execute()`` and
reads the first row of ``.data`` if any. These tests pin the new
behaviour:

* On empty result, the upsert path runs the INSERT (not silently
  swallowed by an exception).
* On existing row, the merged-set UPDATE fires with the right hit_count
  bump and the union of asset ids.
* When ``campaign_id`` is provided, the lookup filters by it; when None,
  the lookup uses ``IS NULL`` (matching the migration 016 unique
  constraint which treats NULL distinctly from a UUID).
* No spurious second query — the previous implementation always issued
  the no-campaign lookup and then re-issued with-campaign if set.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


class _FakeQuery:
    """Captures every chained call so a test can inspect what the
    service builds, then returns the response payload the test sets up
    in advance.

    Mirrors the subset of the supabase-py builder we touch:
    ``.select()``, ``.eq()``, ``.is_()``, ``.limit()``, ``.update()``,
    ``.insert()``, ``.execute()``.
    """
    def __init__(self, store: List[Dict[str, Any]], op_type: str = "select"):
        self._store = store
        self.op = op_type
        self.filters: Dict[str, Any] = {}
        self.is_filters: Dict[str, Any] = {}
        self._payload: Optional[Dict[str, Any]] = None
        self.calls: List[str] = []

    def select(self, *_a, **_kw):
        self.calls.append("select")
        return self

    def insert(self, payload):
        self.calls.append("insert")
        self.op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self.calls.append("update")
        self.op = "update"
        self._payload = payload
        return self

    def eq(self, key, value):
        self.calls.append(f"eq({key})")
        self.filters[key] = value
        return self

    def is_(self, key, value):
        self.calls.append(f"is_({key},{value})")
        self.is_filters[key] = value
        return self

    def limit(self, _n):
        self.calls.append("limit")
        return self

    def execute(self):
        self.calls.append("execute")
        # Persist the captured payload to the shared store so the test
        # can assert on ordering / content across multiple calls.
        self._store.append({
            "op": self.op,
            "filters": dict(self.filters),
            "is_filters": dict(self.is_filters),
            "payload": self._payload,
            "calls": list(self.calls),
        })
        # The service reads ``.data`` after every execute. Default to
        # an empty list (no existing row) — tests override per-fixture.
        result = MagicMock()
        result.data = self._store_response.get(self._signature_key(), [])
        return result

    @property
    def _store_response(self) -> Dict[str, List[Dict[str, Any]]]:
        # Pulled from the shared override map the test sets up.
        return getattr(self, "_overrides", {})

    def _signature_key(self) -> str:
        # Stable identity for the (op, filters) we just executed —
        # tests use this to seed "the row already exists with these
        # fields" responses for specific eq/is_ combinations.
        bits = [self.op]
        for k in sorted(self.filters):
            bits.append(f"{k}={self.filters[k]}")
        for k in sorted(self.is_filters):
            bits.append(f"{k} IS {self.is_filters[k]}")
        return "|".join(bits)


class _FakeTable:
    def __init__(self, store: List[Dict[str, Any]], overrides: Dict[str, List[Dict[str, Any]]]):
        self._store = store
        self._overrides = overrides

    def select(self, *a, **kw):
        q = _FakeQuery(self._store, op_type="select")
        q._overrides = self._overrides
        return q.select(*a, **kw)

    def insert(self, payload):
        q = _FakeQuery(self._store, op_type="insert")
        q._overrides = self._overrides
        return q.insert(payload)

    def update(self, payload):
        q = _FakeQuery(self._store, op_type="update")
        q._overrides = self._overrides
        return q.update(payload)


class _FakeSupabase:
    def __init__(self, overrides: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.calls: List[Dict[str, Any]] = []
        self._overrides = overrides or {}

    def table(self, name):
        assert name == "page_hit_cache", f"unexpected table {name!r}"
        return _FakeTable(self.calls, self._overrides)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecordPageHitsInsert:
    """The empty-result case is what the .maybe_single() bug was hiding
    — when no row exists, the service must INSERT a fresh one, not raise."""

    def test_no_existing_row_inserts_with_campaign_filter(self):
        from app.services import page_cache_service

        fake = _FakeSupabase()  # all selects return [] → "row not found"
        with patch.object(page_cache_service, "supabase", fake):
            page_cache_service.record_page_hits(
                org_id="org-1",
                distributor_id="dist-1",
                campaign_id="camp-1",
                page_matches={"https://example.com/promo": {"asset-1", "asset-2"}},
            )

        # Exactly two ops: one SELECT (to find existing) + one INSERT.
        # NOT three (the old bug always re-ran the SELECT with the
        # campaign filter on top of the campaign-less one).
        ops = [c["op"] for c in fake.calls]
        assert ops == ["select", "insert"], f"expected [select, insert], got {ops}"

        select_call = fake.calls[0]
        # Lookup must filter by org+dist+page_url AND campaign_id.
        assert select_call["filters"]["organization_id"] == "org-1"
        assert select_call["filters"]["distributor_id"] == "dist-1"
        assert select_call["filters"]["page_url"] == "https://example.com/promo"
        assert select_call["filters"]["campaign_id"] == "camp-1"

        insert_call = fake.calls[1]
        payload = insert_call["payload"]
        assert payload["organization_id"] == "org-1"
        assert payload["distributor_id"] == "dist-1"
        assert payload["campaign_id"] == "camp-1"
        assert payload["page_url"] == "https://example.com/promo"
        assert payload["hit_count"] == 1
        assert set(payload["asset_ids_matched"]) == {"asset-1", "asset-2"}
        assert "last_hit_at" in payload

    def test_no_existing_row_no_campaign_uses_is_null(self):
        """Without a campaign id, the lookup must filter
        ``campaign_id IS NULL`` so it doesn't accidentally match a
        per-campaign row that exists for a different campaign."""
        from app.services import page_cache_service

        fake = _FakeSupabase()
        with patch.object(page_cache_service, "supabase", fake):
            page_cache_service.record_page_hits(
                org_id="org-1",
                distributor_id="dist-1",
                campaign_id=None,
                page_matches={"https://example.com/page": {"asset-7"}},
            )

        ops = [c["op"] for c in fake.calls]
        assert ops == ["select", "insert"]
        select_call = fake.calls[0]
        # ``campaign_id`` must NOT appear in eq filters when there's no
        # campaign — the service uses .is_("campaign_id", "null") instead.
        assert "campaign_id" not in select_call["filters"]
        assert select_call["is_filters"].get("campaign_id") == "null"

        # Insert payload still records ``campaign_id=None`` literally.
        insert_payload = fake.calls[1]["payload"]
        assert insert_payload["campaign_id"] is None

    def test_failed_insert_does_not_explode_caller(self):
        """The ``except`` branch must keep the loop alive so a single
        bad row doesn't take down the rest of the page hits."""
        from app.services import page_cache_service

        # Fake table whose insert raises — confirms record_page_hits
        # logs and continues rather than propagating.
        class _BoomTable(_FakeTable):
            def insert(self, payload):
                raise RuntimeError("simulated supabase failure")

        class _BoomSupabase(_FakeSupabase):
            def table(self, name):
                return _BoomTable(self.calls, self._overrides)

        fake = _BoomSupabase()
        with patch.object(page_cache_service, "supabase", fake):
            page_cache_service.record_page_hits(
                org_id="org-1",
                distributor_id="dist-1",
                campaign_id=None,
                page_matches={
                    "https://example.com/a": {"asset-1"},
                    "https://example.com/b": {"asset-2"},
                },
            )
        # No raise — the function must swallow the exception and move on.


class TestRecordPageHitsUpdate:
    """When a row already exists, hit_count must increment and the
    asset id set must merge with the existing one."""

    def test_existing_row_merges_assets_and_bumps_hit_count(self):
        from app.services import page_cache_service

        # Pre-seed: when the SELECT runs with campaign='camp-1' filter,
        # return a row that already has asset-1.
        existing_row = {
            "id": "cache-row-id",
            "hit_count": 3,
            "asset_ids_matched": ["asset-1"],
        }
        # Key matches the (op, filters, is_filters) signature the
        # service will produce. We construct it manually below.
        overrides = {
            "select|"
            "campaign_id=camp-1|"
            "distributor_id=dist-1|"
            "organization_id=org-1|"
            "page_url=https://example.com/promo": [existing_row],
        }
        fake = _FakeSupabase(overrides=overrides)
        with patch.object(page_cache_service, "supabase", fake):
            page_cache_service.record_page_hits(
                org_id="org-1",
                distributor_id="dist-1",
                campaign_id="camp-1",
                page_matches={"https://example.com/promo": {"asset-2"}},
            )

        ops = [c["op"] for c in fake.calls]
        assert ops == ["select", "update"], f"expected [select, update], got {ops}"

        update_call = fake.calls[1]
        payload = update_call["payload"]
        assert payload["hit_count"] == 4  # 3 + 1
        # Asset set must be the union, regardless of order.
        assert set(payload["asset_ids_matched"]) == {"asset-1", "asset-2"}
        assert "last_hit_at" in payload
        # Update must filter by the row id surfaced by the lookup.
        assert update_call["filters"].get("id") == "cache-row-id"


class TestRecordPageHitsNoOp:
    def test_empty_page_matches_does_nothing(self):
        from app.services import page_cache_service

        fake = _FakeSupabase()
        with patch.object(page_cache_service, "supabase", fake):
            page_cache_service.record_page_hits(
                org_id="org-1",
                distributor_id="dist-1",
                campaign_id=None,
                page_matches={},
            )
        assert fake.calls == []
