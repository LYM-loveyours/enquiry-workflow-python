import logging
from collections.abc import Callable

from .models import DeliveryMode, Enquiry, Receipt
from .store import Store

logger = logging.getLogger("enquiry_workflow")


class BeforeSendFailure(Exception):
    """No bytes were transmitted: bounded retry is permitted."""


class AmbiguousDelivery(Exception):
    """Downstream may have received the request: reconcile, do not retry."""


class RejectedDelivery(Exception):
    """Permanent validation rejection."""


def mock_delivery(enquiry: Enquiry) -> None:
    """No HTTP client or real destination exists in this demonstration."""
    match enquiry.delivery_mode:
        case DeliveryMode.BEFORE_SEND_FAILURE:
            raise BeforeSendFailure
        case DeliveryMode.AMBIGUOUS_TIMEOUT:
            raise AmbiguousDelivery
        case DeliveryMode.REJECT:
            raise RejectedDelivery
        case DeliveryMode.SUCCESS:
            return


class Service:
    def __init__(self, store: Store, deliver: Callable[[Enquiry], None] = mock_delivery) -> None:
        self.store = store
        self.deliver = deliver

    def accept(self, enquiry: Enquiry) -> Receipt:
        _, duplicate = self.store.register(enquiry)
        if not duplicate:
            self.process(enquiry)
        return self.receipt(enquiry.enquiry_id, duplicate)

    def process(self, enquiry: Enquiry) -> None:
        if not self.store.claim(enquiry.enquiry_id):
            return
        try:
            self.deliver(enquiry)
            state = "delivered"
        except BeforeSendFailure:
            row = self.store.get(enquiry.enquiry_id)
            state = "exhausted" if row and row["attempts"] >= 3 else "retryable"
        except RejectedDelivery:
            state = "rejected"
        except Exception:
            # Unknown exceptions are conservative: never assume the request was not sent.
            state = "uncertain"
        self.store.finish(enquiry.enquiry_id, state)
        # Only bounded states/attempts, never payloads, identifiers or exception text.
        logger.info("delivery_state=%s", state)

    def retry(self, identifier: str) -> Receipt:
        row = self.store.get(identifier)
        if row is None:
            raise KeyError(identifier)
        if row["state"] == "retryable":
            self.process(Enquiry.model_validate_json(row["payload"]))
        return self.receipt(identifier, True)

    def receipt(self, identifier: str, duplicate: bool = False) -> Receipt:
        row = self.store.get(identifier)
        if row is None:
            raise KeyError(identifier)
        action = {
            "pending": "inspect pending job before dispatch",
            "processing": "wait; quarantine stale processing before reconciliation",
            "retryable": "explicit retry allowed; maximum three delivery attempts",
            "uncertain": "manual reconciliation required; automatic retry forbidden",
            "exhausted": "inspect transport; retry budget exhausted",
            "rejected": "correct the brief and use a new identifier",
            "delivered": "complete; subsequent submissions are deduplicated",
        }[row["state"]]
        return Receipt(
            enquiry_id=identifier,
            state=row["state"],
            duplicate=duplicate,
            attempts=row["attempts"],
            next_action=action,
        )
