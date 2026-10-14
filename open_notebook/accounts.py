"""MCIT AI accounts: one shared login for the whole platform.

* Accounts live in the core database (table ``mcit_user``).
* Passwords are hashed with scrypt (stdlib), never stored or logged in clear.
* Sessions are HS256 JWTs signed with ``MCIT_AUTH_SECRET`` (generated and
  kept in the data volume when the variable is not set).
* A bootstrap administrator (``admin`` / ``MCIT_ADMIN_PASSWORD``, default
  ``1234``) is created on first start. Only administrators create users and
  set passwords; users cannot register themselves.
* Each account gets a private database and data folder (see ``tenancy``),
  provisioned with the full schema when the account is created.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import jwt
from loguru import logger
from pydantic import BaseModel

from open_notebook import tenancy
from open_notebook.config import DATA_FOLDER
from open_notebook.database.repository import ensure_record_id, repo_query

Role = Literal["admin", "user"]

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{2,40}$")
SESSION_HOURS = int(os.getenv("MCIT_SESSION_HOURS", "12") or 12)
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "1234"


class Account(BaseModel):
    id: str
    username: str
    display_name: str = ""
    role: Role = "user"
    active: bool = True
    token_version: int = 0
    created: Optional[str] = None
    last_login: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _public(row: Dict[str, Any]) -> Account:
    def iso(v):
        return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)

    return Account(
        id=str(row["id"]),
        username=row.get("username", ""),
        display_name=row.get("display_name") or row.get("username", ""),
        role=row.get("role", "user"),
        active=bool(row.get("active", True)),
        token_version=int(row.get("token_version") or 0),
        created=iso(row.get("created")),
        last_login=iso(row.get("last_login")),
    )


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------


def _secret_file(name: str) -> Path:
    path = Path(DATA_FOLDER) / "core" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def auth_secret() -> str:
    env = (os.getenv("MCIT_AUTH_SECRET") or "").strip()
    if env:
        return env
    path = _secret_file(".auth_secret")
    if not path.exists():
        path.write_text(secrets.token_hex(32), "utf-8")
        os.chmod(path, 0o600)
    return path.read_text("utf-8").strip()


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except Exception:
        return False


def validate_password(password: str) -> None:
    if not password or len(password) < 4:
        raise ValueError("Password must be at least 4 characters")
    if len(password) > 256:
        raise ValueError("Password is too long")


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------


def issue_session(account: Account, hours: Optional[int] = None, scope: str = "app") -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=hours or SESSION_HOURS)
    token = jwt.encode(
        {
            "sub": account.id,
            "usr": account.username,
            "role": account.role,
            "typ": "session",
            "scp": scope,
            "ver": account.token_version,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        },
        auth_secret(),
        algorithm="HS256",
    )
    return {"token": token, "expires_at": exp.isoformat(), "user": account.model_dump()}


def decode_session(token: str) -> Optional[Dict[str, Any]]:
    try:
        claims = jwt.decode(token, auth_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != "session" or not claims.get("sub"):
        return None
    return claims


# --------------------------------------------------------------------------
# Storage (core database)
# --------------------------------------------------------------------------


async def _rows(query: str, vars: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    with tenancy.tenant_scope(None):
        return await repo_query(query, vars or {}) or []


async def get_account(user_id: str) -> Optional[Account]:
    if not user_id.startswith("mcit_user:"):
        return None
    rows = await _rows("SELECT * FROM $id", {"id": ensure_record_id(user_id)})
    return _public(rows[0]) if rows else None


async def _get_row_by_username(username: str) -> Optional[Dict[str, Any]]:
    rows = await _rows(
        "SELECT * FROM mcit_user WHERE username = $u LIMIT 1", {"u": username.lower()}
    )
    return rows[0] if rows else None


async def list_accounts() -> List[Account]:
    rows = await _rows("SELECT * FROM mcit_user ORDER BY created ASC")
    return [_public(r) for r in rows]


async def authenticate(username: str, password: str) -> Optional[Account]:
    row = await _get_row_by_username((username or "").strip())
    if not row or not row.get("active", True):
        # Spend comparable time when the user does not exist
        verify_password(password or "", hash_password("timing-equaliser"))
        return None
    if not verify_password(password or "", row.get("password_hash", "")):
        return None
    await _rows(
        "UPDATE $id SET last_login = time::now()", {"id": ensure_record_id(str(row["id"]))}
    )
    return _public(row)


async def create_account(
    username: str, password: str, role: Role = "user", display_name: str = ""
) -> Account:
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 2-40 characters: letters, digits, dot, dash or underscore"
        )
    validate_password(password)
    if await _get_row_by_username(username):
        raise ValueError("That username is already taken")
    rows = await _rows(
        "CREATE mcit_user CONTENT $data",
        {
            "data": {
                "username": username,
                "display_name": display_name.strip() or username,
                "role": role,
                "active": True,
                "token_version": 0,
                "password_hash": hash_password(password),
                "created": datetime.now(timezone.utc),
            }
        },
    )
    account = _public(rows[0])
    await provision_tenant(account.id)
    await audit("user.created", target=account.id, detail={"username": username, "role": role})
    return account


async def update_account(
    user_id: str,
    *,
    display_name: Optional[str] = None,
    role: Optional[Role] = None,
    active: Optional[bool] = None,
    password: Optional[str] = None,
) -> Account:
    patch: Dict[str, Any] = {}
    if display_name is not None:
        patch["display_name"] = display_name.strip()
    if role is not None:
        patch["role"] = role
    if active is not None:
        patch["active"] = active
    if password is not None:
        validate_password(password)
        patch["password_hash"] = hash_password(password)
        current = await get_account(user_id)
        if not current:
            raise ValueError("User not found")
        patch["token_version"] = current.token_version + 1
    if patch:
        await _rows("UPDATE $id MERGE $p", {"id": ensure_record_id(user_id), "p": patch})
    account = await get_account(user_id)
    if not account:
        raise ValueError("User not found")
    return account


async def delete_account(user_id: str) -> None:
    """Remove the account and its private database. Files stay on disk for
    the operator to archive (``data/users/<db>``)."""
    db = tenancy.tenant_db_name(user_id)
    await _rows("DELETE $id", {"id": ensure_record_id(user_id)})
    try:
        await _rows(f"REMOVE DATABASE IF EXISTS {db}")
    except Exception as e:
        logger.warning(f"Could not remove database for {user_id}: {type(e).__name__}")


async def count_admins() -> int:
    rows = await _rows(
        "SELECT count() AS n FROM mcit_user WHERE role = 'admin' AND active = true GROUP ALL"
    )
    return int(rows[0]["n"]) if rows else 0


# --------------------------------------------------------------------------
# Audit trail (core database, admin-visible)
# --------------------------------------------------------------------------


async def audit(
    action: str,
    actor: Optional[str] = None,
    target: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        await _rows(
            "CREATE mcit_audit CONTENT $e",
            {
                "e": {
                    "action": action,
                    "actor": actor or tenancy.current_tenant_user(),
                    "target": target,
                    "detail": detail or {},
                    "created": datetime.now(timezone.utc),
                }
            },
        )
    except Exception as e:
        logger.warning(f"Audit write failed: {type(e).__name__}")


async def recent_audit(limit: int = 100, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if user_id:
        return await _rows(
            "SELECT * FROM mcit_audit WHERE actor = $u OR target = $u ORDER BY created DESC LIMIT $n",
            {"u": user_id, "n": limit},
        )
    return await _rows("SELECT * FROM mcit_audit ORDER BY created DESC LIMIT $n", {"n": limit})


# --------------------------------------------------------------------------
# Tenant databases
# --------------------------------------------------------------------------


async def provision_tenant(user_id: str) -> None:
    """Create/upgrade the user's private database to the current schema."""
    from open_notebook.database.async_migrate import AsyncMigrationManager

    with tenancy.tenant_scope(user_id), tenancy.unrouted():
        manager = AsyncMigrationManager()
        if await manager.needs_migration():
            await manager.run_migration_up()
    tenancy.user_data_dir(user_id)


