"""Integration tests for the /agent-auth/health endpoint."""

import pytest

from tests._http import get


@pytest.mark.covers_function("Serve Health Endpoint")
def test_health_endpoint_reports_ok_on_running_container(agent_auth_container):
    status, body = get(agent_auth_container.url("health"))
    assert status == 200
    assert body == {"status": "ok"}
