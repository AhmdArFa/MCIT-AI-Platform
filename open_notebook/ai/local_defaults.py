"""MCIT AI: zero-cloud default model bootstrap.

On API startup, register the local Ollama models (via the existing ``ollama``
provider, configured through ``OLLAMA_API_BASE``) and assign them as defaults
for any slot that is still empty. Existing user choices are never overwritten.
"""

import os
from typing import Optional

from loguru import logger

from open_notebook.ai.models import DefaultModels, Model
from open_notebook.database.repository import ensure_record_id, repo_query

# OpenAI voice names used by the seeded podcast speaker profiles -> Kokoro voices
KOKORO_VOICE_MAP = {
    "alloy": "af_alloy",
    "echo": "am_echo",
    "fable": "bm_fable",
    "onyx": "am_onyx",
    "nova": "af_nova",
    "shimmer": "af_bella",
    "ash": "am_michael",
    "coral": "af_heart",
    "sage": "af_sky",
    "ballad": "bm_george",
    "verse": "am_liam",
}


async def _ensure_model(name: str, model_type: str, provider: str = "ollama") -> str:
    rows = await repo_query(
        "SELECT * FROM model WHERE provider=$provider AND name=$name AND type=$type;",
        {"name": name, "type": model_type, "provider": provider},
    )
    if rows:
        return str(rows[0]["id"])
    model = Model(name=name, provider=provider, type=model_type)
    await model.save()
    logger.info(f"Registered local {provider} {model_type} model '{name}'")
    return str(model.id)


async def _fill_podcast_profiles(llm_id: str, tts_id: Optional[str]) -> None:
    """Point seeded podcast profiles at the local models, only where unset."""
    for ep in await repo_query("SELECT * FROM episode_profile;"):
        patch = {}
        for field in ("outline_llm", "transcript_llm"):
            if not ep.get(field):
                patch[field] = ensure_record_id(llm_id)
        if patch:
            await repo_query(
                "UPDATE $id MERGE $data;",
                {"id": ensure_record_id(ep["id"]), "data": patch},
            )
    if not tts_id:
        return
    for sp in await repo_query("SELECT * FROM speaker_profile;"):
        if sp.get("voice_model") and str(sp["voice_model"]) != tts_id:
            continue
        speakers = []
        for spk in sp.get("speakers") or []:
            spk = dict(spk)
            spk["voice_id"] = KOKORO_VOICE_MAP.get(
                spk.get("voice_id", ""), spk.get("voice_id")
            )
            speakers.append(spk)
        await repo_query(
            "UPDATE $id MERGE $data;",
            {
                "id": ensure_record_id(sp["id"]),
                "data": {"voice_model": ensure_record_id(tts_id), "speakers": speakers},
            },
        )


async def bootstrap_local_models() -> None:
    if os.environ.get("MCIT_LOCAL_LLM_BOOTSTRAP", "true").lower() in (
        "0",
        "false",
        "no",
    ):
        return
    llm = os.environ.get("OLLAMA_CHAT_MODEL", "qwen2.5:7b").strip()
    embed = os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text").strip()

    llm_id = await _ensure_model(llm, "language")
    embed_id = await _ensure_model(embed, "embedding") if embed else None

    # Self-hosted TTS (Kokoro, OpenAI-compatible) keeps podcasts fully local
    tts_id = None
    if os.environ.get("OPENAI_COMPATIBLE_BASE_URL_TTS") or os.environ.get(
        "OPENAI_COMPATIBLE_BASE_URL"
    ):
        tts_name = os.environ.get("LOCAL_TTS_MODEL", "kokoro").strip()
        tts_id = await _ensure_model(tts_name, "text_to_speech", "openai_compatible")

    defaults = await DefaultModels.get_instance()
    wanted = {
        "default_chat_model": llm_id,
        "default_transformation_model": llm_id,
        "large_context_model": llm_id,
        "default_tools_model": llm_id,
        "default_embedding_model": embed_id,
        "default_text_to_speech_model": tts_id,
    }
    patch = {k: v for k, v in wanted.items() if v and not getattr(defaults, k, None)}
    if patch:
        await repo_query(
            "UPSERT $record_id MERGE $data;",
            {"record_id": ensure_record_id(DefaultModels.record_id), "data": patch},
        )
        logger.info(f"Assigned local default models: {sorted(patch)}")

    await _fill_podcast_profiles(llm_id, tts_id)
    await sync_unsynced_credentials()


async def sync_credential_models(provider: str) -> int:
    """Discover and register a provider's models; returns how many are registered."""
    from open_notebook.ai.key_provider import provision_provider_keys
    from open_notebook.ai.model_discovery import sync_provider_models

    try:
        await provision_provider_keys(provider)
        discovered, new, existing = await sync_provider_models(
            provider, auto_register=True
        )
        if new:
            logger.info(f"Registered {new} {provider} models")
        return new + existing
    except Exception as e:  # never block credential saving on discovery
        logger.warning(f"Model sync for {provider} failed: {type(e).__name__}")
        return 0


async def sync_unsynced_credentials() -> None:
    """Startup repair: providers that have a credential but no registered models."""
    rows = await repo_query("SELECT provider FROM credential GROUP BY provider;")
    for row in rows or []:
        provider = row.get("provider")
        if not provider:
            continue
        count = await repo_query(
            "SELECT count() AS n FROM model WHERE provider=$p GROUP ALL;",
            {"p": provider},
        )
        if not count or not count[0].get("n"):
            await sync_credential_models(provider)
