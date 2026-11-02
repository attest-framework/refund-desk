"""Fixtures for the Refund Desk tests: settings and the fake payments API.

The scripted model server and the payments API must already run; `make check`
starts them through scripts/stack.py.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from refund_desk.agent import Settings


def admin(url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture
def payments(settings: Settings) -> Callable[[str | None], None]:
    """Reset the payments ledger, optionally arming a fault script."""

    def reset(fault_script: str | None) -> None:
        admin(f"{settings.payments_base_url}/_admin/reset", {"fault_script": fault_script})

    return reset


@pytest.fixture(scope="session")
def incident_request() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "incidents" / "INC-1042" / "request.json"
    request: dict[str, str] = json.loads(path.read_text())
    return request
