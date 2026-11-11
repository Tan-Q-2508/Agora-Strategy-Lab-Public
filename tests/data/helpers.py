from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient


def wait_job(client: TestClient, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    """Poll a job until it finishes (jobs run on real background threads)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job: dict[str, Any] = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish")
