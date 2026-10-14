"""ONLYOFFICE callback cannot fetch attacker-controlled URLs."""

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import office


def test_callback_rejects_unexpected_download_origin(monkeypatch):
    monkeypatch.setenv("ONLYOFFICE_PUBLIC_URL", "http://localhost:8082")
    monkeypatch.setenv("ONLYOFFICE_INTERNAL_URL", "http://office")
    monkeypatch.setenv("ONLYOFFICE_JWT_SECRET", "office-test-secret")
    ticket = office._ticket("file-id", "mcit_user:alice")
    malicious = jwt.encode(
        {"status": 2, "url": "http://169.254.169.254/latest/meta-data"},
        "office-test-secret",
        algorithm="HS256",
    )
    app = FastAPI()
    app.include_router(office.router, prefix="/api")
    response = TestClient(app).post(f"/api/office/callback/{ticket}", json={"token": malicious})
    assert response.status_code == 403


def test_callback_requires_document_server_signature(monkeypatch):
    monkeypatch.setenv("ONLYOFFICE_JWT_SECRET", "office-test-secret")
    ticket = office._ticket("file-id", "mcit_user:alice")
    app = FastAPI()
    app.include_router(office.router, prefix="/api")
    response = TestClient(app).post(
        f"/api/office/callback/{ticket}", json={"status": 2, "url": "http://office/save"}
    )
    assert response.status_code == 403
