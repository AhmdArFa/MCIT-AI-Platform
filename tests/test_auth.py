"""Shared login, roles and per-user isolation."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.auth import ACT_AS_HEADER, SessionAuthMiddleware
from open_notebook import accounts, tenancy
from open_notebook.utils.tenant_checkpoint import _scoped

ADMIN = accounts.Account(id="mcit_user:admin1", username="admin", role="admin")
ALICE = accounts.Account(id="mcit_user:alice1", username="alice", role="user")
BOB = accounts.Account(id="mcit_user:bob1", username="bob", role="user")
PEOPLE = {a.id: a for a in (ADMIN, ALICE, BOB)}


def token(account):
    return accounts.issue_session(account)["token"]


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)

    @app.get("/api/whoami")
    async def whoami(request: Request):
        return {"tenant": tenancy.current_tenant_db(), "user": request.state.account.username}

    @app.get("/api/models")
    async def models_get():
        return {"ok": True}

    @app.post("/api/models")
    async def models_post():
        return {"ok": True}

    @app.get("/api/admin/users")
    async def admin_users():
        return {"ok": True}

    @app.get("/api/auth/status")
    async def status():
        return {"ok": True}

    @app.post("/api/mcp")
    async def mcp():
        return {"ok": True}

    @app.get("/api/credentials/status")
    async def credential_status():
        return {"ok": True}

    @app.get("/api/credentials")
    async def credentials():
        return {"ok": True}

    with patch.object(accounts, "get_account", AsyncMock(side_effect=lambda uid: PEOPLE.get(uid))):
        yield TestClient(app)


def auth(account, **extra):
    return {"Authorization": f"Bearer {token(account)}", **extra}


class TestPasswords:
    def test_hash_roundtrip(self):
        h = accounts.hash_password("1234")
        assert h.startswith("scrypt$") and "1234" not in h
        assert accounts.verify_password("1234", h)
        assert not accounts.verify_password("12345", h)

    def test_hashes_are_salted(self):
        assert accounts.hash_password("x" * 8) != accounts.hash_password("x" * 8)

    def test_short_passwords_rejected(self):
        with pytest.raises(ValueError):
            accounts.validate_password("123")


class TestSessions:
    def test_issue_and_decode(self):
        claims = accounts.decode_session(token(ALICE))
        assert claims["sub"] == ALICE.id and claims["role"] == "user"

    def test_tampered_token_rejected(self):
        assert accounts.decode_session(token(ALICE)[:-3] + "abc") is None


class TestMiddleware:
    def test_public_paths(self, client):
        assert client.get("/api/auth/status").status_code == 200

    def test_sign_in_required(self, client):
        assert client.get("/api/whoami").status_code == 401

    def test_each_user_gets_a_private_database(self, client):
        a = client.get("/api/whoami", headers=auth(ALICE)).json()
        b = client.get("/api/whoami", headers=auth(BOB)).json()
        assert a["tenant"] == tenancy.tenant_db_name(ALICE.id)
        assert b["tenant"] == tenancy.tenant_db_name(BOB.id)
        assert a["tenant"] != b["tenant"]

    def test_user_cannot_act_as_another_user(self, client):
        r = client.get("/api/whoami", headers=auth(ALICE, **{ACT_AS_HEADER: BOB.id}))
        assert r.status_code == 403

    def test_admin_can_open_a_user_workspace(self, client):
        r = client.get("/api/whoami", headers=auth(ADMIN, **{ACT_AS_HEADER: BOB.id}))
        assert r.json()["tenant"] == tenancy.tenant_db_name(BOB.id)

    def test_admin_api_is_admin_only(self, client):
        assert client.get("/api/admin/users", headers=auth(ALICE)).status_code == 403
        assert client.get("/api/admin/users", headers=auth(ADMIN)).status_code == 200

    def test_platform_config_is_read_only_for_users(self, client):
        assert client.get("/api/models", headers=auth(ALICE)).status_code == 200
        assert client.post("/api/models", headers=auth(ALICE)).status_code == 403
        assert client.post("/api/models", headers=auth(ADMIN)).status_code == 200

    def test_session_cookie_accepted(self, client):
        client.cookies.set("mcit_session", token(BOB))
        assert client.get("/api/whoami").json()["user"] == "bob"

    def test_agent_token_only_accesses_mcp(self, client):
        mcp_token = accounts.issue_session(ADMIN, scope="mcp", hours=24 * 90)["token"]
        headers = {"Authorization": f"Bearer {mcp_token}"}
        assert client.post("/api/mcp", headers=headers).status_code == 200
        assert client.get("/api/admin/users", headers=headers).status_code == 403
        assert client.get("/api/whoami", headers=headers).status_code == 403

    def test_member_sees_only_credential_status(self, client):
        assert client.get("/api/credentials/status", headers=auth(ALICE)).status_code == 200
        assert client.get("/api/credentials", headers=auth(ALICE)).status_code == 403


class TestRouting:
    @pytest.mark.parametrize(
        "query,shared",
        [
            ("SELECT * FROM model WHERE type = $t", True),
            ("SELECT * FROM credential", True),
            ("SELECT * FROM open_notebook:default_models", True),
            ("SELECT * FROM notebook", False),
            ("SELECT * FROM source WHERE id IN $ids", False),
            ("CREATE usage_event CONTENT $e;", False),
            ("SELECT * FROM chat_session, model", False),
            ("RETURN 1", False),
        ],
    )
    def test_shared_detection(self, query, shared):
        assert tenancy.is_shared_query(query, {}) is shared

    def test_record_id_vars_decide(self):
        from surrealdb import RecordID

        assert tenancy.is_shared_query("SELECT * FROM $id", {"id": RecordID("model", "x")})
        assert not tenancy.is_shared_query("SELECT * FROM $id", {"id": RecordID("note", "x")})

    def test_database_selection(self):
        from open_notebook.database.repository import (
            get_core_database_name,
            get_database_name,
        )

        with tenancy.tenant_scope(ALICE.id):
            assert get_database_name() == tenancy.tenant_db_name(ALICE.id)
            assert get_database_name(shared=True) == get_core_database_name()
            with tenancy.unrouted():
                assert get_database_name(shared=True) == tenancy.tenant_db_name(ALICE.id)
        assert get_database_name() == get_core_database_name()

    def test_data_folders_are_private(self):
        with tenancy.tenant_scope(ALICE.id):
            a = tenancy.studio_folder()
        with tenancy.tenant_scope(BOB.id):
            b = tenancy.studio_folder()
        assert a != b and tenancy.tenant_db_name(ALICE.id) in str(a)

    def test_chat_threads_are_namespaced(self):
        cfg = {"configurable": {"thread_id": "chat_session:1"}}
        with tenancy.tenant_scope(ALICE.id):
            a = _scoped(cfg)["configurable"]["thread_id"]
            assert _scoped({"configurable": {"thread_id": a}})["configurable"]["thread_id"] == a
        with tenancy.tenant_scope(BOB.id):
            b = _scoped(cfg)["configurable"]["thread_id"]
        assert a != b


class TestJobs:
    @pytest.mark.asyncio
    async def test_jobs_are_private(self):
        from open_notebook.tut import jobs

        async def work(run):
            return None

        with tenancy.tenant_scope(ALICE.id):
            run = jobs.start("studio", work, feature="studio")
            assert jobs.get_run(run.id) is run
        with tenancy.tenant_scope(BOB.id):
            assert jobs.get_run(run.id) is None
        await run.task
