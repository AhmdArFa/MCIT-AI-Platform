"""Studio must use Tut's user-scoped agent runtime, never a renamed local model."""

from unittest.mock import AsyncMock

import httpx
import pytest

from open_notebook.tut import client


@pytest.mark.asyncio
async def test_studio_requires_user_connection(monkeypatch):
    monkeypatch.setattr(client, "repo_query", AsyncMock(return_value=[]))
    with pytest.raises(ValueError, match="Connect your Tut Agent"):
        await client.draft("make a report")


@pytest.mark.asyncio
async def test_studio_invokes_actual_agent_and_records_usage(monkeypatch):
    queries = []

    async def query(sql, params=None):
        queries.append((sql, params))
        return [{"key": "encrypted-personal-key"}] if sql.startswith("SELECT") else []

    monkeypatch.setattr(client, "repo_query", query)
    monkeypatch.setattr(client, "decrypt_value", lambda _: "personal-tut-key")
    monkeypatch.setenv("TUT_AGENT_INTERNAL_URL", "http://tut-agent:3210")

    def respond(request):
        assert request.url.path == "/api/v1/responses"
        assert request.headers["Authorization"] == "Bearer personal-tut-key"
        assert request.read().decode().find('"model":"inbox"') >= 0
        return httpx.Response(200, json={
            "status": "completed",
            "model": "inbox",
            "output_text": '{"title":"Quarterly review"}',
            "usage": {"input_tokens": 75, "output_tokens": 28},
        })

    transport = httpx.MockTransport(respond)
    original = client.httpx.AsyncClient
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    result = await client.TutModel().ainvoke("make a report")
    assert result.content == '{"title":"Quarterly review"}'
    assert any("CREATE usage_event" in q for q, _ in queries)


@pytest.mark.asyncio
async def test_studio_rejects_expired_personal_key(monkeypatch):
    monkeypatch.setattr(client, "repo_query", AsyncMock(return_value=[{"key": "ciphertext"}]))
    monkeypatch.setattr(client, "decrypt_value", lambda _: "bad-tut-key")
    monkeypatch.setenv("TUT_AGENT_INTERNAL_URL", "http://tut-agent:3210")
    transport = httpx.MockTransport(lambda _: httpx.Response(401))
    original = client.httpx.AsyncClient
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(ValueError, match="expired or lacks permission"):
        await client.draft("make a report")
