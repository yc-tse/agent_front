"""Shared fixtures.

Mission ids live in `sample_missions.py`, not here, so test modules can import
them without importing conftest.
"""

from __future__ import annotations

import pytest

from audit_front.example_backend import ExampleDataAPI, reload_example_data


@pytest.fixture(autouse=True)
def _fresh_example_index():
    """Re-scan the example directory around every test.

    Tests that point `EXAMPLE_DIR` somewhere else must not leave a cached index
    behind for the next test to trip over.
    """
    reload_example_data()
    yield
    reload_example_data()


@pytest.fixture
def client() -> ExampleDataAPI:
    """The example backend, without the simulated latency."""
    return ExampleDataAPI(latency=False)
