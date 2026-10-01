# QA evidence · 1 October 2026

17 pytest tests passed. Ruff passed. Strict mypy passed on the application package. A dependency audit reported no known vulnerabilities at the check. A Starlette warning recommends a future migration of its test client from httpx to httpx2; the current pinned environment passes.

Coverage includes duplicate/conflicting payloads, durable state across restart, 20 concurrent requests, bounded pre-transmission retries, permanent rejection, ambiguous delivery quarantine, crash recovery, exception/validation redaction and API responses. Tests use a mock adapter and SQLite; they do not establish real-world delivery reliability.

Not tested: physical devices, assistive-technology user testing, production hosting, live delivery, load/performance under real traffic or GitHub-hosted CI. Automated accessibility checks are not certification. No measured commercial results are claimed. Nothing deployed.
