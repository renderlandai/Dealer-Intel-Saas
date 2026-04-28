"""Unit tests for deep links in scan-completion notifications.

Each notification channel (email / Slack / Salesforce / Jira) must surface
the dashboard URLs that let recipients act on a scan result. These tests
exercise the pure builder functions only — no external API calls — so they
can run without mocking the Resend / Slack / SF / Jira clients.

The link targets validated here come from `app.services.notification_service`:

- `/matches`                   — full match list
- `/matches?status=violation`  — filtered to violations
- `/matches/{id}`              — per-match detail

`settings.frontend_url` defaults to "http://localhost:3000" in the test
environment (set in conftest via the env-var defaults).
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.services import notification_service as ns

# Pin the dashboard origin so tests don't depend on whatever FRONTEND_URL
# the developer happens to have exported. The autouse fixture below patches
# the settings call site inside notification_service for every test in this
# module.
EXPECTED_BASE = "https://app.test.dealer-intel.local"
ORG_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def _pin_frontend_url():
    with patch.object(ns, "get_settings") as mock:
        mock.return_value.frontend_url = EXPECTED_BASE
        yield mock


def _summary(total: int = 50, matches: int = 4, compliant: int = 2,
             violations_count: int = 2, rate: float = 50.0) -> dict:
    return {
        "total_images": total,
        "matches": matches,
        "compliant": compliant,
        "violations": violations_count,
        "compliance_rate": rate,
        "pages_scanned": 5,
    }


# Sentinel — distinct from None so tests can request an explicitly missing
# match_id without the helper synthesising one.
_DEFAULT = object()


def _violation(match_id=_DEFAULT,
               asset: str = "Spring Promo",
               distributor: str = "Acme Dealer",
               channel: str = "website",
               confidence: int = 87,
               summary: str = "Logo color drifted") -> dict:
    if match_id is _DEFAULT:
        match_id = str(uuid4())
    return {
        "match_id": match_id,
        "asset_name": asset,
        "distributor_name": distributor,
        "channel": channel,
        "confidence_score": confidence,
        "compliance_summary": summary,
    }


# ─── Link helpers ───────────────────────────────────────────────


class TestLinkHelpers:
    def test_dashboard_link_no_path(self):
        assert ns._dashboard_link() == EXPECTED_BASE

    def test_dashboard_link_normalises_leading_slash(self):
        assert ns._dashboard_link("matches") == f"{EXPECTED_BASE}/matches"
        assert ns._dashboard_link("/matches") == f"{EXPECTED_BASE}/matches"

    def test_dashboard_link_strips_trailing_base_slash(self):
        with patch.object(ns, "get_settings") as mock:
            mock.return_value.frontend_url = "https://app.example.com/"
            assert ns._dashboard_link("/x") == "https://app.example.com/x"

    def test_match_detail_url_returns_none_for_missing_id(self):
        assert ns._match_detail_url(None) is None
        assert ns._match_detail_url("") is None

    def test_match_detail_url_for_uuid(self):
        mid = "abc-123"
        assert ns._match_detail_url(mid) == f"{EXPECTED_BASE}/matches/{mid}"

    def test_violations_url_carries_status_filter(self):
        assert ns._violations_url() == f"{EXPECTED_BASE}/matches?status=violation"


# ─── Email ──────────────────────────────────────────────────────


class TestEmailDeepLinks:
    def test_violation_cta_links_to_filtered_matches(self):
        v = _violation()
        _, html = ns._build_scan_report_email(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=1),
            violations=[v],
        )
        assert f'href="{EXPECTED_BASE}/matches?status=violation"' in html
        assert "Review 1 Violation" in html
        # Secondary "View all matches" link is always present.
        assert f'href="{EXPECTED_BASE}/matches"' in html

    def test_violation_row_carries_per_match_review_link(self):
        mid = str(uuid4())
        _, html = ns._build_scan_report_email(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=1),
            violations=[_violation(match_id=mid)],
        )
        assert f'href="{EXPECTED_BASE}/matches/{mid}"' in html
        assert ">Review</a>" in html

    def test_violation_row_without_match_id_renders_dash(self):
        _, html = ns._build_scan_report_email(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=1),
            violations=[_violation(match_id="")],
        )
        # No /matches/ broken link, falls back to a dash placeholder.
        assert f'href="{EXPECTED_BASE}/matches/"' not in html
        assert "—" in html

    def test_no_violations_cta_opens_dashboard(self):
        _, html = ns._build_scan_report_email(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=0),
            violations=[],
        )
        assert "Open Dashboard" in html
        assert f'href="{EXPECTED_BASE}/matches"' in html
        # No filtered URL when there's nothing to triage.
        assert "?status=violation" not in html

    def test_truncation_links_to_full_violations_list(self):
        violations = [_violation() for _ in range(25)]
        _, html = ns._build_scan_report_email(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=25),
            violations=violations,
        )
        assert "Showing 20 of 25 violations" in html
        # Truncation message includes the filtered URL.
        truncation_idx = html.index("Showing 20 of 25")
        assert "/matches?status=violation" in html[truncation_idx:]

    def test_custom_frontend_url_is_honoured(self):
        with patch.object(ns, "get_settings") as mock:
            mock.return_value.frontend_url = "https://app.example.com"
            _, html = ns._build_scan_report_email(
                org_name="Acme",
                scan_source="website",
                summary=_summary(violations_count=1),
                violations=[_violation()],
            )
        assert "https://app.example.com/matches?status=violation" in html
        assert EXPECTED_BASE not in html


# ─── Slack ──────────────────────────────────────────────────────


def _find_actions_block(blocks: list) -> dict:
    for b in blocks:
        if b.get("type") == "actions":
            return b
    raise AssertionError("No actions block found in Slack message")


class TestSlackDeepLinks:
    def test_violation_actions_block_links_correctly(self):
        blocks = ns._build_scan_slack_blocks(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=2),
            violations=[_violation(), _violation()],
        )
        actions = _find_actions_block(blocks)
        urls = [el["url"] for el in actions["elements"]]
        assert f"{EXPECTED_BASE}/matches?status=violation" in urls
        assert f"{EXPECTED_BASE}/matches" in urls
        # Primary CTA labelled with the count.
        primary = next(el for el in actions["elements"] if el.get("style") == "primary")
        assert "2 Violations" in primary["text"]["text"]

    def test_each_violation_section_carries_review_button(self):
        mid_a, mid_b = str(uuid4()), str(uuid4())
        blocks = ns._build_scan_slack_blocks(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=2),
            violations=[_violation(match_id=mid_a), _violation(match_id=mid_b)],
        )
        accessory_urls = [
            b["accessory"]["url"]
            for b in blocks
            if b.get("type") == "section" and "accessory" in b
        ]
        assert f"{EXPECTED_BASE}/matches/{mid_a}" in accessory_urls
        assert f"{EXPECTED_BASE}/matches/{mid_b}" in accessory_urls

    def test_violation_without_match_id_omits_accessory(self):
        blocks = ns._build_scan_slack_blocks(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=1),
            violations=[_violation(match_id="")],
        )
        violation_sections = [
            b for b in blocks
            if b.get("type") == "section"
            and "•" in (b.get("text", {}).get("text", ""))
        ]
        assert violation_sections, "Expected at least one per-violation section"
        for s in violation_sections:
            assert "accessory" not in s

    def test_no_violations_actions_block_opens_dashboard(self):
        blocks = ns._build_scan_slack_blocks(
            org_name="Acme",
            scan_source="website",
            summary=_summary(violations_count=0),
            violations=[],
        )
        actions = _find_actions_block(blocks)
        primary = next(el for el in actions["elements"] if el.get("style") == "primary")
        assert primary["text"]["text"] == "Open Dashboard"
        assert primary["url"] == f"{EXPECTED_BASE}/matches"


# ─── Salesforce ─────────────────────────────────────────────────


class TestSalesforceDeepLinks:
    def test_description_includes_dashboard_links(self):
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return True

        with patch.object(ns, "_get_salesforce_integration",
                          return_value={"access_token": "x", "instance_url": "https://sf.example.com"}), \
             patch.object(ns, "_get_org_name", return_value="Acme"), \
             patch.object(ns, "_create_sf_task", side_effect=fake_create):
            ns.notify_salesforce_scan_complete(
                organization_id=ORG_ID,
                scan_source="website",
                summary=_summary(violations_count=2),
                violations=[_violation(match_id="m-1"), _violation(match_id="m-2")],
            )

        desc = captured["description"]
        assert f"Review violations: {EXPECTED_BASE}/matches?status=violation" in desc
        assert f"Open dashboard: {EXPECTED_BASE}/matches" in desc
        assert f"{EXPECTED_BASE}/matches/m-1" in desc
        assert f"{EXPECTED_BASE}/matches/m-2" in desc

    def test_no_violation_url_when_zero_violations(self):
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return True

        with patch.object(ns, "_get_salesforce_integration",
                          return_value={"access_token": "x", "instance_url": "https://sf.example.com"}), \
             patch.object(ns, "_get_org_name", return_value="Acme"), \
             patch.object(ns, "_create_sf_task", side_effect=fake_create):
            ns.notify_salesforce_scan_complete(
                organization_id=ORG_ID,
                scan_source="website",
                summary=_summary(violations_count=0),
                violations=[],
            )

        desc = captured["description"]
        assert "Review violations:" not in desc
        assert f"Open dashboard: {EXPECTED_BASE}/matches" in desc


# ─── Jira ───────────────────────────────────────────────────────


def _flatten_adf_text(doc: dict) -> str:
    """Concatenate every text node in an ADF doc for substring checks."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                out.append(node.get("text", ""))
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return "\n".join(out)


