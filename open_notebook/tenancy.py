"""Per-user isolation for MCIT AI.

Every user owns a private SurrealDB database (``u_<user id>``) inside the
configured namespace and a private data folder (``data/users/<user id>``).
Notebooks, sources, notes, chats, embeddings, podcasts episodes, generated
Studio files and usage events therefore live in storage that no other user's
request can address: the database a query runs against is chosen from the
authenticated request, not from anything the client sends.

Platform configuration that the administrator manages for everyone (models,
provider credentials, transformations, podcast profiles and the
``open_notebook:*`` settings records) stays in the shared core database. The
repository layer routes a query there only when every table it touches is in
``SHARED_TABLES``.

The tenant is carried in a context variable, so it follows a request through
``await`` chains and into background tasks started from it. Jobs handed to
the command worker carry it explicitly (see ``submit_command`` / ``command``).
"""

from __future__ import annotations

import contextvars
import functools
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional

from open_notebook.config import DATA_FOLDER

# Tables that hold platform-wide configuration managed by the administrator.
SHARED_TABLES = frozenset(
    {
        "model",
        "credential",
        "transformation",
        "episode_profile",
        "speaker_profile",
        "open_notebook",  # open_notebook:default_models, :content_settings, ...
        "mcit_user",
        "mcit_oidc_code",
        "mcit_audit",
    }
)

_SAFE = re.compile(r"[^a-zA-Z0-9_]")

# Database name of the active tenant (None = core/system scope)
_tenant_db: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mcit_tenant_db", default=None
)
_tenant_user: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "mcit_tenant_user", default=None
)
# When set, every query goes to the active tenant DB unrouted (migrations)
_routing_off: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mcit_routing_off", default=False
)


def tenant_db_name(user_id: str) -> str:
    """Stable, identifier-safe database name for a user id."""
    raw = user_id.split(":", 1)[-1]
    return "u_" + _SAFE.sub("_", raw)[:60]


def current_tenant_db() -> Optional[str]:
    return _tenant_db.get()


def current_tenant_user() -> Optional[str]:
    return _tenant_user.get()


def routing_disabled() -> bool:
    return _routing_off.get()


def set_tenant(user_id: Optional[str]) -> contextvars.Token:
    """Bind the current context to a user (or to core scope with None)."""
    _tenant_user.set(user_id)
    return _tenant_db.set(tenant_db_name(user_id) if user_id else None)


@contextmanager
def tenant_scope(user_id: Optional[str]) -> Iterator[None]:
    """Temporarily run code as ``user_id`` (None = core scope)."""
    t1 = _tenant_user.set(user_id)
    t2 = _tenant_db.set(tenant_db_name(user_id) if user_id else None)
    try:
        yield
    finally:
        _tenant_db.reset(t2)
        _tenant_user.reset(t1)


@contextmanager
def unrouted() -> Iterator[None]:
    """Send every query to the active database as-is (schema migrations)."""
    tok = _routing_off.set(True)
    try:
        yield
    finally:
        _routing_off.reset(tok)


# --------------------------------------------------------------------------
# Data folders
# --------------------------------------------------------------------------


def user_data_dir(user_id: Optional[str] = None) -> Path:
    """Private data folder of a user (the active tenant by default)."""
    uid = user_id or _tenant_user.get()
    if not uid:
        path = Path(DATA_FOLDER) / "core"
    else:
        path = Path(DATA_FOLDER) / "users" / tenant_db_name(uid)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def user_subdir(name: str, user_id: Optional[str] = None) -> Path:
    path = user_data_dir(user_id) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_folder() -> str:
    return str(user_subdir("uploads"))


def podcasts_folder() -> str:
    return str(user_subdir("podcasts"))


def studio_folder() -> Path:
    return user_subdir("studio")


def craft_workspace() -> Path:
    """Folder the Craft engines may read and write for the active user."""
    return user_subdir("craft")


# --------------------------------------------------------------------------
# Query routing
# --------------------------------------------------------------------------

_TABLE_REF = re.compile(
    r"\b(?:FROM|UPDATE|UPSERT|CREATE|DELETE|INTO|ONLY|RELATE)\s+(?:ONLY\s+)?"
    r"([a-zA-Z_][a-zA-Z0-9_]*)(?=[\s:;,()\[]|$)",
    re.IGNORECASE,
)
_KEYWORDS = frozenset(
    {"only", "select", "type", "array", "string", "value", "none", "null", "return"}
)


def _table_of(value: Any) -> Optional[str]:
    tb = getattr(value, "table_name", None)
    if isinstance(tb, str):
        return tb
    return None


def tables_in(query: str, vars: Optional[Dict[str, Any]] = None) -> set:
    found = {
        m.group(1).lower()
        for m in _TABLE_REF.finditer(query or "")
        if m.group(1).lower() not in _KEYWORDS
    }
    for v in (vars or {}).values():
        items = v if isinstance(v, (list, tuple)) else [v]
        for item in items:
            tb = _table_of(item)
            if tb:
                found.add(tb.lower())
    return found


def is_shared_query(query: str, vars: Optional[Dict[str, Any]] = None) -> bool:
    tables = tables_in(query, vars)
    return bool(tables) and tables <= SHARED_TABLES


def is_shared_table(table: str) -> bool:
    return table.split(":", 1)[0].lower() in SHARED_TABLES


# --------------------------------------------------------------------------
# Background commands carry the tenant explicitly
# --------------------------------------------------------------------------

TENANT_ARG = "tenant"


def submit_command(app: str, name: str, args: Dict[str, Any], *a, **kw):
    """Drop-in for ``surreal_commands.submit_command`` that records the tenant."""
    from surreal_commands import submit_command as _submit

    payload = dict(args or {})
    payload.setdefault(TENANT_ARG, _tenant_user.get())
    return _submit(app, name, payload, *a, **kw)


def execute_command_sync(app: str, name: str, args: Dict[str, Any], *a, **kw):
    from surreal_commands import execute_command_sync as _exec

    payload = dict(args or {})
    payload.setdefault(TENANT_ARG, _tenant_user.get())
    return _exec(app, name, payload, *a, **kw)


def command(*dargs, **dkwargs) -> Callable:
    """Drop-in for ``surreal_commands.command`` that restores the tenant.

    The handler runs inside ``tenant_scope(input.tenant)``. Input models must
    derive from ``TenantCommandInput`` so the field survives validation.
    """
    from surreal_commands import command as _command

    def wrap(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def runner(input_data, *a, **kw):
            with tenant_scope(getattr(input_data, TENANT_ARG, None)):
                return await fn(input_data, *a, **kw)

        return _command(*dargs, **dkwargs)(runner)

    return wrap


def _make_input_base():
    from typing import Optional as _Opt

    from surreal_commands import CommandInput

    class TenantCommandInput(CommandInput):
        tenant: _Opt[str] = None

    return TenantCommandInput


TenantCommandInput = _make_input_base()


def core_database_name() -> str:
    return os.getenv("SURREAL_DATABASE") or "open_notebook"
