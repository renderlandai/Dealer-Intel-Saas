"""Unit tests for the scan-pipeline bulk-write helpers."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_db():
    """Patch the supabase proxy used by bulk_writers with a fresh mock."""
    with patch("app.services.bulk_writers.supabase") as mock:
        # Default: every insert/.execute() returns a response with one row.
        mock.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "row-1"}],
        )
        yield mock


# ---------------------------------------------------------------------------
# discovered_images
# ---------------------------------------------------------------------------

class TestSafeInsertDiscoveredImage:
    def test_inserts_in_one_call_on_happy_path(self, mock_db):
        from app.services.bulk_writers import _safe_insert_discovered_image

        ok = _safe_insert_discovered_image({"image_url": "x", "distributor_id": "d1"})

        assert ok is True
        mock_db.table.assert_called_with("discovered_images")
        mock_db.table.return_value.insert.assert_called_once_with(
            {"image_url": "x", "distributor_id": "d1"}
        )

    def test_retries_without_distributor_on_fk_23503(self, mock_db):
        from app.services.bulk_writers import _safe_insert_discovered_image

        # First insert raises FK violation; the second (without distributor_id) succeeds.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("ERROR 23503: foreign key violation on distributor_id"),
            MagicMock(data=[{"id": "row-1"}]),
        ]

        ok = _safe_insert_discovered_image({"image_url": "x", "distributor_id": "d1"})

        assert ok is True
        # Two insert() calls were made; the retry should have cleared distributor_id.
        calls = mock_db.table.return_value.insert.call_args_list
        assert len(calls) == 2
        assert calls[1].args[0]["distributor_id"] is None

    def test_returns_false_when_retry_also_fails(self, mock_db):
        from app.services.bulk_writers import _safe_insert_discovered_image

        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("23503 fk"),
            Exception("still broken"),
        ]

        ok = _safe_insert_discovered_image({"image_url": "x", "distributor_id": "d1"})

        assert ok is False

    def test_non_fk_error_returns_false(self, mock_db):
        from app.services.bulk_writers import _safe_insert_discovered_image

        mock_db.table.return_value.insert.return_value.execute.side_effect = Exception(
            "rate limited"
        )

        ok = _safe_insert_discovered_image({"image_url": "x"})

        assert ok is False


class TestBulkInsertDiscoveredImages:
    def test_empty_rows_returns_zero_without_calling_db(self, mock_db):
        from app.services.bulk_writers import bulk_insert_discovered_images

        assert bulk_insert_discovered_images([]) == 0
        mock_db.table.assert_not_called()

    def test_bulk_insert_passes_full_list_in_one_call(self, mock_db):
        from app.services.bulk_writers import bulk_insert_discovered_images

        rows = [{"image_url": f"u{i}"} for i in range(5)]
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": str(i)} for i in range(5)],
        )

        n = bulk_insert_discovered_images(rows)

        assert n == 5
        mock_db.table.return_value.insert.assert_called_once_with(rows)

    def test_falls_back_to_per_row_on_batch_failure(self, mock_db):
        from app.services.bulk_writers import bulk_insert_discovered_images

        rows = [{"image_url": "a"}, {"image_url": "b"}, {"image_url": "c"}]
        # Batch insert raises; per-row inserts all succeed.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("payload too large"),
            MagicMock(data=[{"id": "1"}]),
            MagicMock(data=[{"id": "2"}]),
            MagicMock(data=[{"id": "3"}]),
        ]

        n = bulk_insert_discovered_images(rows)

        assert n == 3
        # 1 batch + 3 per-row = 4 total insert calls
        assert mock_db.table.return_value.insert.call_count == 4


class TestDiscoveredImageBuffer:
    def test_auto_flushes_at_batch_size(self, mock_db):
        from app.services.bulk_writers import DiscoveredImageBuffer

        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": str(i)} for i in range(3)],
        )
        buf = DiscoveredImageBuffer(batch_size=3)

        for i in range(3):
            buf.add({"image_url": f"u{i}"})

        # One auto-flush of 3 rows should have happened.
        assert mock_db.table.return_value.insert.call_count == 1
        assert buf.total_inserted == 3

    def test_flush_all_persists_remainder_and_returns_cumulative(self, mock_db):
        from app.services.bulk_writers import DiscoveredImageBuffer

        # Each flush returns its row count.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[{"id": "a"}, {"id": "b"}]),  # auto-flush of 2
            MagicMock(data=[{"id": "c"}]),               # final flush of 1
        ]
        buf = DiscoveredImageBuffer(batch_size=2)
        buf.add({"image_url": "a"})
        buf.add({"image_url": "b"})  # triggers auto-flush
        buf.add({"image_url": "c"})

        total = buf.flush_all()

        assert total == 3
        assert mock_db.table.return_value.insert.call_count == 2

    def test_flush_all_with_empty_buffer_is_safe(self, mock_db):
        from app.services.bulk_writers import DiscoveredImageBuffer

        buf = DiscoveredImageBuffer()
        assert buf.flush_all() == 0
        mock_db.table.assert_not_called()


# ---------------------------------------------------------------------------
# matches (+ alerts)
# ---------------------------------------------------------------------------

class TestBulkInsertMatches:
    def test_empty_items_returns_empty_list(self, mock_db):
        from app.services.bulk_writers import bulk_insert_matches

        assert bulk_insert_matches([]) == []
        mock_db.table.assert_not_called()

    def test_inserts_matches_and_alerts_in_two_calls(self, mock_db):
        from app.services.bulk_writers import bulk_insert_matches, PendingMatch

        items = [
            PendingMatch(
                payload={"asset_id": "a1"},
                alert_template={"organization_id": "o1", "title": "v"},
            ),
            PendingMatch(payload={"asset_id": "a2"}),  # no alert
        ]

        # Bulk match insert returns both rows (with ids), then bulk alerts insert succeeds.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[{"id": "m1", "asset_id": "a1"},
                            {"id": "m2", "asset_id": "a2"}]),
            MagicMock(data=[{"id": "alert-1"}]),
        ]

        results = bulk_insert_matches(items)

        assert [r["id"] for r in results] == ["m1", "m2"]
        # First call: matches table; second call: alerts table.
        table_calls = [c.args[0] for c in mock_db.table.call_args_list]
        assert table_calls == ["matches", "alerts"]
        # The alert payload should have been hydrated with match_id=m1.
        alert_call = mock_db.table.return_value.insert.call_args_list[1]
        assert alert_call.args[0] == [
            {"organization_id": "o1", "title": "v", "match_id": "m1"},
        ]

    def test_falls_back_to_per_row_on_batch_failure(self, mock_db):
        from app.services.bulk_writers import bulk_insert_matches, PendingMatch

        items = [
            PendingMatch(payload={"asset_id": "a1"}),
            PendingMatch(payload={"asset_id": "a2"}),
        ]

        # Batch fails; per-row inserts each succeed; no alerts to write.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("batch boom"),
            MagicMock(data=[{"id": "m1"}]),
            MagicMock(data=[{"id": "m2"}]),
        ]

        results = bulk_insert_matches(items)

        assert [r["id"] for r in results] == ["m1", "m2"]
        # 1 failed batch + 2 per-row = 3 insert calls on `matches`.
        assert mock_db.table.return_value.insert.call_count == 3

    def test_individual_failure_marked_none_and_skips_alert(self, mock_db):
        from app.services.bulk_writers import bulk_insert_matches, PendingMatch

        items = [
            PendingMatch(
                payload={"asset_id": "a1"},
                alert_template={"organization_id": "o1"},
            ),
        ]

        # Batch fails; per-row also fails — should yield None and no alert call.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("batch boom"),
            Exception("row boom"),
        ]

        results = bulk_insert_matches(items)

        assert results == [None]
        # Only matches table touched (twice, both failures); alerts never queried.
        table_calls = [c.args[0] for c in mock_db.table.call_args_list]
        assert "alerts" not in table_calls


class TestMatchBuffer:
    def test_auto_flushes_at_batch_size(self, mock_db):
        from app.services.bulk_writers import MatchBuffer

        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "m1"}, {"id": "m2"}],
        )
        buf = MatchBuffer(batch_size=2)

        buf.add({"asset_id": "a1"})
        buf.add({"asset_id": "a2"})  # triggers auto-flush

        assert buf.total_inserted == 2
        assert mock_db.table.return_value.insert.call_count == 1

    def test_flush_all_drains_remainder(self, mock_db):
        from app.services.bulk_writers import MatchBuffer

        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "m1"}],
        )
        buf = MatchBuffer(batch_size=10)
        buf.add({"asset_id": "a1"})

        total = buf.flush_all()

        assert total == 1

    def test_failed_inserts_increment_total_failed(self, mock_db):
        from app.services.bulk_writers import MatchBuffer

        # Batch fails; per-row also fails for both items.
        mock_db.table.return_value.insert.return_value.execute.side_effect = [
            Exception("batch boom"),
            Exception("row 1 boom"),
            Exception("row 2 boom"),
        ]
        buf = MatchBuffer(batch_size=2)
        buf.add({"asset_id": "a1"})
        buf.add({"asset_id": "a2"})  # triggers flush

        assert buf.total_inserted == 0
        assert buf.total_failed == 2


# ---------------------------------------------------------------------------
# discovered_images.is_processed (Phase 4.7)
# ---------------------------------------------------------------------------

class TestBulkMarkImagesProcessed:
    def test_empty_list_returns_zero_without_calling_db(self, mock_db):
        from app.services.bulk_writers import bulk_mark_images_processed

        assert bulk_mark_images_processed([]) == 0
        mock_db.table.assert_not_called()

    def test_marks_all_ids_in_one_bulk_update(self, mock_db):
        from app.services.bulk_writers import bulk_mark_images_processed

        ids = [f"img-{i}" for i in range(5)]
        n = bulk_mark_images_processed(ids)

        assert n == 5
        mock_db.table.assert_called_with("discovered_images")
        mock_db.table.return_value.update.assert_called_once_with({"is_processed": True})
        mock_db.table.return_value.update.return_value.in_.assert_called_once_with("id", ids)
        # The per-row .eq path must not be touched on the happy path.
        mock_db.table.return_value.update.return_value.eq.assert_not_called()

    def test_falls_back_to_per_row_on_bulk_failure(self, mock_db):
        from app.services.bulk_writers import bulk_mark_images_processed

        # Bulk update raises; each per-row update succeeds.
        mock_db.table.return_value.update.return_value.in_.return_value.execute.side_effect = (
            Exception("payload too large")
        )
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": "x"}])
        )

        n = bulk_mark_images_processed(["a", "b", "c"])

        assert n == 3
        # 1 bulk attempt + 3 per-row attempts.
        assert mock_db.table.return_value.update.return_value.in_.call_count == 1
        assert mock_db.table.return_value.update.return_value.eq.call_count == 3

    def test_per_row_partial_failure_returns_success_count(self, mock_db):
        from app.services.bulk_writers import bulk_mark_images_processed

        mock_db.table.return_value.update.return_value.in_.return_value.execute.side_effect = (
            Exception("bulk boom")
        )
        # Middle row fails; others succeed.
        mock_db.table.return_value.update.return_value.eq.return_value.execute.side_effect = [
            MagicMock(data=[{"id": "a"}]),
            Exception("row b boom"),
            MagicMock(data=[{"id": "c"}]),
        ]

        n = bulk_mark_images_processed(["a", "b", "c"])

        assert n == 2


class TestProcessedImageBuffer:
    def test_auto_flushes_at_batch_size(self, mock_db):
        from app.services.bulk_writers import ProcessedImageBuffer

        buf = ProcessedImageBuffer(batch_size=3)
        for i in range(3):
            buf.add(f"img-{i}")

        # One bulk UPDATE should have fired; per-row path untouched.
        assert mock_db.table.return_value.update.return_value.in_.call_count == 1
        mock_db.table.return_value.update.return_value.in_.assert_called_with(
            "id", ["img-0", "img-1", "img-2"],
        )
        assert buf.total_marked == 3

    def test_flush_all_drains_remainder_and_returns_cumulative(self, mock_db):
        from app.services.bulk_writers import ProcessedImageBuffer

        buf = ProcessedImageBuffer(batch_size=2)
        buf.add("a")
        buf.add("b")  # auto-flush of 2
        buf.add("c")  # remainder

        total = buf.flush_all()

        assert total == 3
        # Two bulk UPDATEs: one for the auto-flush, one for the remainder.
        assert mock_db.table.return_value.update.return_value.in_.call_count == 2

    def test_flush_all_with_empty_buffer_is_safe(self, mock_db):
        from app.services.bulk_writers import ProcessedImageBuffer

        buf = ProcessedImageBuffer()
        assert buf.flush_all() == 0
        mock_db.table.assert_not_called()

    def test_add_ignores_falsy_ids(self, mock_db):
        from app.services.bulk_writers import ProcessedImageBuffer

        buf = ProcessedImageBuffer(batch_size=10)
        buf.add("")
        buf.add(None)  # type: ignore[arg-type]

        assert buf.flush_all() == 0
        mock_db.table.assert_not_called()
