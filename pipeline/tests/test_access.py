import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline import access
from pipeline.config import settings


@pytest.mark.asyncio
async def test_resolve_user_ids_maps_defunct_alias_to_active_account(monkeypatch):
    """A defunct address (pepe@) that has no account of its own resolves to the uid
    of the active account for the same person (jma@), so the person's old
    correspondence is granted to their current user."""
    monkeypatch.setattr(
        settings, "user_email_aliases", "pepe@kiboventures.com:jma@kiboventures.com"
    )
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"users": [
        {"email": "jma@kiboventures.com", "id": "uid-jma"},
        {"email": "other@kiboventures.com", "id": "uid-other"},
    ]})
    http = MagicMock()
    http.get = AsyncMock(return_value=resp)

    mapping = await access.resolve_user_ids(http)

    assert mapping["jma@kiboventures.com"] == "uid-jma"
    assert mapping["pepe@kiboventures.com"] == "uid-jma"   # alias → active account
    # alias only applies when the target account exists
    assert "ghost@kiboventures.com" not in mapping


@pytest.mark.asyncio
async def test_resolve_user_ids_alias_skipped_when_target_missing(monkeypatch):
    monkeypatch.setattr(settings, "user_email_aliases", "pepe@kiboventures.com:jma@kiboventures.com")
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"users": [{"email": "other@kiboventures.com", "id": "uid-other"}]})
    http = MagicMock()
    http.get = AsyncMock(return_value=resp)

    mapping = await access.resolve_user_ids(http)

    assert "pepe@kiboventures.com" not in mapping  # jma@ has no account → no alias
