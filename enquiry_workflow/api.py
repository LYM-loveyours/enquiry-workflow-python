"""Local, synthetic-data API. Not safe to expose as an authenticated production service."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .models import Enquiry, Receipt
from .service import Service
from .store import ConflictError, Store


def create_app(path: Path = Path("runtime/enquiries.sqlite3")) -> FastAPI:
    app = FastAPI(title="LYM enquiry workflow — synthetic demonstration", version="1.0.0")
    store = Store(path)
    store.quarantine_stale()
    service = Service(store)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default validation response includes the rejected input. Redact it.
        issues: list[dict[str, Any]] = [
            {"loc": error["loc"], "type": error["type"]} for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": issues})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic-only", "delivery": "mock"}

    @app.post("/enquiries", response_model=Receipt)
    def accept(enquiry: Enquiry) -> Receipt:
        try:
            return service.accept(enquiry)
        except ConflictError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/enquiries/{identifier}", response_model=Receipt)
    def status(identifier: str) -> Receipt:
        try:
            return service.receipt(identifier)
        except KeyError as error:
            raise HTTPException(404, "Unknown enquiry") from error

    @app.post("/enquiries/{identifier}/retry", response_model=Receipt)
    def retry(identifier: str) -> Receipt:
        try:
            return service.retry(identifier)
        except KeyError as error:
            raise HTTPException(404, "Unknown enquiry") from error

    return app
