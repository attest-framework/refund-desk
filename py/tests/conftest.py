"""Fixtures for the Refund Desk tests: the payments world and the incident request.

The scripted model server must already run (`make check` starts it through
scripts/stack.py); each test hosts its own payments world from world/.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from attest.world import WorldSession

WORLDS = Path(__file__).resolve().parents[2] / "world"


@pytest.fixture
def payments_world(attest_world: Callable[..., WorldSession]) -> Callable[[str], WorldSession]:
    """Host a fresh payments world for the test: `payments_world("payments")` is healthy and
    `payments_world("payments-inc-1042")` arms the INC-1042 fault. It sets PAYMENTS_BASE_URL until
    the test ends, so read `Settings.from_env()` after the call."""

    def start(name: str) -> WorldSession:
        return attest_world(WORLDS / f"{name}.world.yaml")

    return start


@pytest.fixture(scope="session")
def incident_request() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "incidents" / "INC-1042" / "request.json"
    request: dict[str, str] = json.loads(path.read_text())
    return request
