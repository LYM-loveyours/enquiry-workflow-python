"""Run against an isolated temporary database. No network is used."""

import json
import tempfile
from pathlib import Path

from enquiry_workflow.models import DeliveryMode, Enquiry
from enquiry_workflow.service import Service
from enquiry_workflow.store import Store

with tempfile.TemporaryDirectory() as directory:
    service = Service(Store(Path(directory) / "demo.sqlite3"))
    for mode in DeliveryMode:
        enquiry = Enquiry(
            enquiry_id="demo-" + mode.value.replace("_", "-"),
            service="website",
            team_size=8,
            delivery_mode=mode,
        )
        print(json.dumps(service.accept(enquiry).model_dump()))
        print(json.dumps(service.accept(enquiry).model_dump()))
