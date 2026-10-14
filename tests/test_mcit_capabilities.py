"""Ollama context capacity must not be mistaken for its active context window."""

from types import SimpleNamespace

import pytest

from open_notebook.ai import capabilities


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded,expected", [(True, 8192), (False, None)])
async def test_ollama_uses_active_context_when_loaded(monkeypatch, loaded, expected):
    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def post(self, *_args, **_kwargs):
            return Response(
                {
                    "model_info": {"qwen2.context_length": 32768},
                    "capabilities": ["completion", "tools"],
                }
            )

        async def get(self, *_args, **_kwargs):
            return Response(
                {"models": [{"name": "qwen2.5:7b", "context_length": 8192}]}
                if loaded
                else {"models": []}
            )

    monkeypatch.setattr(capabilities.httpx, "AsyncClient", Client)
    result = await capabilities._ollama(
        SimpleNamespace(type="language", name="qwen2.5:7b")
    )
    assert result["context_window"] == expected
    assert result["max_context_window"] == 32768
