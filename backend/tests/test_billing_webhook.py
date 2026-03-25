"""Tests for Stripe webhook event handling."""
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import ORG_A_ID

WEBHOOK_URL = "/api/v1/billing/webhook"
FAKE_ORG_ID = str(ORG_A_ID)
FAKE_CUSTOMER_ID = "cus_test_123"
FAKE_SUB_ID = "sub_test_456"


def _webhook_event(event_type: str, data_object: dict) -> dict:
    return {
        "id": "evt_test",
        "type": event_type,
        "data": {"object": data_object},
    }


# ------------------------------------------------------------------
# Invalid signature
# ------------------------------------------------------------------

class TestInvalidSignature:
    def test_bad_signature_returns_400(self, client, mock_supabase):
        with patch("stripe.Webhook.construct_event") as mock_construct:
            import stripe
            mock_construct.side_effect = stripe.error.SignatureVerificationError(
                "bad sig", "sig_header"
            )
            resp = client.post(
                WEBHOOK_URL,
                content=b'{}',
                headers={"stripe-signature": "bad"},
            )
            assert resp.status_code == 400
            assert "Invalid signature" in resp.json()["detail"]


# ------------------------------------------------------------------
# checkout.session.completed
# ------------------------------------------------------------------

class TestCheckoutCompleted:
    def test_activates_org_plan(self, client, mock_supabase):
        event = _webhook_event("checkout.session.completed", {
            "metadata": {"org_id": FAKE_ORG_ID, "plan": "professional"},
            "subscription": FAKE_SUB_ID,
            "customer": FAKE_CUSTOMER_ID,
        })

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200

        update_call = mock_supabase.table.return_value.update
        update_call.assert_called()
        update_args = update_call.call_args[0][0]
        assert update_args["plan"] == "professional"
        assert update_args["plan_status"] == "active"
        assert update_args["stripe_subscription_id"] == FAKE_SUB_ID

    def test_missing_org_id_is_graceful(self, client, mock_supabase):
        event = _webhook_event("checkout.session.completed", {
            "metadata": {},
            "subscription": FAKE_SUB_ID,
            "customer": FAKE_CUSTOMER_ID,
        })

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_not_called()


# ------------------------------------------------------------------
# invoice.payment_failed
# ------------------------------------------------------------------

class TestPaymentFailed:
    def test_marks_org_past_due(self, client, mock_supabase):
        org_result = MagicMock()
        org_result.data = {"id": FAKE_ORG_ID}

        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.maybe_single.return_value.execute.return_value = org_result

        event = _webhook_event("invoice.payment_failed", {
            "customer": FAKE_CUSTOMER_ID,
        })

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200
        update_call = mock_supabase.table.return_value.update
        update_call.assert_called()
        assert update_call.call_args[0][0]["plan_status"] == "past_due"

    def test_unknown_customer_is_graceful(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(data=None)

        event = _webhook_event("invoice.payment_failed", {
            "customer": "cus_unknown",
        })

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_not_called()


# ------------------------------------------------------------------
# customer.subscription.deleted
# ------------------------------------------------------------------

class TestSubscriptionDeleted:
    def test_downgrades_to_free(self, client, mock_supabase):
        org_result = MagicMock()
        org_result.data = {"id": FAKE_ORG_ID}

        mock_supabase.table.return_value.select.return_value \
            .eq.return_value.maybe_single.return_value.execute.return_value = org_result

        event = _webhook_event("customer.subscription.deleted", {
            "customer": FAKE_CUSTOMER_ID,
            "id": FAKE_SUB_ID,
        })

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200
        update_call = mock_supabase.table.return_value.update
        update_call.assert_called()
        update_args = update_call.call_args[0][0]
        assert update_args["plan"] == "free"
        assert update_args["plan_status"] == "canceled"
        assert update_args["stripe_subscription_id"] is None
        assert update_args["extra_dealers_count"] == 0


# ------------------------------------------------------------------
# Unhandled event type — should still return 200
# ------------------------------------------------------------------

class TestUnhandledEvent:
    def test_unknown_event_returns_200(self, client, mock_supabase):
        event = _webhook_event("some.unknown.event", {"foo": "bar"})

        with patch("stripe.Webhook.construct_event", return_value=event):
            resp = client.post(
                WEBHOOK_URL,
                content=json.dumps(event).encode(),
                headers={"stripe-signature": "valid"},
            )

        assert resp.status_code == 200
        assert resp.json()["received"] is True
