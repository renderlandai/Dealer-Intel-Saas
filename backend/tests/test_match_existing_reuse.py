"""Coverage for the "scan once, audit many campaigns" reuse path.

`match_existing_images_against_campaign` re-runs the (cheap) matcher over a
prior scan's already-discovered creatives against an arbitrary campaign —
NO new Apify / website discovery. These tests assert the reuse contract:

1. It ignores `is_processed` (pulls every discovered image for the scan).
2. It drops full-page "blocked_evidence" rows before matching.
3. It restricts campaign assets to those eligible for the scan's source.
4. It runs `run_image_analysis` against the chosen campaign's assets.
5. It runs `_prune_duplicate_matches` afterwards for idempotency.
6. It short-circuits (no analysis) when there are no eligible assets.

Async coroutines are driven via plain `asyncio.run(...)` because the
project does not depend on `pytest-asyncio`.
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


SCAN_JOB_ID = uuid4()
CAMPAIGN_ID = uuid4()
ORG_ID = str(uuid4())


def _run(coro):
    return asyncio.run(coro)


class _Chain:
    """Chainable stand-in for a supabase-py query builder.

    Every builder method returns ``self`` so any `.select().eq().single()`
    or `.update().eq()` ordering works; `.execute()` returns the preset
    result for the table.
    """

    def __init__(self, result):
        self._result = result

    def select(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def insert(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self, *a, **k):
        return self

    def execute(self):
        return self._result


class _FakeSupabase:
    def __init__(self, results):
        self._results = results

    def table(self, name):
        return _Chain(self._results[name])


def _results(*, images, assets, source="facebook", rules=None):
    return {
        "scan_jobs": SimpleNamespace(
            data={"organization_id": ORG_ID, "source": source},
        ),
        "discovered_images": SimpleNamespace(data=images),
        "assets": SimpleNamespace(data=assets),
        "compliance_rules": SimpleNamespace(data=rules or []),
    }


def _patched(results, analysis, prune, notify=None):
    from app.services import scan_runners

    return patch.multiple(
        scan_runners,
        supabase=_FakeSupabase(results),
        run_image_analysis=analysis,
        _prune_duplicate_matches=prune,
        # Patched out in the runner unit tests so they don't fire real
        # emails / integrations; exercised for real in
        # ``TestReuseCompletionEmail`` below.
        _send_scan_notifications=notify or MagicMock(),
    )


class TestReuseMatcher:
    def test_ignores_is_processed_and_drops_evidence_rows(self):
        from app.services import scan_runners

        images = [
            {"id": "img1", "metadata": {}, "is_processed": True},
            {"id": "img2", "metadata": {"capture_method": "blocked_evidence"}},
            {"id": "img3", "metadata": {}, "is_processed": False},
        ]
        assets = [{"id": "a1", "target_platforms": ["facebook"]}]
        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)

        with _patched(_results(images=images, assets=assets), analysis, prune):
            count = _run(
                scan_runners.match_existing_images_against_campaign(
                    SCAN_JOB_ID, CAMPAIGN_ID,
                )
            )

        # img2 (evidence) dropped; img1 + img3 matched despite is_processed.
        assert count == 2
        analysis.assert_awaited_once()
        passed_images = analysis.await_args.args[0]
        assert {i["id"] for i in passed_images} == {"img1", "img3"}
        prune.assert_awaited_once_with(SCAN_JOB_ID)

    def test_filters_assets_to_scan_source(self):
        from app.services import scan_runners

        images = [{"id": "img1", "metadata": {}}]
        assets = [
            {"id": "a1", "target_platforms": ["facebook"]},
            {"id": "a2", "target_platforms": ["website"]},
            {"id": "a3", "target_platforms": []},  # no restriction -> eligible
        ]
        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)

        with _patched(
            _results(images=images, assets=assets, source="facebook"),
            analysis, prune,
        ):
            _run(
                scan_runners.match_existing_images_against_campaign(
                    SCAN_JOB_ID, CAMPAIGN_ID,
                )
            )

        passed_assets = analysis.await_args.args[1]
        assert {a["id"] for a in passed_assets} == {"a1", "a3"}

    def test_no_eligible_assets_skips_analysis(self):
        from app.services import scan_runners

        images = [{"id": "img1", "metadata": {}}]
        assets = [{"id": "a2", "target_platforms": ["website"]}]
        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)

        with _patched(
            _results(images=images, assets=assets, source="facebook"),
            analysis, prune,
        ):
            count = _run(
                scan_runners.match_existing_images_against_campaign(
                    SCAN_JOB_ID, CAMPAIGN_ID,
                )
            )

        assert count == 0
        analysis.assert_not_awaited()
        prune.assert_not_awaited()

    def test_writes_to_tracking_row_and_prunes_source(self):
        from app.services import scan_runners

        tracking_id = uuid4()
        source_id = uuid4()
        images = [{"id": "img1", "metadata": {}}]
        assets = [{"id": "a1", "target_platforms": ["facebook"]}]
        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)
        notify = MagicMock()

        with _patched(
            _results(images=images, assets=assets), analysis, prune, notify,
        ):
            count = _run(
                scan_runners.match_existing_images_against_campaign(
                    tracking_id, CAMPAIGN_ID, source_id,
                )
            )

        assert count == 1
        # run_image_analysis writes results onto the TRACKING row, not source.
        assert analysis.await_args.args[4] == str(tracking_id)
        # prune is keyed off the SOURCE scan (where discovered images live).
        prune.assert_awaited_once_with(source_id)
        # The completion email reports on the TRACKING row but must look up
        # creatives under the SOURCE scan and scope to the target campaign.
        notify.assert_called_once()
        kwargs = notify.call_args.kwargs
        assert notify.call_args.args[0] == tracking_id
        assert kwargs["image_scan_job_id"] == source_id
        assert kwargs["campaign_id"] == CAMPAIGN_ID

    def test_skips_email_when_nothing_to_match(self):
        from app.services import scan_runners

        images = [{"id": "img1", "metadata": {}}]
        assets = [{"id": "a2", "target_platforms": ["website"]}]  # ineligible
        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)
        notify = MagicMock()

        with _patched(
            _results(images=images, assets=assets, source="facebook"),
            analysis, prune, notify,
        ):
            _run(
                scan_runners.match_existing_images_against_campaign(
                    SCAN_JOB_ID, CAMPAIGN_ID,
                )
            )

        # No audit ran -> no "scan complete" email for a no-op.
        notify.assert_not_called()

    def test_no_discovered_images_returns_zero(self):
        from app.services import scan_runners

        analysis = AsyncMock()
        prune = AsyncMock(return_value=0)

        with _patched(
            _results(images=[], assets=[{"id": "a1", "target_platforms": []}]),
            analysis, prune,
        ):
            count = _run(
                scan_runners.match_existing_images_against_campaign(
                    SCAN_JOB_ID, CAMPAIGN_ID,
                )
            )

        assert count == 0
        analysis.assert_not_awaited()


class TestReuseTaskWrapper:
    """The dispatch wrapper must forward all three ids to the runner."""

    def test_run_match_existing_forwards_source_id(self):
        from app import tasks

        tracking_id = str(uuid4())
        campaign_id = str(uuid4())
        source_id = str(uuid4())

        runner = AsyncMock(return_value=3)
        with patch(
            "app.services.scan_runners.match_existing_images_against_campaign",
            runner,
        ):
            _run(tasks._run_match_existing(tracking_id, campaign_id, source_id))

        runner.assert_awaited_once()
        args = runner.await_args.args
        assert str(args[0]) == tracking_id
        assert str(args[1]) == campaign_id
        assert str(args[2]) == source_id

    def test_run_match_existing_requires_campaign(self):
        from app import tasks

        tracking_id = str(uuid4())
        runner = AsyncMock()
        with patch(
            "app.services.scan_runners.match_existing_images_against_campaign",
            runner,
        ), patch.object(tasks, "_mark_job_failed") as mark_failed:
            _run(tasks._run_match_existing(tracking_id, "", None))

        runner.assert_not_awaited()
        mark_failed.assert_called_once()


# ---------------------------------------------------------------------------
# Completion email correctness for the reuse pass.
#
# The creatives live under the SOURCE scan, while org / totals live on the
# fresh TRACKING row. The email must (a) look up images by the source scan,
# and (b) scope match counts to the TARGET campaign so it never counts
# another campaign's matches against the same shared creatives.
# ---------------------------------------------------------------------------

class _NotifChain:
    def __init__(self, name, fake):
        self.name = name
        self.fake = fake
        self.eqs = {}
        self.ins = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.eqs[col] = val
        return self

    def in_(self, col, vals):
        self.ins[col] = list(vals)
        return self

    def single(self, *a, **k):
        return self

    def execute(self):
        f = self.fake
        if self.name == "scan_jobs":
            return SimpleNamespace(data=f.job)
        if self.name == "discovered_images":
            want = self.eqs.get("scan_job_id")
            rows = [i for i in f.images if i.get("scan_job_id") == want]
            return SimpleNamespace(data=[{"id": i["id"]} for i in rows])
        if self.name == "assets":
            want = self.eqs.get("campaign_id")
            rows = [a for a in f.assets if a.get("campaign_id") == want]
            return SimpleNamespace(data=[{"id": a["id"]} for a in rows])
        if self.name == "matches":
            rows = list(f.matches)
            if "discovered_image_id" in self.ins:
                ids = set(self.ins["discovered_image_id"])
                rows = [m for m in rows if m["discovered_image_id"] in ids]
            if "asset_id" in self.ins:
                aset = set(self.ins["asset_id"])
                rows = [m for m in rows if m["asset_id"] in aset]
            if self.eqs.get("compliance_status"):
                rows = [
                    m for m in rows
                    if m.get("compliance_status") == self.eqs["compliance_status"]
                ]
            return SimpleNamespace(data=rows)
        return SimpleNamespace(data=[])


class _NotifFake:
    def __init__(self, job, images, assets, matches):
        self.job = job
        self.images = images
        self.assets = assets
        self.matches = matches

    def table(self, name):
        return _NotifChain(name, self)


class TestReuseCompletionEmail:
    def test_email_scoped_to_source_images_and_target_campaign(self):
        from app.services import scan_runners

        tracking_id = uuid4()
        source_id = uuid4()
        campaign_b = uuid4()

        # Tracking row carries org + totals; it has NO discovered images.
        job = {
            "organization_id": ORG_ID,
            "total_items": 2,
            "processed_items": 2,
            "matches_count": 2,
        }
        # Creatives live under the SOURCE scan.
        images = [
            {"id": "i1", "scan_job_id": str(source_id)},
            {"id": "i2", "scan_job_id": str(source_id)},
        ]
        assets = [
            {"id": "aB", "campaign_id": str(campaign_b)},
            {"id": "aA", "campaign_id": str(uuid4())},  # other campaign
        ]
        matches = [
            {"discovered_image_id": "i1", "asset_id": "aB",
             "compliance_status": "compliant"},
            {"discovered_image_id": "i2", "asset_id": "aB",
             "compliance_status": "violation", "id": "m2",
             "ai_analysis": {"compliance": {"summary": "bad"}},
             "assets": {"name": "Asset B"}, "distributors": {"name": "Dealer"}},
            # Another campaign's violation on the SAME source creative —
            # must NOT be counted in this reuse email.
            {"discovered_image_id": "i1", "asset_id": "aA",
             "compliance_status": "violation", "id": "mX"},
        ]

        fake = _NotifFake(job, images, assets, matches)
        scan_complete = MagicMock()

        with patch.multiple(
            scan_runners,
            supabase=fake,
            notify_scan_complete=scan_complete,
            notify_slack_scan_complete=MagicMock(),
            notify_salesforce_scan_complete=MagicMock(),
            notify_jira_scan_complete=MagicMock(),
            push_compliance_to_salesforce=MagicMock(),
            push_compliance_to_hubspot=MagicMock(),
        ):
            scan_runners._send_scan_notifications(
                tracking_id,
                scan_source="facebook",
                pipeline_stats={"matched_new": 2, "total_images": 2},
                image_scan_job_id=source_id,
                campaign_id=campaign_b,
            )

        scan_complete.assert_called_once()
        summary = scan_complete.call_args.kwargs["summary"]
        violations = scan_complete.call_args.kwargs["violations"]
        # Only campaign B's two matches counted (aA violation excluded).
        assert summary["compliant"] == 1
        assert summary["violations"] == 1
        assert len(violations) == 1
        assert violations[0]["match_id"] == "m2"

    def test_email_finds_no_images_without_source_override(self):
        """Sanity: without the source override the tracking row has 0 images,
        proving the override is what makes the reuse email non-empty."""
        from app.services import scan_runners

        tracking_id = uuid4()
        source_id = uuid4()
        campaign_b = uuid4()

        job = {"organization_id": ORG_ID, "matches_count": 0}
        images = [{"id": "i1", "scan_job_id": str(source_id)}]
        assets = [{"id": "aB", "campaign_id": str(campaign_b)}]
        matches = [{"discovered_image_id": "i1", "asset_id": "aB",
                    "compliance_status": "violation", "id": "m1"}]

        fake = _NotifFake(job, images, assets, matches)
        scan_complete = MagicMock()

        with patch.multiple(
            scan_runners,
            supabase=fake,
            notify_scan_complete=scan_complete,
            notify_slack_scan_complete=MagicMock(),
            notify_salesforce_scan_complete=MagicMock(),
            notify_jira_scan_complete=MagicMock(),
            push_compliance_to_salesforce=MagicMock(),
            push_compliance_to_hubspot=MagicMock(),
        ):
            # No image_scan_job_id -> looks up images under the tracking row,
            # which has none.
            scan_runners._send_scan_notifications(
                tracking_id,
                scan_source="facebook",
                campaign_id=campaign_b,
            )

        summary = scan_complete.call_args.kwargs["summary"]
        assert summary["violations"] == 0


# ---------------------------------------------------------------------------
# End-to-end HTTP: POST /scans/{job_id}/match-campaign must create a FRESH
# pending tracking row (so the worker-handoff deploy can claim it) and
# dispatch the reuse task with [tracking_id, campaign_id, source_id].
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


def _endpoint_table_router(*, job_row, campaign_row, di_count, asset_count,
                           reuse_id, org_id):
    def router(name):
        t = MagicMock()
        if name == "user_profiles":
            t.select.return_value.eq.return_value.single.return_value\
                .execute.return_value = MagicMock(
                    data={"organization_id": str(org_id), "role": "owner"})
        elif name == "scan_jobs":
            t.select.return_value.eq.return_value.eq.return_value.single\
                .return_value.execute.return_value = MagicMock(data=job_row)
            t.insert.return_value.execute.return_value = MagicMock(
                data=[{"id": reuse_id}])
        elif name == "campaigns":
            t.select.return_value.eq.return_value.eq.return_value.single\
                .return_value.execute.return_value = MagicMock(data=campaign_row)
        elif name == "discovered_images":
            t.select.return_value.eq.return_value.execute.return_value = \
                MagicMock(count=di_count)
        elif name == "assets":
            t.select.return_value.eq.return_value.execute.return_value = \
                MagicMock(count=asset_count)
        return t

    return router


class TestReuseEndpoint:
    def test_creates_pending_tracking_row_and_dispatches(
        self, client, mock_supabase,
    ):
        job_id = uuid4()
        campaign_id = uuid4()
        reuse_id = str(uuid4())

        mock_supabase.table.side_effect = _endpoint_table_router(
            job_row={
                "id": str(job_id),
                "status": "completed",
                "source": "facebook",
                "distributor_id": str(uuid4()),
                "organization_id": str(ORG_A_ID),
            },
            campaign_row={"id": str(campaign_id)},
            di_count=3,
            asset_count=2,
            reuse_id=reuse_id,
            org_id=ORG_A_ID,
        )

        dispatch = AsyncMock(return_value=reuse_id)
        with patch("app.tasks.dispatch_task", dispatch):
            resp = client.post(
                f"/api/v1/scans/{job_id}/match-campaign"
                f"?campaign_id={campaign_id}",
                headers={"Authorization": f"Bearer {_token(USER_A_ID)}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["job_id"] == reuse_id
        assert body["source_scan_job_id"] == str(job_id)
        assert body["image_count"] == 3
        assert body["asset_count"] == 2

        # A fresh pending tracking row must be inserted for the reuse pass.
        insert_calls = [
            c for c in mock_supabase.table.call_args_list
            if c.args and c.args[0] == "scan_jobs"
        ]
        assert insert_calls, "scan_jobs table should be used"

        # The task is dispatched with [tracking_id, campaign_id, source_id].
        dispatch.assert_awaited_once()
        args = dispatch.await_args.args
        assert args[0] == "run_match_existing_task"
        assert args[1] == [reuse_id, str(campaign_id), str(job_id)]
        assert args[2] == reuse_id
        assert args[3] == "match_existing"

    def test_rejects_incomplete_source_scan(self, client, mock_supabase):
        job_id = uuid4()
        campaign_id = uuid4()

        mock_supabase.table.side_effect = _endpoint_table_router(
            job_row={
                "id": str(job_id),
                "status": "running",
                "source": "facebook",
                "organization_id": str(ORG_A_ID),
            },
            campaign_row={"id": str(campaign_id)},
            di_count=3,
            asset_count=2,
            reuse_id=str(uuid4()),
            org_id=ORG_A_ID,
        )

        dispatch = AsyncMock()
        with patch("app.tasks.dispatch_task", dispatch):
            resp = client.post(
                f"/api/v1/scans/{job_id}/match-campaign"
                f"?campaign_id={campaign_id}",
                headers={"Authorization": f"Bearer {_token(USER_A_ID)}"},
            )

        assert resp.status_code == 400
        dispatch.assert_not_awaited()
