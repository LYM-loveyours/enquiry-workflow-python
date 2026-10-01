from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import pytest
from fastapi.testclient import TestClient

from enquiry_workflow.api import create_app
from enquiry_workflow.models import DeliveryMode, Enquiry
from enquiry_workflow.service import Service
from enquiry_workflow.store import ConflictError, Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "test.sqlite3")


def enquiry(mode: DeliveryMode = DeliveryMode.SUCCESS) -> Enquiry:
    return Enquiry(enquiry_id="demo-alpha", service="website", team_size=8, delivery_mode=mode)


def test_duplicate_is_not_delivered_twice(store: Store) -> None:
    calls: list[str] = []
    service = Service(store, lambda value: calls.append(value.enquiry_id))
    assert service.accept(enquiry()).state == "delivered"
    assert service.accept(enquiry()).duplicate
    assert calls == ["demo-alpha"]


def test_conflicting_id_is_rejected(store: Store) -> None:
    service = Service(store)
    service.accept(enquiry())
    with pytest.raises(ConflictError):
        service.accept(enquiry().model_copy(update={"team_size": 9}))


def test_durable_deduplication_after_restart(store: Store) -> None:
    Service(store).accept(enquiry())
    receipt = Service(Store(store.path)).accept(enquiry())
    assert receipt.duplicate and receipt.attempts == 1


def test_concurrent_duplicate_has_single_delivery(store: Store) -> None:
    calls: list[str] = []
    lock = Lock()

    def deliver(value: Enquiry) -> None:
        with lock:
            calls.append(value.enquiry_id)

    service = Service(store, deliver)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: service.accept(enquiry()), range(20)))
    assert len(calls) == 1
    assert service.receipt("demo-alpha").attempts == 1


def test_presend_retry_is_bounded(store: Store) -> None:
    service = Service(store)
    assert service.accept(enquiry(DeliveryMode.BEFORE_SEND_FAILURE)).state == "retryable"
    assert service.retry("demo-alpha").attempts == 2
    assert service.retry("demo-alpha").state == "exhausted"
    assert service.retry("demo-alpha").attempts == 3


@pytest.mark.parametrize(
    "mode,state", [(DeliveryMode.AMBIGUOUS_TIMEOUT, "uncertain"), (DeliveryMode.REJECT, "rejected")]
)
def test_unsafe_retry_is_not_attempted(store: Store, mode: DeliveryMode, state: str) -> None:
    service = Service(store)
    assert service.accept(enquiry(mode)).state == state
    assert service.retry("demo-alpha").attempts == 1


def test_unknown_exception_is_uncertain_and_redacted(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    def failing(value: Enquiry) -> None:
        raise RuntimeError("private-example-value")

    service = Service(store, failing)
    with caplog.at_level("INFO", logger="enquiry_workflow"):
        assert service.accept(enquiry()).state == "uncertain"
    assert "private-example-value" not in caplog.text
    assert "demo-alpha" not in caplog.text
    assert "delivery_state=uncertain" in caplog.text


def test_crash_is_quarantined_never_resent(store: Store) -> None:
    store.register(enquiry())
    assert store.claim("demo-alpha")
    assert store.quarantine_stale(older_than_seconds=-1) == 1
    assert Service(store).retry("demo-alpha").state == "uncertain"
    assert not store.claim("demo-alpha")


def test_fresh_inflight_work_is_not_quarantined(store: Store) -> None:
    store.register(enquiry())
    store.claim("demo-alpha")
    assert store.quarantine_stale() == 0


def test_api_contract(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "api.sqlite3")) as client:
        payload = enquiry().model_dump(mode="json")
        assert client.get("/health").json()["delivery"] == "mock"
        assert client.post("/enquiries", json=payload).json()["state"] == "delivered"
        assert client.post("/enquiries", json=payload).json()["duplicate"]
        payload["team_size"] = 9
        assert client.post("/enquiries", json=payload).status_code == 409
        assert client.get("/enquiries/does-not-exist").status_code == 404
        assert client.post("/enquiries/does-not-exist/retry").status_code == 404


@pytest.mark.parametrize(
    "patch",
    [
        {"enquiry_id": "customer-actual"},
        {"team_size": 0},
        {"team_size": "8"},
        {"email": "private@example.com"},
        {"service": "unexpected"},
        {"delivery_mode": "real"},
    ],
)
def test_invalid_input_and_pii_not_echoed(tmp_path: Path, patch: dict[str, object]) -> None:
    with TestClient(create_app(tmp_path / "invalid.sqlite3")) as client:
        payload = enquiry().model_dump(mode="json") | patch
        response = client.post("/enquiries", json=payload)
        assert response.status_code == 422
        assert "private@example.com" not in response.text
        assert "input" not in response.text
