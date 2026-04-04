"""E2E test fixtures — httpx client pointed at the local test stack."""

from collections.abc import Iterator

import httpx
import pytest

BASE_URL = "http://localhost:15010"
API_TOKEN = "test-token"


@pytest.fixture(scope="session", autouse=True)
def _preflight_check() -> None:
    """Fail fast if webhook-relay is unreachable or disconnected from IB Gateway."""
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5.0)
    except httpx.HTTPError:
        pytest.exit(
            "webhook-relay is not reachable at "
            f"{BASE_URL}. Is the E2E stack running? (make e2e-up)",
            returncode=1,
        )
    if resp.status_code != 200 or not resp.json().get("connected"):
        pytest.exit(
            "webhook-relay is up but NOT connected to IB Gateway. "
            "This usually means another IBKR session (e.g. local-dev stack) "
            "was running when the test gateway started and IBKR rejected it. "
            "Fix: make e2e-down && make local-down && make e2e-up",
            returncode=1,
        )


@pytest.fixture(scope="session")
def api() -> Iterator[httpx.Client]:
    """Shared httpx client with auth header, scoped to the entire test session."""
    with httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
        timeout=15.0,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def anon_api() -> Iterator[httpx.Client]:
    """Httpx client without auth — for testing 401 responses."""
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        yield client