def _collect_link_marks(doc: dict) -> list[tuple[str, str]]:
    """Return (text, href) pairs for every text node carrying a link mark."""
    pairs: list[tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                for mark in node.get("marks", []) or []:
                    if mark.get("type") == "link":
                        pairs.append((node.get("text", ""), mark.get("attrs", {}).get("href", "")))
            for child in node.get("content", []) or []:
                walk(child)

    walk(doc)
    return pairs


class TestJiraDeepLinks:
    def test_adf_text_helper_with_and_without_link(self):
        plain = ns._adf_text("hi")
        assert plain == {"type": "text", "text": "hi"}
        linked = ns._adf_text("Review", href="https://x")
        assert linked == {
            "type": "text",
            "text": "Review",
            "marks": [{"type": "link", "attrs": {"href": "https://x"}}],
        }

    def test_doc_from_text_preserves_blank_lines(self):
        doc = ns._adf_doc_from_text("first\n\nthird")
        assert doc["type"] == "doc"
        assert len(doc["content"]) == 3
        assert doc["content"][1]["content"] == []  # blank paragraph

    def test_scan_complete_doc_has_dashboard_link_marks(self):
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return True

        with patch.object(ns, "_get_jira_integration",
                          return_value={"access_token": "x", "cloud_id": "c", "project_key": "OPS"}), \
             patch.object(ns, "_create_jira_issue", side_effect=fake_create):
            ns.notify_jira_scan_complete(
                organization_id=ORG_ID,
                scan_source="website",
                summary=_summary(violations_count=2),
                violations=[_violation(match_id="m-1"), _violation(match_id="m-2")],
            )

        doc = captured["description_doc"]
        assert doc["type"] == "doc"
        links = dict(_collect_link_marks(doc))
        assert links.get(f"{EXPECTED_BASE}/matches?status=violation") == \
            f"{EXPECTED_BASE}/matches?status=violation"
        assert links.get(f"{EXPECTED_BASE}/matches") == f"{EXPECTED_BASE}/matches"
        # Per-match "Review" links.
        assert ("Review", f"{EXPECTED_BASE}/matches/m-1") in _collect_link_marks(doc)
        assert ("Review", f"{EXPECTED_BASE}/matches/m-2") in _collect_link_marks(doc)
        # Plain text content survives alongside the marks.
        flat = _flatten_adf_text(doc)
        assert "Spring Promo" in flat
        assert "Acme Dealer" in flat

    def test_violation_without_match_id_omits_review_link(self):
        captured: dict = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return True

        with patch.object(ns, "_get_jira_integration",
                          return_value={"access_token": "x", "cloud_id": "c", "project_key": "OPS"}), \
             patch.object(ns, "_create_jira_issue", side_effect=fake_create):
            ns.notify_jira_scan_complete(
                organization_id=ORG_ID,
                scan_source="website",
                summary=_summary(violations_count=1),
                violations=[_violation(match_id="")],
            )

        doc = captured["description_doc"]
        review_links = [pair for pair in _collect_link_marks(doc) if pair[0] == "Review"]
        assert review_links == []  # no per-match link when match_id is missing

    def test_no_violations_short_circuits(self):
        # Existing behaviour preserved: Jira issues are only created when
        # there is at least one violation. Verify the deep-link refactor
        # didn't change that.
        with patch.object(ns, "_get_jira_integration",
                          return_value={"access_token": "x", "cloud_id": "c", "project_key": "OPS"}), \
             patch.object(ns, "_create_jira_issue") as create:
            result = ns.notify_jira_scan_complete(
                organization_id=ORG_ID,
                scan_source="website",
                summary=_summary(violations_count=0),
                violations=[],
            )
        assert result is False
        create.assert_not_called()
