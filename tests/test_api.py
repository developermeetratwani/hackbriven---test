from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.core.credits import InsufficientCreditsError


def _client() -> TestClient:
    return TestClient(create_app())


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("backend.api.routes.credits.charge", return_value=4)
@patch("backend.api.routes.run_pipeline")
def test_create_job_returns_queued_job(mock_run_pipeline, mock_charge) -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "Why EVs are popular"})

    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "Why EVs are popular"
    assert body["status"] == "queued"
    assert body["motion_tier"] == "balanced"
    assert body["id"]
    mock_charge.assert_called_once()


def test_create_job_rejects_empty_topic() -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "   "})
    assert response.status_code == 422


@patch("backend.api.routes.credits.charge", side_effect=InsufficientCreditsError(required=4, available=0))
def test_create_job_returns_402_when_credits_insufficient(mock_charge) -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "topic"})

    assert response.status_code == 402
    body = response.json()["detail"]
    assert body["required"] == 4
    assert body["available"] == 0
    assert body["top_up"] == "/credits/create-order"


@patch("backend.api.routes.credits.charge", return_value=1)
@patch("backend.api.routes.run_pipeline")
def test_create_job_accepts_motion_tier(mock_run_pipeline, mock_charge) -> None:
    client = _client()
    response = client.post("/jobs", json={"topic": "topic", "motion_tier": "basic"})

    assert response.status_code == 200
    assert response.json()["motion_tier"] == "basic"


@patch("backend.api.routes.credits.charge", return_value=4)
@patch("backend.api.routes.run_pipeline")
def test_get_job_roundtrip(mock_run_pipeline, mock_charge) -> None:
    client = _client()
    created = client.post("/jobs", json={"topic": "topic"}).json()

    fetched = client.get(f"/jobs/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_get_missing_job_returns_404() -> None:
    client = _client()
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


@patch("backend.api.routes.credits.charge", return_value=4)
def test_get_result_before_completion_returns_409(mock_charge) -> None:
    with patch("backend.api.routes.run_pipeline"):
        client = _client()
        created = client.post("/jobs", json={"topic": "topic"}).json()

    response = client.get(f"/jobs/{created['id']}/result")
    assert response.status_code == 409


@patch("backend.api.routes.credits.get_balance", return_value=42)
def test_get_credits_balance(mock_get_balance) -> None:
    client = _client()
    response = client.get("/credits")

    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == 42
    assert set(body["cost_by_tier"].keys()) == {"max", "balanced", "basic"}


@patch("backend.api.routes.payments.create_order")
def test_create_order_returns_checkout_details(mock_create_order) -> None:
    mock_create_order.return_value = {
        "order_id": "order_123",
        "amount": 9900,
        "currency": "INR",
        "key_id": "rzp_test_fake",
        "credits": 50,
    }
    client = _client()
    response = client.post("/credits/create-order")

    assert response.status_code == 200
    assert response.json()["order_id"] == "order_123"


@patch("backend.api.routes.payments.create_order")
def test_create_order_returns_503_when_razorpay_not_configured(mock_create_order) -> None:
    from backend.services.payments import PaymentError

    mock_create_order.side_effect = PaymentError("RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not configured")
    client = _client()
    response = client.post("/credits/create-order")

    assert response.status_code == 503


@patch("backend.api.routes.credits.add_credits", return_value=50)
@patch("backend.api.routes.payments.verify_payment_signature")
def test_verify_payment_credits_account_on_success(mock_verify, mock_add_credits) -> None:
    client = _client()
    response = client.post(
        "/credits/verify-payment",
        json={
            "razorpay_order_id": "order_123",
            "razorpay_payment_id": "pay_456",
            "razorpay_signature": "deadbeef",
        },
    )

    assert response.status_code == 200
    assert response.json()["balance"] == 50
    mock_verify.assert_called_once_with(order_id="order_123", payment_id="pay_456", signature="deadbeef")


@patch("backend.api.routes.payments.verify_payment_signature")
def test_verify_payment_rejects_bad_signature(mock_verify) -> None:
    from backend.services.payments import SignatureVerificationError

    mock_verify.side_effect = SignatureVerificationError("payment signature did not match")
    client = _client()
    response = client.post(
        "/credits/verify-payment",
        json={
            "razorpay_order_id": "order_123",
            "razorpay_payment_id": "pay_456",
            "razorpay_signature": "wrong",
        },
    )

    assert response.status_code == 400
