from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeliveryMode(StrEnum):
    SUCCESS = "success"
    REJECT = "reject"
    BEFORE_SEND_FAILURE = "before_send_failure"
    AMBIGUOUS_TIMEOUT = "ambiguous_timeout"


class Enquiry(BaseModel):
    """Deliberately synthetic identifiers, not a production personal-data schema."""

    model_config = ConfigDict(extra="forbid")
    enquiry_id: str = Field(pattern=r"^demo-[a-z0-9-]{1,40}$")
    service: str = Field(pattern=r"^(website|integration|automation)$")
    team_size: int = Field(ge=1, le=10000, strict=True)
    delivery_mode: DeliveryMode = DeliveryMode.SUCCESS


class Receipt(BaseModel):
    enquiry_id: str
    state: str
    duplicate: bool
    attempts: int
    next_action: str
