"""
Pytest configuration file.

This file ensures that the project root is in the Python path,
allowing tests to import from the api and open_notebook modules.
"""

import os
import sys
from pathlib import Path

# Account secrets for tests (never the production values)
os.environ.setdefault("MCIT_AUTH_SECRET", "test-secret-not-for-production")

# Load environment variables from .env file
# This must be done BEFORE any imports that depend on environment variables
from dotenv import load_dotenv

# Load .env file from project root
dotenv_path = Path(__file__).parent.parent / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path)
    print(f"Loaded environment variables from {dotenv_path}")
else:
    print(f"Warning: .env file not found at {dotenv_path}")

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


import pytest  # noqa: E402

_AUTH_TEST_MODULES = {"test_auth"}


@pytest.fixture(autouse=True)
def _signed_in_admin(request, monkeypatch):
    """API tests run as a signed-in administrator in core scope.

    The session middleware is exercised for real in tests/test_auth.py; every
    other test predates accounts and talks to routers directly.
    """
    if request.module.__name__.rsplit(".", 1)[-1] in _AUTH_TEST_MODULES:
        yield
        return
    from api.auth import SessionAuthMiddleware
    from open_notebook import accounts, tenancy

    admin = accounts.Account(id="mcit_user:test", username="admin", role="admin")

    async def dispatch(self, req, call_next):
        req.state.account = admin
        req.state.tenant_user = None
        tenancy.set_tenant(None)
        return await call_next(req)

    monkeypatch.setattr(SessionAuthMiddleware, "dispatch", dispatch)
    yield
