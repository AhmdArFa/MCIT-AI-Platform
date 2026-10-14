"""OpenID Connect provider: one login for MCIT AI and Tut Agent.

Tut Agent (the MCIT-Agent app) is registered as the single OIDC client
(``AUTH_SSO_PROVIDERS=generic-oidc``, password sign-in disabled there). When
a user opens Tut Agent it redirects here; a signed-in MCIT AI session is
accepted silently, otherwise the user signs in on the MCIT AI login page and
comes back. Accounts, roles and passwords are managed only in MCIT AI.

Issuer: ``{MCIT_PUBLIC_URL}/api/oidc``. Authorization code flow with PKCE
support, RS256 tokens, key kept in the data volume.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm

from api.auth import SESSION_COOKIE
from open_notebook import accounts, tenancy
from open_notebook.config import DATA_FOLDER
from open_notebook.database.repository import repo_query

router = APIRouter(prefix="/oidc", tags=["oidc"])

CODE_SECONDS = 120
TOKEN_SECONDS = 3600


def _public_base() -> str:
    return (os.getenv("MCIT_PUBLIC_URL") or "http://localhost:8502").rstrip("/")


def issuer() -> str:
    return (os.getenv("MCIT_OIDC_ISSUER") or _public_base() + "/api/oidc").rstrip("/")


def _client_id() -> str:
    return os.getenv("TUT_OIDC_CLIENT_ID") or "tut-agent"


def _client_secret() -> str:
    return os.getenv("TUT_OIDC_CLIENT_SECRET") or ""


def _allowed_redirect(uri: str) -> bool:
    allowed = [
        u.strip().rstrip("/")
        for u in (os.getenv("TUT_OIDC_REDIRECT_ORIGINS") or os.getenv("TUT_AGENT_PUBLIC_URL") or "").split(",")
        if u.strip()
    ]
    if not allowed:
        return False
    parsed = urlparse(uri)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return parsed.scheme in ("http", "https") and origin in allowed


def _email_for(account: accounts.Account) -> str:
    return f"{account.username}@{os.getenv('MCIT_EMAIL_DOMAIN') or 'mcit.local'}"


_key_cache: Optional[rsa.RSAPrivateKey] = None


def _private_key() -> rsa.RSAPrivateKey:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    path = Path(DATA_FOLDER) / "core" / "oidc_signing_key.pem"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        os.chmod(path, 0o600)
    _key_cache = key  # type: ignore[assignment]
    return key  # type: ignore[return-value]


def _kid() -> str:
    pub = _private_key().public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(pub).hexdigest()[:16]


def _sign(claims: Dict[str, Any]) -> str:
    return jwt.encode(claims, _private_key(), algorithm="RS256", headers={"kid": _kid()})


@router.get("/.well-known/openid-configuration")
async def discovery():
    iss = issuer()
    public = _public_base() + "/api/oidc"
    return {
        "issuer": iss,
        "authorization_endpoint": f"{public}/authorize",
        "token_endpoint": f"{iss}/token",
        "userinfo_endpoint": f"{iss}/userinfo",
        "jwks_uri": f"{iss}/jwks",
        "end_session_endpoint": f"{iss}/logout",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "claims_supported": ["sub", "name", "preferred_username", "email", "email_verified", "role"],
    }


@router.get("/jwks")
async def jwks():
    jwk = RSAAlgorithm.to_jwk(_private_key().public_key(), as_dict=True)
    jwk.update({"kid": _kid(), "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str = "code",
    scope: str = "openid",
    state: Optional[str] = None,
    nonce: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
):
    if client_id != _client_id() or not _allowed_redirect(redirect_uri):
        raise HTTPException(status_code=400, detail="Unknown client or redirect address")
    if response_type != "code":
        raise HTTPException(status_code=400, detail="Only the authorization code flow is supported")

    claims = accounts.decode_session(request.cookies.get(SESSION_COOKIE) or "")
    account = await accounts.get_account(claims["sub"]) if claims else None
    if not account or not account.active:
        here = str(request.url.path) + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse(f"/login?{urlencode({'next': here})}", status_code=302)

    code = secrets.token_urlsafe(32)
    with tenancy.tenant_scope(None):
        await repo_query(
            "CREATE mcit_oidc_code CONTENT $c",
            {
                "c": {
                    "code_hash": hashlib.sha256(code.encode()).hexdigest(),
                    "user": account.id,
                    "redirect_uri": redirect_uri,
                    "nonce": nonce,
                    "scope": scope,
                    "challenge": code_challenge,
                    "challenge_method": code_challenge_method or ("plain" if code_challenge else None),
                    "expires": datetime.now(timezone.utc) + timedelta(seconds=CODE_SECONDS),
                }
            },
        )
    await accounts.audit("auth.tut_agent_login", actor=account.id)
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


def _client_auth(request: Request, client_id: Optional[str], client_secret: Optional[str]) -> None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("basic "):
        try:
            raw = base64.b64decode(header.split(" ", 1)[1]).decode()
            client_id, client_secret = raw.split(":", 1)
        except Exception:
            raise HTTPException(status_code=401, detail="invalid_client")
    from urllib.parse import unquote

    cid, csec = unquote(client_id or ""), unquote(client_secret or "")
    expected = _client_secret()
    if cid != _client_id() or not expected or not hmac.compare_digest(csec, expected):
        raise HTTPException(status_code=401, detail="invalid_client")


def _pkce_ok(row: Dict[str, Any], verifier: Optional[str]) -> bool:
    challenge = row.get("challenge")
    if not challenge:
        return True
    if not verifier:
        return False
    if row.get("challenge_method") == "S256":
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        return hmac.compare_digest(digest, challenge)
    return hmac.compare_digest(verifier, challenge)


@router.post("/token")
async def token(
    request: Request,
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
):
    _client_auth(request, client_id, client_secret)
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    with tenancy.tenant_scope(None):
        rows = await repo_query(
            "DELETE mcit_oidc_code WHERE code_hash = $h RETURN BEFORE", {"h": code_hash}
        )
        await repo_query("DELETE mcit_oidc_code WHERE expires < time::now()")
    row = rows[0] if rows else None
    expires = row.get("expires") if row else None
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    if (
        not row
        or row.get("redirect_uri") != redirect_uri
        or not expires
        or expires < datetime.now(timezone.utc)
        or not _pkce_ok(row, code_verifier)
    ):
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    account = await accounts.get_account(row["user"])
    if not account or not account.active:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    now = int(time.time())
    base = {"iss": issuer(), "sub": account.id, "iat": now, "exp": now + TOKEN_SECONDS}
    profile = {
        "name": account.display_name or account.username,
        "preferred_username": account.username,
        "email": _email_for(account),
        "email_verified": True,
        "role": account.role,
    }
    id_token = _sign({**base, "aud": _client_id(), "nonce": row.get("nonce"), **profile})
    access_token = _sign({**base, "aud": "mcit-ai", "scope": row.get("scope", "openid"), "typ": "access"})
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": TOKEN_SECONDS,
        "id_token": id_token,
        "scope": row.get("scope", "openid"),
    }


@router.get("/userinfo")
async def userinfo(request: Request):
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="invalid_token")
    try:
        claims = jwt.decode(
            header.split(" ", 1)[1],
            _private_key().public_key(),
            algorithms=["RS256"],
            audience="mcit-ai",
            issuer=issuer(),
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid_token")
    account = await accounts.get_account(claims["sub"])
    if not account or not account.active:
        raise HTTPException(status_code=401, detail="invalid_token")
    return {
        "sub": account.id,
        "name": account.display_name or account.username,
        "preferred_username": account.username,
        "email": _email_for(account),
        "email_verified": True,
        "role": account.role,
    }


@router.get("/logout")
async def end_session(post_logout_redirect_uri: Optional[str] = None):
    target = post_logout_redirect_uri if post_logout_redirect_uri and _allowed_redirect(post_logout_redirect_uri) else "/login"
    response = RedirectResponse(target, status_code=302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