async def bootstrap() -> None:
    """Startup: schema for accounts, bootstrap admin, upgrade every tenant."""
    await _rows(
        "DEFINE TABLE IF NOT EXISTS mcit_user SCHEMALESS; "
        "DEFINE INDEX IF NOT EXISTS mcit_user_username ON mcit_user FIELDS username UNIQUE; "
        "DEFINE TABLE IF NOT EXISTS mcit_audit SCHEMALESS; "
        "DEFINE TABLE IF NOT EXISTS mcit_oidc_code SCHEMALESS;"
    )
    username = (os.getenv("MCIT_ADMIN_USERNAME") or DEFAULT_ADMIN_USERNAME).strip().lower()
    password = os.getenv("MCIT_ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
    row = await _get_row_by_username(username)
    if not row:
        await create_account(username, password, role="admin", display_name="Administrator")
        logger.info(f"Created bootstrap administrator '{username}'")
    elif row.get("role") != "admin":
        await update_account(str(row["id"]), role="admin", active=True)
    if password == DEFAULT_ADMIN_PASSWORD:
        logger.warning(
            "The administrator uses the default password. Change it from the admin "
            "console or set MCIT_ADMIN_PASSWORD before exposing this instance."
        )
    for account in await list_accounts():
        try:
            await provision_tenant(account.id)
        except Exception as e:
            logger.error(f"Schema upgrade failed for {account.username}: {e}")
