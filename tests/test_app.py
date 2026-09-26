"""The backend app: health check and the websocket stub."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.schema import InitMessage, TickMessage, server_message


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ws_sends_init_then_tick(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        first = server_message.validate_json(ws.receive_text())
        second = server_message.validate_json(ws.receive_text())
    assert isinstance(first, InitMessage)
    assert isinstance(second, TickMessage)
    assert [h.id for h in second.homes] == [h.id for h in first.homes]
